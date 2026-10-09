"""Original-commit certification for trusted GitHub Actions callers."""
POLICY_VERSION = "2"
GATE_CONTEXT = "DCO-owned"
AUDIT_NAME = "DCO audit"


class Refused(RuntimeError):
    """Evidence cannot support certification."""


class Draft(Refused):
    """No publication is permitted after observing a draft."""


class Obsolete(Refused):
    """A newer execution or changed generation superseded this invocation."""
