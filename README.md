# DCO checker

An immutable GitHub composite action that certifies original contributions under
the [Developer Certificate of Origin](https://developercertificate.org/).
It publishes `DCO-owned` on the captured pull request head or merge-group head.

## Install

Copy [the caller](examples/dco.yml) to `.github/workflows/dco.yml` and replace
`REPLACE_WITH_REVIEWED_COMMIT_SHA` with a reviewed **full 40-character release SHA**.
The caller executes the pinned action without checking out contribution code or
loading artifacts. Set a required status check named `DCO-owned` from GitHub
Actions after observing its check on a ready PR and, when used, a merge group.
Keep your other required checks and merge-queue configuration.

The initial supported environment is **GitHub.com, GitHub-hosted Ubuntu 24.04,
and Python 3.11 or newer**. The action uses Python's standard-library HTTP client;
`gh` is an operator tool, not a runtime dependency. GitHub Enterprise and
self-hosted runners are not qualified release targets. Required token permissions
are `contents: read`, `pull-requests: read`, `actions: read`, and `checks: write`.

The default CI display name is `CI` and filename is `ci.yml`. If yours differ,
change `workflow_run.workflows` in the caller and the action's `ci-workflow` input.
A trusted completion of CI supplies the write-capable follow-up for Dependabot.
Manual rechecks use the caller's `workflow_dispatch` with a ready PR number.
Checks UI rerun requests are not an action input; dispatch the workflow instead.

## Certification

Each result records repository, original PR identities, base/head SHAs, checker
revision, and policy version. Commit inventories use complete immutable paginated
comparisons, including contributions after position 250. Merge groups map their
structured queue ancestry to original member PRs; synthetic queue sign-offs do
not substitute for original certification. All open PR contexts sharing a head
are evaluated together.

A current ready target receives a pending check before scanning and a terminal
update on that same check. Interrupted scans remain pending until another run
rechecks them. Publication reconciles ambiguous creation and refuses to replace
newer executions. Repository-wide serial caller execution with `queue: max` prevents delayed CI
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

Run `PYTHONPATH=scripts python3 -m unittest discover -s tests -v`.
[Contributing](CONTRIBUTING.md) describes sign-offs and release review.
Licensed under Apache-2.0.
