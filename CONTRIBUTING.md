# Contributing

Every nonexempt commit must include a valid final `Signed-off-by` trailer matching
its author or committer. Use `git commit --signoff`; sign only if you can certify
the [DCO](https://developercertificate.org/). Squash merge messages must also retain
a matching sign-off for the resulting commit.

Run `PYTHONPATH=scripts python3 -m unittest discover -s tests -v` on Python 3.11+
and inspect CI. Tests must exercise meaningful policy, evidence, transport, and
publication boundaries. Production certification never executes contribution code.
Keep runtime dependencies in Python's standard library.

Open draft PRs while implementation or evidence is incomplete. Required CI and
DCO checks gate delivery; code owners review workflow and checker changes. The
maintainer model and any required independent approvals are configured in branch
protection and documented in [operations](docs/operations.md). Record deliberate
bypasses rather than treating them as ordinary verification.

Release changes require documentation of policy differences, runtime scope, exact
SHAs, and qualification. See [qualification](docs/qualification.md).
