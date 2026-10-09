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
