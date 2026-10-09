# Hosted qualification, 2026-10-09

This record distinguishes development candidates and platform probes from final
release qualification. The first candidate was
`8c8e1ebd5dec2450ccc0796807b24ba9d9dc6f62`.
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

## Canonical status candidate 7a0e11

Candidate `7a0e11d8cf7d46d946bd151b99c234cc71431eef` passed strict
recording of the required status, distinct audit, evidence digest, actual caller
revision, and downloaded action revision:

| Scenario | Hosted evidence | Result |
| --- | --- | --- |
| Signed original contribution | [run 37988196265](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37988196265) | Success |
| Fresh unsigned contribution | [run 37988460330](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37988460330) | Failed status and audit |
| Genuine fork direct event | [run 37988483587](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37988483587) | Success |
| Authentic fork CI with empty PR associations | [run 37988499368](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37988499368) | Success after complete live inventory |
| Fresh merge-group head under required status app binding | [run 37987684566](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37987684566) | Success; queue accepted status from app 15368 |

The candidate's hosted CI passed 70 behavior and workflow contracts on Python
3.11–3.14 plus workflow lint. Bootstrap PR 10 was squash merged as
`736a365bc68ac489e49c55ee455a1ba57a37ad84`; its author and final DCO trailer
were verified after merging. Candidate evidence does not certify that different
squashed SHA. Final release evidence must use the exact released SHA and preserve
the additional long-inventory, draft, bot, and queue observations.


## Cumulative queue boundary correction

Negative qualification of the canonical candidate exposed a stale cumulative
queue group whose Git ancestry still contained unsigned PR 11, while its audit
listed only signed PR 13. The group was rebuilt and did not merge. The original
webhook payload was not retained; its event base is inferred from immutable Git
parents and audit behavior, and is not presented as a captured field. The
recorded regression fixture labels those inferences and replay assumptions.

Certification now captures the protected branch head with the queue inventory
and traverses every prefix to that root. The event base must occur on that
ancestry but does not terminate traversal. Immutable Git parent edges must
corroborate queue metadata. Root changes, withdrawn prefixes, or rewritten
metadata refuse success. The updated suite has 79 tests, including malformed-parent refusal and
independent recomputation of published evidence digests; genuine cumulative
queue qualification with retained webhook payloads remains required before
release.


Candidate `76373c28e004ca4d2b9728bcbcecf87c4cc262fb` passed genuine
two-member cumulative qualification in
[run 37990175214](https://github.com/paintedwolf-ai/dco-checker-qualification/actions/runs/37990175214).
The retained webhook event base was the preceding synthetic entry, rather than
the protected root. The audit included both original PRs 15 and 18, and the
recorder independently reconstructed their full captured queue prefix and
recomputed the digest shared by audit and required status. This establishes the
new captured event behavior; it does not retroactively turn the earlier inferred
payload into recorded evidence.
