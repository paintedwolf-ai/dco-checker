# DCO checker

An immutable GitHub composite action that certifies original contributions under
the [Developer Certificate of Origin](https://developercertificate.org/).
Its required `DCO-owned` commit status gates the captured pull request head or
merge-group head. A separate `DCO audit` check preserves certification evidence
and actionable contributor feedback.

## Install

Copy [the caller](examples/dco.yml) to `.github/workflows/dco.yml` and replace
`REPLACE_WITH_REVIEWED_COMMIT_SHA` with a reviewed **full 40-character release SHA**.
The caller executes the pinned action without checking out contribution code or
loading artifacts. Set a required status context named `DCO-owned` from GitHub Actions after
observing its commit status on a ready PR and, when used, a merge group.
`DCO audit` is the evidence record; require only the status gate.
Keep your other required checks and merge-queue configuration.

The initial supported environment is **GitHub.com, GitHub-hosted Ubuntu 24.04,
and Python 3.11 or newer**. The action uses Python's standard-library HTTP client;
`gh` is an operator tool, not a runtime dependency. GitHub Enterprise and
self-hosted runners are not qualified release targets. Required token permissions
are `contents: read`, `pull-requests: read`, `actions: read`, `checks: write`, and
`statuses: write`. Publication uses the caller's GitHub Actions `GITHUB_TOKEN`;
personal access tokens and tokens from another app are not supported publishers.

The default CI display name is `CI` and filename is `ci.yml`. If yours differ,
change `workflow_run.workflows` in the caller and the action's `ci-workflow` input.
A trusted completion of CI supplies the write-capable follow-up for Dependabot.
The caller skips only Dependabot-initiated `pull_request_target` jobs, whose token
is read-only; it retains the trusted CI completion even when its actor is Dependabot.
Human-triggered ready/edit events on a bot-authored PR can certify directly.
GitHub may omit CI PR associations, especially for forks; the verified exact CI
head then wakes a fresh certification using the complete live open-PR inventory.
Empty associations do not certify commits by themselves. Contradictory or malformed
associations are rejected.
Manual rechecks use the caller's `workflow_dispatch` with a ready PR number.
Checks UI rerun requests are not an action input; dispatch the workflow instead.

## Certification

Each result records repository, original PR identities, base/head SHAs, checker
revision, and policy version. Commit inventories use complete immutable paginated
comparisons, including contributions after position 250. Merge groups map their
structured queue ancestry to original member PRs; synthetic queue sign-offs do
not substitute for original certification. Complete paginated repository open-PR inventories supply all contexts sharing a
head, including genuine fork heads omitted by GitHub's commit-association REST
endpoint. Those contexts are evaluated together and revalidated before publication.

A current ready target receives a pending status before scanning and a pending
audit check identified by execution and immutable evidence. A terminal status is
published only after the identified audit check is complete. Interrupted scans remain pending until another run rechecks them. Publication reconciles ambiguous writes and refuses to replace newer executions.
Certification reserves capacity for pending, terminal, and ambiguous-write recovery
within GitHub's per-context status limit before it begins publication. Repository-wide serial caller execution with `queue: max` prevents delayed CI
completions from cancelling current work. GitHub bounds the queued backlog to 100
runs; operators must recheck dropped work after an exceptional event burst.
Obsolete validated events do no work.
Changed or unavailable evidence cannot produce success. Draft observations prevent
further check writes, including drafts among shared-head PR contexts. GitHub state
reads and check writes are separate API operations: a draft transition or repository
change immediately after the final read cannot be made atomic with publication.

Read the [policy](docs/policy.md), [trust model](docs/security-model.md),
[operations guide](docs/operations.md), and [qualification procedure](docs/qualification.md)
before enforcing the check across repositories.

## Development

On Python 3.11+, install development dependencies with
`python3 -m pip install -r requirements-dev.txt`, then run
`PYTHONPATH=scripts python3 -m unittest discover -s tests -v`.
The pinned PyYAML dependency validates workflow YAML only; it is not installed or
imported by the action. Semantic tests validate modern GitHub concurrency queues,
including job sections, alongside actionlint's narrowly scoped accommodation for
its unsupported `queue` key.
[Contributing](CONTRIBUTING.md) describes sign-offs and release review.
Licensed under Apache-2.0.
