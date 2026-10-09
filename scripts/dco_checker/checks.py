"""A pending check identifies each execution; ambiguous writes are reconciled."""
import json
import re
from . import CHECK_NAME, Obsolete, POLICY_VERSION, Refused
from .transport import APIError

EXTERNAL = re.compile(r"^dco:v2:(\d+):(\d+):([0-9a-f]{64})$")


class Publisher:
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
                      "checker_revision": self.config.revision, "policy_version": POLICY_VERSION}
        return {"title": title,
                "summary": f"[Certification run]({self.config.run_url}) · attempt {self.config.attempt}\n\n" + summary,
                "text": "```json\n" + json.dumps(provenance, sort_keys=True) + "\n```"}

    def inventory(self):
        checks, page, total = [], 1, None
        while True:
            response = self.github.api(f"repos/{self.github.repository}/commits/{self.sha}/check-runs?check_name={CHECK_NAME}&filter=all&per_page=100&page={page}")
            if total is not None and total != response["total_count"]:
                raise Refused("Check inventory changed during pagination")
            total = response["total_count"]
            nodes = response["check_runs"]
            checks += nodes
            if len({c["id"] for c in checks}) != len(checks) or len(checks) > total:
                raise Refused("Repeated check inventory")
            if len(checks) == total:
                return checks
            if len(nodes) != 100:
                raise Refused("Incomplete check inventory")
            page += 1

    def validate(self, check):
        if (not isinstance(check, dict) or type(check.get("id")) is not int or
            check.get("name") != CHECK_NAME or check.get("head_sha") != self.sha or
            (check.get("app") or {}).get("id") != 15368 or
            check.get("external_id") != self.external_id):
            raise Refused("Check response does not match expected target, execution and GitHub Actions publisher")

    def reconcile(self):
        checks = self.inventory()
        for check in checks:
            if check.get("name") == CHECK_NAME and (check.get("app") or {}).get("id") != 15368:
                raise Refused("DCO check was published by an unexpected app")
            match = EXTERNAL.fullmatch(check.get("external_id") or "")
            if check.get("name") != CHECK_NAME or not match:
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
        payload = {"name": CHECK_NAME, "head_sha": self.sha, "external_id": self.external_id,
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

    def finish(self, conclusion, summary):
        current = self.reconcile()
        if current is None or current["id"] != self.check["id"]:
            raise Refused("Pending check identity was lost")
        payload = {"status": "completed", "conclusion": conclusion,
                   "output": self.output("DCO certified" if conclusion == "success" else "DCO certification failed", summary)}
        path = f"repos/{self.github.repository}/check-runs/{self.check['id']}"
        try:
            self.github.api(path, payload, "PATCH")
        except APIError as error:
            if not error.ambiguous:
                raise
            recovered = self.github.api(path)
            self.validate(recovered)
            if recovered.get("status") == "completed" and recovered.get("conclusion") == conclusion and recovered.get("output", {}).get("summary") == payload["output"]["summary"] and recovered.get("output", {}).get("text") == payload["output"]["text"]:
                return
            # PATCH is idempotent for this identified check, but verify supersession first.
            self.reconcile()
            self.github.api(path, payload, "PATCH")
