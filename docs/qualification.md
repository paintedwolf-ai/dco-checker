# Release qualification

Qualification distinguishes deterministic local contracts, live read-only probes,
and token-bearing hosted execution. Passing the unit suite is not evidence of
required-check enforcement or genuine Dependabot credentials.

## Hosted consumer

Provision an initialized disposable GitHub.com repository named
`OWNER/dco-qualification-NAME` or `OWNER/dco-checker-qualification`. Keep it separate
from production and record its visibility, default branch, ruleset, app binding,
and token scope. Use an operator `gh` login authorized to write workflows. If workflow writes are unavailable
to that token, install the reviewed callers using Git SSH and pass `--skip-install`. The
runtime action still uses its own `GITHUB_TOKEN` and standard-library HTTP.

Run the real candidate action using full SHA pins:

```sh
python3 tests/qualification/create_case.py \
  --repository OWNER/dco-checker-qualification \
  --action-sha FULL_REVIEWED_SHA --scenario signed --output /tmp/signed.json
```

The harness installs the caller and CI on the consumer's default branch using a
signed commit, then creates an actual PR. Available cases are `signed`, `unsigned`,
`unsigned-after-250`, and `draft`. The long inventory case has 251 original commits
and an unsigned final commit; its required check must fail. Drafts must receive no
check writes. The action is executed by GitHub Actions, reads real GitHub API data,
and writes using the real repository workflow token. Deliberately unsigned fixture
commits exist only in the disposable consumer.

After the actual DCO run completes, collect and independently verify its result:

```sh
python3 tests/qualification/record.py \
  --repository OWNER/dco-checker-qualification --run-id RUN_ID \
  --head FULL_PR_OR_GROUP_HEAD_SHA --action-sha FULL_REVIEWED_SHA \
  --scenario signed --expected-conclusion success --output /tmp/signed-result.json
```

The recorder verifies run identity, a composite certification step, exact check
head, execution identity, terminal outcome, GitHub Actions app ID, evidence identity, and
audit summary. GitHub rewrites Actions-created check URLs and may attach them to
an existing app suite, so exact execution matching uses the structured external ID,
not the check URL or suite ID. It preserves API run/job/check responses. It verifies the checker revision in the published audit summary and preserves
the immutable caller source at the run head, verifying its full-SHA pin. It does not itself establish branch-rule enforcement. Read the configured
ruleset back and attempt the expected merge rejection/acceptance in the disposable
consumer. Never interpret an Actions job result alone as the required DCO check.

## Scenario matrix

Record the actual trigger and immutable SHAs for each scenario:

| Boundary | Evidence required |
| --- | --- |
| Ordinary signed and unsigned PR | Exact-head success and failure checks from the composite action |
| More than 250 commits | Failed check identifies unsigned contribution after 250 |
| Fork PR | Genuine fork association, base-repository token publication, no contribution execution |
| Dependabot | Genuine Dependabot-generated PR and CI completion under actual token restrictions |
| Draft transitions | No writes when draft is observed; ready transition certifies original commits |
| Force push and delayed CI | Old completion cannot cancel or overwrite newer certification |
| Manual retry and duplicate events | Captured live generation, identified checks, no ambiguous POST replay |
| Multi-member merge group | Original commits, synthetic group head, membership reread and rebuilt group |
| Missing/changed queue entries | No successful certification on incomplete authority |
| Interrupted/API-unavailable scan | Pending or failed result; recovered newer run certifies current evidence |
| Publisher boundary | Ruleset app binding plus reviewed publisher workflow controls |

Local execution tests exercise duplicate delivery, delayed fork/Dependabot-shaped
payloads (including genuine recorded empty fork associations), interruption, API
failure, same-head retargeting, shared-head contexts,
ambiguous creation, supersession, and multi-member queue success/failure. These are
deterministic contracts, not claims that GitHub delivered authentic external events.
Some scenarios require operator orchestration beyond the case creator: create a
real fork, configure Dependabot, enable a merge queue, trigger ready/draft transitions,
and capture the actual run histories. Never synthesize a payload and label it a
genuine token-bearing Dependabot or queue qualification.

Attach exact candidate/final SHAs, reports, ruleset readback, run URLs, and any
unqualified scenarios to release evidence. Archive disposable repositories after
preserving reports and links; delete only under explicit maintainer direction.
