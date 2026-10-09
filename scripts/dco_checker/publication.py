"""Publish the required status and independently auditable rich check in order."""
from . import Refused
from .checks import Audit
from .statuses import Gate


class Publication:
    def __init__(self, github, sha, evidence, config):
        self.audit = Audit(github, sha, evidence, config)
        self.gate = Gate(github, sha, evidence, config)
        self.reusable = False

    @property
    def check(self):
        return self.audit.check

    def recover_terminal(self):
        existing_audit = self.audit.reconcile()
        existing_gate = self.gate.inspect()
        if (existing_audit is not None and existing_audit.get("status") == "completed" and
            existing_gate is not None and existing_gate.get("target_url") == self.gate.target_url and
            existing_gate["state"] in ("success", "failure", "error") and
            (existing_audit.get("conclusion") == "success") == (existing_gate["state"] == "success")):
            self.audit.check = existing_audit
            return existing_gate["state"]
        return None

    def start(self):
        latest = self.gate.inspect()
        if latest is not None and latest.get("target_url") == self.gate.target_url and latest["state"] != "pending":
            if self.recover_terminal() is not None:
                self.reusable = True
                return
        # A new execution invalidates an older success before accessing the
        # optional rich-audit service or scanning immutable commits.
        self.gate.start()
        self.audit.start()

    def finish(self, state, summary, description):
        if self.audit.check is None:
            raise Refused("Audit publication unavailable; required DCO status remains pending")
        # A suite-independent gate can only become successful after its rich
        # evidence record completes. Neither writer executes contribution code.
        self.audit.finish("success" if state == "success" else "failure", summary)
        self.gate.finish(state, description)
