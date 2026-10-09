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
on ready PRs plus merge groups if a queue is used. Configure `DCO-owned` with the
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

Pending checks indicate incomplete certification, not approval. Inspect the linked
run and dispatch a recheck after restoring API availability. Infrastructure failures
are distinct from rejected sign-offs. Never treat a successful unrelated workflow
job as DCO evidence. Serial execution can delay results under a large event burst;
obsolete events are skipped when reached, and new ready heads still require their
own successful check.
