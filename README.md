# DCO checker

A GitHub action maintained by Painted Wolf AI to certify contributions under the
[Developer Certificate of Origin](https://developercertificate.org/).

Copy [the caller workflow](examples/dco.yml) into `.github/workflows/dco.yml` in
each consuming repository. Replace `REPLACE_WITH_REVIEWED_COMMIT_SHA` with a
reviewed full commit SHA from this repository. Configure the branch ruleset to
require `DCO-owned` from GitHub Actions after confirming a successful check on a
ready pull request and a merge group. Preserve other required checks and the
merge queue. Keep the existing DCO requirement during migration.

The workflow needs `contents: read`, `pull-requests: read`, `actions: read`, and
`checks: write`. It runs this action's pinned code without checking out pull
request code or reading artifacts. It requires Python 3 and `gh`; both are
available on GitHub's Ubuntu runners. `workflow_run` provides a trusted
follow-up for Dependabot events whose direct token can be read-only.

If the caller's CI has a different display name, update `workflow_run.workflows`.
If its workflow filename differs from `ci.yml`, set the action's `ci-workflow`
input. For a manual recheck, dispatch the caller workflow with `pull_request`
set to a ready PR number.

The checker reads every page of an immutable base-to-head comparison. It
refuses incomplete inventories, changed PR identities, and ambiguous queue
membership. Merge groups certify their original member PR commits using
structured queue ancestry rather than GitHub's synthetic commit. Draft PRs,
including PRs returned to draft during certification, receive no check writes.

A sign-off must match the author or committer's name and email as a pair,
ignoring case. Merge commits and GitHub-identified bot authors are exempt.
There are no owner, member, or remediation exemptions. This action publishes
the `DCO-owned` check on the exact captured head and fails closed on incomplete
or changed evidence.

The standard-library unittest suite covers pagination above 250 commits,
identity matching, incomplete responses, merge group ancestry, trusted CI
association, and draft/head/base races. CI uses the same suite as the original
repository's verification infrastructure.

Licensed under Apache-2.0.
