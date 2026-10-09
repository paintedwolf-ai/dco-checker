# Security and publisher trust

Repository writers, reviewed repository workflows, GitHub Actions, and the
reviewed pinned checker revision are trusted. Contribution code, commit display
text, event payload claims, and CI artifacts are not execution authority.
The checker never checks out a PR or executes its code. HTTP requests are limited
to the supported GitHub API with bounded budgets, versioned requests, validated
responses, and sanitized error diagnostics.

## Event authority

`pull_request_target` executes the base repository caller. Dependabot-initiated
direct jobs are skipped because their token is read-only; a verified CI completion
is the write-capable route. This event guard does not exempt commit policy or skip
Dependabot-triggered `workflow_run` certification. The checker rereads the
live PR and complete repository open-PR inventory, captures its original immutable
commits across every same-head context, and validates state before final
publication. `workflow_run` executes the default-branch caller and rereads the
completed CI run, workflow identity, repository, and exact captured run/head
identity. Consistent nonempty PR associations are validated; an empty list is only
a wakeup for fresh original-commit certification using the complete live open-PR
inventory at that exact head. No live matching contexts means obsolete work;
malformed or contradictory associations and incomplete inventory are rejected.
Stale heads are ignored. `workflow_dispatch` is a maintainer-triggered default-branch
recheck of current live PR state. `merge_group` executes the queue workflow and
resolves original members using GraphQL queue ancestry, validating membership
again after scanning. Missing or ambiguous evidence cannot certify a group.

Use the supplied serial caller and maintain the DCO workflow on the default and
queue base branch. Manual dispatch should target the default branch. Review all
changes to `.github/workflows/**`, action references, check-writing permissions,
and the checker implementation. Restrict `checks: write` and `statuses: write` to
reviewed publishers;
never pass a write-capable token into contribution code or artifact-driven scripts.

## Required-check binding

Binding the `DCO-owned` commit status to GitHub Actions rejects another app's
status. Runtime publication validates the observed GitHub Actions bot identity
as well as execution and evidence fields; a personal access token or another app
is not an interchangeable publisher. The distinct `DCO audit` check exposes evidence and is not the required gate. App binding does **not** uniquely authenticate this checker: another workflow with `statuses: write` can
publish that status context under the same app. Workflow protection, code ownership, reviewed
full-SHA pins, and trusted writers are the enforceable boundary of this design.
The evidence identity includes the trusted caller revision alongside the action
revision, policy, and target PR/group contexts. That identity and the run link
support auditing, not independent authorization
against a malicious trusted writer. A deployment requiring isolation from repository
writers needs a separately controlled publisher and credential architecture.

## Review controls

Protect default branches with required CI and DCO checks, disallow force pushes and
deletions, and require PR delivery. CODEOWNERS identifies review responsibility.
Use an approval count consistent with available independent reviewers; zero required approvals provides no independent review. Record administrator bypasses and emergency changes in release evidence.
See [SECURITY.md](../SECURITY.md) for reporting and incident response.
