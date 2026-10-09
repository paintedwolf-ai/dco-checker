"""A pending check identifies each execution; ambiguous writes are reconciled."""
import json
import re
from urllib.parse import urlencode
from . import AUDIT_NAME, Obsolete, POLICY_VERSION, Refused
from .transport import APIError

EXTERNAL = re.compile(r"^dco:v2:(\d+):(\d+):([0-9a-f]{64})$")


class Audit:
    def __init__(self, github, sha, evidence, config):
        self.github, self.sha, self.evidence, self.config = github, sha, evidence, config
        self.external_id = f"dco:v2:{config.run_id}:{config.attempt}:{evidence['digest']}"
        self.check = None

    def output(self, title, summary):
        # GitHub Actions may attach custom checks to an existing app suite and
        # rewrite details_url. Correlate execution using our explicit output,
        # never the suite workflow or GitHub-generated check details link.
        provenance = {"run_url": self.config.run_url, "run_id": self.config.run_id,
                      "attempt": self.config.attempt, "external_id": self.external_id,
                      "evidence_digest": self.evidence["digest"],
                      "checker_revision": self.config.revision, "caller_revision": self.config.caller_revision, "policy_version": POLICY_VERSION}
        return {"title": title,
                "summary": f"[Certification run]({self.config.run_url}) · attempt {self.config.attempt}\n\n" + summary,
                "text": "```json\n" + json.dumps(provenance, sort_keys=True) + "\n```"}

    def inventory(self):
        checks, page, total = [], 1, None
        while True:
            query = urlencode({"check_name": AUDIT_NAME, "filter": "all", "per_page": 100, "page": page})
            response = self.github.api(f"repos/{self.github.repository}/commits/{self.sha}/check-runs?{query}")
            if (not isinstance(response, dict) or type(response.get("total_count")) is not int or
                response["total_count"] < 0 or not isinstance(response.get("check_runs"), list)):
                raise Refused("Malformed check inventory")
            if total is not None and total != response["total_count"]:
                raise Refused("Check inventory changed during pagination")
            total = response["total_count"]
            nodes = response["check_runs"]
            if any(not isinstance(check, dict) or type(check.get("id")) is not int or check["id"] <= 0 for check in nodes):
                raise Refused("Invalid check inventory entry")
            checks += nodes
            if len({c["id"] for c in checks}) != len(checks) or len(checks) > total:
                raise Refused("Repeated check inventory")
            if len(checks) == total:
                return checks
            if len(nodes) != 100:
                raise Refused("Incomplete check inventory")
            page += 1

    def validate(self, check):
        if (not isinstance(check, dict) or type(check.get("id")) is not int or check["id"] <= 0 or
            check.get("name") != AUDIT_NAME or check.get("head_sha") != self.sha or
            not isinstance(check.get("app"), dict) or check["app"].get("id") != 15368 or
            check.get("external_id") != self.external_id):
            raise Refused("Check response does not match expected target, execution and GitHub Actions publisher")

    def reconcile(self):
        checks = self.inventory()
        for check in checks:
            if check.get("name") == AUDIT_NAME and (not isinstance(check.get("app"), dict) or check["app"].get("id") != 15368):
                raise Refused("DCO check was published by an unexpected app")
            match = EXTERNAL.fullmatch(check.get("external_id") or "")
            if check.get("name") != AUDIT_NAME or not match:
                continue
            if (int(match[1]), int(match[2])) > (self.config.run_id, self.config.attempt):
                raise Obsolete("A newer DCO execution superseded this invocation")
        matching = [check for check in checks if check.get("external_id") == self.external_id]
        if len(matching) > 1:
            raise Refused("Duplicate checks for one execution; publication refused")
        if matching:
            self.validate(matching[0])
        return matching[0] if matching else None

    def start(self):
        existing = self.reconcile()
        if existing:
            self.check = existing
            return
        payload = {"name": AUDIT_NAME, "head_sha": self.sha, "external_id": self.external_id,
                   "status": "in_progress", "details_url": self.config.run_url,
                   "output": self.output("DCO certification in progress", "Evaluating original commits against policy 2 and captured live PR contexts.")}
        try:
            self.check = self.github.api(f"repos/{self.github.repository}/check-runs", payload, "POST")
            if not isinstance(self.check, dict) or type(self.check.get("id")) is not int:
                raise APIError("Check creation returned an invalid response", ambiguous=True)
        except APIError as error:
            if not error.ambiguous:
                raise
            # Never replay a POST whose outcome is unknown.
            self.check = self.reconcile()
            if self.check is None:
                raise Refused("Check creation outcome is unknown; re-run certification to recover") from error
        self.validate(self.check)

    def completed(self, check, payload):
        self.validate(check)
        if check["id"] != self.check["id"]:
            raise Refused("Audit completion returned a different check identity")
        output = check.get("output")
        return (check.get("status") == "completed" and check.get("conclusion") == payload["conclusion"] and
                isinstance(output, dict) and all(output.get(key) == value for key, value in payload["output"].items()))

    def finish(self, conclusion, summary):
        current = self.reconcile()
        if current is None or current["id"] != self.check["id"]:
            raise Refused("Pending check identity was lost")
        payload = {"status": "completed", "conclusion": conclusion,
                   "output": self.output("DCO certified" if conclusion == "success" else "DCO certification failed", summary)}
        path = f"repos/{self.github.repository}/check-runs/{self.check['id']}"
        for attempt in range(2):
            try:
                response = self.github.api(path, payload, "PATCH")
                try:
                    verified = self.completed(response, payload)
                except (Refused, AttributeError, TypeError):
                    verified = False
                if not verified:
                    raise APIError("Audit completion response is unverifiable", ambiguous=True)
                self.check = response
                return
            except APIError as error:
                if not error.ambiguous:
                    raise
                recovered = self.github.api(path)
                # A GET for the identified check must retain the complete identity
                # before any retry; malformed or contradictory authority refuses.
                if self.completed(recovered, payload):
                    self.check = recovered
                    return
                if attempt == 1:
                    raise Refused("Audit completion could not be confirmed; required DCO gate remains pending") from error
                # One identified PATCH retry is idempotent. Reestablish current
                # execution authority rather than overwriting a newer publisher.
                current = self.reconcile()
                if current is None or current["id"] != self.check["id"]:
                    raise Refused("Audit check identity was lost during completion recovery")
