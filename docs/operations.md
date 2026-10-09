# Operations and releases

## Release contract

Supported releases identify an immutable full commit SHA, semantic version,
certification policy version, supported runtime, and qualification evidence.
Human-readable tags and GitHub releases aid discovery; consumers always pin the
full SHA. Patch releases repair defects without intended policy changes. Minor
releases add compatible behavior. Changes to certification policy or required
configuration need explicit migration notes and an appropriate major release.

Release through a draft PR while work and qualification remain incomplete. Run
CI, inspect the diff and audit output, and record hosted evidence against the exact
candidate SHA. Mark the PR ready when verification is sufficient, then squash with
a valid DCO trailer. Verify CI and DCO against the merged SHA before publishing
release notes. Any tested candidate SHA differing from the merged release SHA must
be identified clearly; rerun hosted qualification with the final SHA for release
claims about that final action. Attach reports and workflow/run links to the release.

## Consumer migration and rollback

Select a reviewed supported SHA, update the caller pin, and observe certification
on ready PRs plus merge groups if a queue is used. If the first caller is not yet
on the default branch, explicitly dispatch its reviewed installation PR branch
once GitHub has registered that workflow. Use
`gh workflow run dco.yml --ref REVIEWED_BRANCH -f pull_request=PR_NUMBER --repo OWNER/REPO`. Inspect the exact
caller revision, downloaded action SHA, original-commit audit, and required status
before changing enforcement. This deliberate bootstrap uses the real certification
implementation and repository Actions token; it does not publish an admission
success through a different implementation. Normal manual rechecks target the
default branch. If GitHub has not registered the new workflow, finish registration
through its supported workflow events before attempting dispatch; do not substitute
a fabricated status or remove other branch protections. Configure `DCO-owned` with the
GitHub Actions app identity and verify ruleset API readback. Remove the old DCO
requirement and uninstall the previous app once the replacement is active. Maintain
one implementation and one required DCO context in each migrated repository.

For regression response, restore the previous reviewed full SHA in the caller,
rerun current ready PRs, and record the affected version and evidence. Do not
silently disable the requirement. If the old policy is unsuitable, halt merging
until the repaired pin is reviewed and qualified. A first release has no previous
supported SHA; use an explicitly reviewed emergency fix rather than claiming a
known-good rollback target exists.

## Maintenance

The Painted Wolf AI repository maintainers own policy, action releases, protection,
and consumer upgrade coordination. Dependabot proposes updates for development
workflow actions; inspect permission and execution changes before accepting them.
No third-party Python package is required at runtime. Review GitHub API and hosted
runner changes as part of releases. Retain Actions logs and qualification JSON with
release records according to repository retention settings.

A rebuilt merge group needs fresh certification of its complete prefix back to
the current protected branch head. Removing a queue member does not make an old
dependent synthetic head eligible: its surviving suffix cannot certify an
absent contribution. Let GitHub rebuild the group and inspect the new audit.

Pending statuses and audit checks indicate incomplete certification, not approval. Inspect the linked
run and dispatch a recheck after restoring API availability. Infrastructure failures
are distinct from rejected sign-offs. Never treat a successful unrelated workflow job as DCO evidence. Require the
commit status gate rather than the Actions job or audit check; hosted qualification observed a successful custom Actions check on the exact head
while GitHub still reported the required check as expected. GitHub attached that
check to an older suite; the specific platform gating cause was not established.
The commit status gate was independently proven to satisfy the app-bound requirement. Serial execution can delay results under a large event burst;
obsolete events are skipped when reached, and new ready heads still require their
own successful check.

GitHub limits each context to 1,000 commit statuses per head. Certification starts
only with capacity for its normal pending and terminal records plus one blocking
recovery record. At the threshold it blocks certification and asks for a fresh
signed head commit; it does not silently retain a prior successful gate while
claiming to certify different evidence. A lost response is reconciled by exact
run, attempt, evidence digest, and intended state instead of blindly appending
another status. Permanent API denial may prevent a write; inspect the failed run
and existing gate rather than treating the run as proof of a new certification.

## Checker repository enforcement

The default branch requires the aggregate `check` and the `DCO-owned` status, both
bound to GitHub Actions (integration 15368). Delivery uses PRs and squash merges;
force pushes, deletion, and bypass actors are prohibited. Release tags matching
`v*` cannot be updated or deleted. Repository workflow tokens default to read
permissions, with publication rights explicitly granted only to the DCO caller.
Secret scanning, push protection, vulnerability alerts, automated security fixes,
and private vulnerability reporting are enabled.

Self-certification checks out the protected default branch without persisted Git
credentials and executes that trusted action. Its evidence records the actual
checkout SHA and caller workflow SHA. Initial installation requires one reviewed,
signed bootstrap merge before this workflow can run from the default branch;
observe a real status on the next signed PR before enabling the required context.
Subsequent deliveries must pass both gates, and squash messages retain a matching
final sign-off. Release qualification of a consumer still pins the exact resulting
merged SHA rather than substituting self-check evidence for consumer execution.
