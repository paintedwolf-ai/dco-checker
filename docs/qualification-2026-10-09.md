# Hosted qualification, 2026-10-09

This record covers development candidate
`8c8e1ebd5dec2450ccc0796807b24ba9d9dc6f62`, not a supported final release SHA.
The disposable public consumer is
[paintedwolf-ai/dco-checker-qualification](https://github.com/paintedwolf-ai/dco-checker-qualification).
Its caller pinned the full candidate SHA. Actual runner logs identified the
downloaded action SHA, Ubuntu 24.04, and the requested repository token permissions.

| Scenario | Observed result | Hosted evidence |
| --- | --- | --- |
| Signed original PR commit | Successful exact-head DCO check; 1 signed context | [PR 1](https://github.com/paintedwolf-ai/dco-checker-qualification/pull/1), [run 37984201676](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37984201676) |
| Unsigned original PR commit | Failed exact-head DCO check; 1 missing sign-off | [PR 2](https://github.com/paintedwolf-ai/dco-checker-qualification/pull/2), [run 37984213575](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37984213575) |
| Unsigned commit after position 250 | Failed exact-head DCO check; 251 contexts, 250 signed, 1 failed | [PR 5](https://github.com/paintedwolf-ai/dco-checker-qualification/pull/5), [run 37984547558](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37984547558) |
| Draft PR | No DCO-owned check on captured draft head | [PR 3](https://github.com/paintedwolf-ai/dco-checker-qualification/pull/3) |
| Authentic fork contribution | Candidate refused incomplete REST commit association; no certification | [PR 4](https://github.com/paintedwolf-ai/dco-checker-qualification/pull/4), [run 37984415880](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37984415880) |

The fork result revealed an API boundary rather than a sign-off failure: GitHub's
base-repository commit-to-PR REST endpoint returned an empty list, while GraphQL
exposed the open fork PR with the exact original head. The recorded fixture is
`tests/fixtures/authentic-fork-association.json`. Complete open-PR enumeration is
the resulting authority contract; qualification must rerun the authentic fork
against the corrected action before release.

GitHub rewrote the supplied `details_url` to its check UI and associated a custom
Actions check with an existing app suite. The recorder therefore verifies explicit
execution IDs, app identity, target head, immutable workflow source, and downloaded
action SHA. Production output adds an explicit workflow run link and structured
execution provenance. The development candidate predates that output and was
recorded with the explicit legacy flag, making its records ineligible as final
release qualification.

These observations do not establish genuine Dependabot behavior, merge-queue
enforcement, or verification of a later squashed release SHA. Final release notes
must link additional evidence and state any remaining qualification gaps.

## Corrected candidate d07f07

Candidate `d07f07c5df395ea5a625a0ae1fdaf08beffefec8` passed genuine
two-member merge-group certification and the protected fixture queue merged both
original PRs. The group target was
`8eb49cf4568377945420a240619da0fca1db76e2`; original members were PRs 1 and 6.
[Run 37985287486](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37985287486)
was independently recorded with exact downloaded SHA, caller source, structured
execution provenance, run link, expected app identity, and successful result.

The authentic fork passed a fresh manual certification with the corrected complete
open-PR inventory in
[run 37985409568](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37985409568).
A real attempt to enqueue unsigned PR 2 was rejected by the required `DCO-owned`
check. These are hosted enforcement observations, not merely local test results.

Further authentic fork CI completion exposed empty PR associations in GitHub's run
metadata. The revised fallback treats a verified exact-head CI completion only as
a wakeup, then establishes complete live PR authority and scans original commits.
Its local tests replay recorded empty associations and reject incomplete or
contradictory authority. This fallback revision requires subsequent hosted evidence
and does not inherit a successful claim from the manual fork certification.

## Required-status architecture qualification

A later signed fixture PR had a successful `DCO-owned` custom Actions check on its
exact head but GitHub still reported that the required check was expected. GitHub attached the check to an older Actions suite, and a newer suite did not
contain that custom check. Suite selection was a possible explanation, not a
proven causal mechanism. The observed successful-check/expected-gate mismatch
made the custom-check gate unsuitable as the sole production requirement.

A reviewed fixture-only publisher emitted a distinct `DCO-status-probe` commit
status on the authentic fork head in
[run 37986224580](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37986224580).
The status creator was GitHub Actions bot ID 41898282. With that status as the only
required context bound to integration 15368, GitHub accepted the same fork PR into
the protected merge queue. Other rules—including PR delivery, force-push/deletion
restrictions, and queue configuration—were preserved. This proves platform status
app binding and suite independence; the test-only success is not DCO certification.

The resulting shipped architecture uses a required `DCO-owned` commit status and
a distinct `DCO audit` rich check. Final qualification must verify both against
the same immutable evidence and actual downloaded release SHA.
