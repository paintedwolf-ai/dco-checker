"""Suite-independent required gate with execution identity and bounded capacity."""
import re
from . import GATE_CONTEXT, Obsolete, Refused
from .transport import APIError

IDENTITY = re.compile(r"^dco:v2:(\d+):(\d+):([0-9a-f]{64})$")
STATES = {"pending", "success", "failure", "error"}


class Gate:
    def __init__(self, github, sha, evidence, config):
        self.github, self.sha, self.evidence, self.config = github, sha, evidence, config
        self.identity = f"dco:v2:{config.run_id}:{config.attempt}:{evidence['digest']}"
        self.target_url = config.run_url + "#" + self.identity
        self.latest = None
        self.count = 0

    def validate(self, status, *, own=False):
        creator = status.get("creator") or {}
        if not isinstance(creator, dict):
            raise Refused("DCO gate has a malformed publisher identity")
        if (type(status.get("id")) is not int or status["id"] <= 0 or status.get("context") != GATE_CONTEXT or
            not isinstance(status.get("state"), str) or status["state"] not in STATES or creator.get("id") != 41898282 or
            creator.get("login") != "github-actions[bot]" or creator.get("type") != "Bot"):
            raise Refused("DCO gate has an unexpected status shape or publisher")
        target = status.get("target_url") or ""
        if not isinstance(target, str):
            raise Refused("DCO gate has malformed execution provenance")
        url, separator, fragment = target.partition("#")
        match = IDENTITY.fullmatch(fragment)
        if not separator or not match or url != f"https://github.com/{self.github.repository}/actions/runs/{match[1]}":
            raise Refused("DCO gate has no valid execution provenance")
        if int(match[1]) <= 0 or int(match[2]) <= 0:
            raise Refused("DCO gate has invalid execution identifiers")
        if own and target != self.target_url:
            raise Refused("DCO gate response belongs to different evidence or execution")
        return int(match[1]), int(match[2]), match[3]

    def inspect(self):
        statuses, seen, page = [], set(), 1
        while True:
            nodes = self.github.api(f"repos/{self.github.repository}/commits/{self.sha}/statuses?per_page=100&page={page}")
            if not isinstance(nodes, list) or len(nodes) > 100:
                raise Refused("Malformed commit status inventory")
            for node in nodes:
                if not isinstance(node, dict) or type(node.get("id")) is not int or node["id"] <= 0 or node["id"] in seen:
                    raise Refused("Invalid or repeated commit status inventory")
                seen.add(node["id"])
                if node.get("context") == GATE_CONTEXT:
                    generation = self.validate(node)
                    if generation[:2] > (self.config.run_id, self.config.attempt):
                        raise Obsolete("A newer DCO gate execution superseded this invocation")
                    statuses.append(node)
            if len(nodes) < 100:
                break
            page += 1
        # GitHub documents reverse chronological ordering; retain that authority.
        self.latest = statuses[0] if statuses else None
        self.count = len(statuses)
        return self.latest

    def post(self, state, description):
        # No status mutation is replayed on an unknown response: append-only API
        # writes are reconciled by exact execution/evidence/state instead.
        payload = {"context": GATE_CONTEXT, "state": state, "target_url": self.target_url,
                   "description": description[:140]}
        try:
            response = self.github.api(f"repos/{self.github.repository}/statuses/{self.sha}", payload, "POST")
            if not isinstance(response, dict):
                raise APIError("Status publication returned an invalid response", ambiguous=True)
            try:
                self.validate(response, own=True)
            except Refused as error:
                raise APIError("Status publication returned unverifiable provenance", ambiguous=True) from error
            if response["state"] != state:
                raise APIError("Status publication returned a different state", ambiguous=True)
            self.latest = response
        except APIError as error:
            if not error.ambiguous:
                raise
            recovered = self.inspect()
            if recovered is None or recovered.get("target_url") != self.target_url or recovered.get("state") != state:
                raise Refused("DCO status publication outcome is unknown; dispatch a new certification run") from error
        return self.latest

    def start(self):
        latest = self.inspect()
        # Two normal records plus one reserved blocking record prevent a final
        # success exhausting GitHub's 1000-status-per-SHA/context limit.
        if self.count >= 998:
            if self.count < 1000 and (latest is None or latest["state"] == "success"):
                self.post("pending", "DCO status capacity reached; push a fresh signed head commit")
            raise Refused("DCO status capacity reached; push a fresh signed head commit before certification")
        if latest is not None and latest.get("target_url") == self.target_url and latest["state"] == "pending":
            return latest
        return self.post("pending", "Original commit DCO certification in progress")

    def finish(self, state, description):
        latest = self.inspect()
        if latest is None or latest.get("target_url") != self.target_url:
            raise Refused("Pending DCO gate identity was lost")
        if latest["state"] == state:
            return
        if latest["state"] != "pending":
            raise Refused("DCO gate is already terminal for different evidence outcome")
        if self.count >= 999:
            raise Refused("DCO status capacity prevents a terminal result; push a fresh signed head commit")
        self.post(state, description)
