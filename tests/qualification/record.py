#!/usr/bin/env python3
"""Collect independently verifiable evidence from an actual consumer action run.

Uses the operator's gh login, never the action's runtime credentials. Read only.
"""
import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess


def api(path):
    completed = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                               check=True, timeout=60)
    return json.loads(completed.stdout)


def verify(run, jobs, checks, *, repository, run_id, head, conclusion, app_id, action_sha=None):
    errors = []
    if run.get("id") != run_id or run.get("repository", {}).get("full_name") != repository:
        errors.append("workflow run identity does not match requested consumer")
    if run.get("status") != "completed":
        errors.append("workflow run is not complete")
    if not any(any("Certify" in step.get("name", "") for step in job.get("steps", []))
               for job in jobs):
        errors.append("no composite certification step appears in recorded jobs")
    run_url = run.get("html_url")
    candidates = [check for check in checks if check.get("name") == "DCO audit"
                  and check.get("head_sha") == head
                  and str(check.get("external_id", "")).startswith(f"dco:v2:{run_id}:{run.get('run_attempt', 1)}:")]
    if not candidates:
        errors.append("no DCO audit check belongs to this exact run and target head")
    for check in candidates:
        if check.get("status") != "completed" or check.get("conclusion") != conclusion:
            errors.append("published check has unexpected terminal outcome")
        if check.get("app", {}).get("id") != app_id:
            errors.append("published check has unexpected GitHub App identity")
        if not check.get("external_id"):
            errors.append("published check lacks certification evidence identity")
        output = check.get("output", {})
        if not output.get("summary"):
            errors.append("published check lacks an audit summary")
        elif action_sha is not None and f"checker: `{action_sha}`" not in output["summary"]:
            errors.append("published evidence does not identify the requested action revision")
    return errors


def verify_gate(statuses, checks, run, expected_state):
    identity = f"dco:v2:{run['id']}:{run.get('run_attempt', 1)}:"
    audits = [check for check in checks if check.get('name') == 'DCO audit'
              and str(check.get('external_id', '')).startswith(identity)]
    owned = [status for status in statuses if status.get('context') == 'DCO-owned'
             and str(status.get('target_url', '')).startswith(run['html_url'] + '#' + identity)]
    errors = []
    terminal = [status for status in owned if status.get('state') == expected_state]
    if not terminal:
        errors.append('no required DCO-owned terminal status belongs to this exact execution')
    for status in terminal:
        creator = status.get('creator') or {}
        if creator.get('id') != 41898282 or creator.get('login') != 'github-actions[bot]' or creator.get('type') != 'Bot':
            errors.append('required status was not published by GitHub Actions')
        if not any(status.get('target_url') == run['html_url'] + '#' + check['external_id'] for check in audits):
            errors.append('required status and audit do not identify the same immutable evidence')
    return errors


def logged_json(logs, marker):
    records = []
    for line in logs.splitlines():
        if marker not in line:
            continue
        value = line.split(marker, 1)[1].strip()
        # The runner also prints the step's source. Only emitted JSON is data.
        if not value.startswith('{'):
            continue
        try:
            records.append(json.loads(value))
        except ValueError:
            continue
    return records


def verify_evidence(logs, checks, run, *, repository, head, action_sha, caller_revision):
    records = logged_json(logs, 'DCO evidence: ')
    events = logged_json(logs, 'DCO_QUALIFICATION_EVENT=')
    queues = logged_json(logs, 'DCO_QUALIFICATION_QUEUE=')
    errors = []
    evidence = records[0] if records else None
    if not isinstance(evidence, dict):
        errors.append('runner logs lack canonical immutable DCO evidence')
    else:
        unsigned = dict(evidence)
        digest = unsigned.pop('digest', None)
        calculated = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        expected = {'repository': repository, 'sha': head, 'revision': action_sha,
                    'caller_revision': caller_revision, 'policy': '2'}
        if digest != calculated or any(evidence.get(k) != v for k, v in expected.items()):
            errors.append('canonical evidence digest or repository/head/source identity differs')
        identity = f"dco:v2:{run['id']}:{run.get('run_attempt', 1)}:{calculated}"
        if not any(c.get('name') == 'DCO audit' and c.get('external_id') == identity for c in checks):
            errors.append('canonical evidence does not reproduce the published audit identity')
        if any(record != evidence for record in records):
            errors.append('runner emitted conflicting immutable evidence records')
        group = evidence.get('group')
        if group:
            if not events or not queues:
                errors.append('group qualification requires actual event and complete queue captures')
                return errors, {'canonical_evidence': evidence, 'captured_events': events, 'captured_queues': queues}
            try:
                captured = events[-1]['merge_group']
                if (captured['head_sha'] != group['head'] or captured['base_sha'] != group['event_base']
                        or captured['base_ref'] != 'refs/heads/' + group['branch'] or group['head'] != head):
                    errors.append('canonical group differs from the actual captured event')
                captured_repository = queues[-1]['data']['repository']
                if captured_repository['baseRef']['target']['oid'] != group['root']:
                    errors.append('canonical protected root differs from captured queue authority')
                connection = captured_repository['mergeQueue']['entries']
                if (connection['pageInfo']['hasNextPage'] is not False or
                        connection['totalCount'] != len(connection['nodes'])):
                    errors.append('captured qualification queue inventory is incomplete')
                by_head = {}
                for entry in connection['nodes']:
                    if entry['headCommit'] is None:
                        continue
                    oid = entry['headCommit']['oid']
                    if oid in by_head:
                        raise ValueError('duplicate queue head')
                    by_head[oid] = entry
                members, visited, cursor = [], set(), group['head']
                while cursor != group['root']:
                    if cursor in visited or cursor not in by_head:
                        raise ValueError('missing or cyclic cumulative prefix')
                    visited.add(cursor)
                    entry = by_head[cursor]
                    snapshot = {key:entry['pullRequest'][key] for key in
                                ('number','headRefOid','baseRefOid','isDraft','state')}
                    if snapshot['state'] != 'OPEN' or snapshot['isDraft'] is not False:
                        raise ValueError('inactive original member')
                    members.append(snapshot)
                    cursor = entry['baseCommit']['oid']
                if group['event_base'] not in visited | {group['root']}:
                    raise ValueError('event checkpoint absent from captured ancestry')
                # Certification canonicalizes member order by PR number, while
                # the independently captured queue records ancestry order.
                canonical_members = evidence.get('members')
                if not isinstance(canonical_members, list) or sorted(members, key=lambda m:m['number']) != canonical_members:
                    errors.append('canonical original members differ from complete captured cumulative prefix')
            except (KeyError, TypeError, ValueError):
                errors.append('captured qualification queue authority is malformed')
    return errors, {'canonical_evidence': evidence, 'captured_events': events, 'captured_queues': queues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--expected-conclusion", choices=["success", "failure", "cancelled"], required=True)
    parser.add_argument("--app-id", type=int, default=15368)
    parser.add_argument("--expected-state", choices=["success", "failure", "error"])
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--action-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-legacy-missing-run-link", action="store_true", help="Candidate-only evidence for the pre-link implementation; never use for release qualification")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("repository must be owner/name")
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (args.head, args.action_sha)):
        parser.error("head and action-sha must be full immutable SHAs")
    prefix = f"repos/{args.repository}"
    run = api(f"{prefix}/actions/runs/{args.run_id}")
    jobs = []
    checks = []
    for path, key, target in [(f"actions/runs/{args.run_id}/jobs", "jobs", jobs),
                              (f"commits/{args.head}/check-runs", "check_runs", checks)]:
        page = 1
        while True:
            query = f"per_page=100&page={page}" + ("&filter=all" if key == "check_runs" else "")
            batch = api(f"{prefix}/{path}?{query}")[key]
            target.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    errors = verify(run, jobs, checks, repository=args.repository, run_id=args.run_id,
                    head=args.head, conclusion=args.expected_conclusion, app_id=args.app_id, action_sha=args.action_sha)
    executed_jobs = [job for job in jobs if any("Certify" in step.get("name", "") for step in job.get("steps", []))]
    logs = "\n".join(subprocess.run(["gh", "run", "view", "--job", str(job["id"]), "--repo", args.repository, "--log"],
                       capture_output=True, text=True, check=True, timeout=60).stdout for job in executed_jobs)
    if f"Download action repository 'paintedwolf-ai/dco-checker@{args.action_sha}' (SHA:{args.action_sha})" not in logs:
        errors.append("runner logs do not attest downloading the requested immutable action SHA")
    identified = [check for check in checks if str(check.get("external_id", "")).startswith(f"dco:v2:{args.run_id}:{run.get('run_attempt', 1)}:")]
    statuses = []
    page = 1
    while True:
        batch = api(f"{prefix}/commits/{args.head}/statuses?per_page=100&page={page}")
        statuses.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    expected_state = args.expected_state or ('success' if args.expected_conclusion == 'success' else 'failure')
    errors += verify_gate(statuses, checks, run, expected_state)
    caller_revision = None
    for check in identified:
        try:
            raw = check["output"]["text"]
            parsed = json.loads(raw[8:-4])
            candidate = parsed.get("caller_revision")
            if re.fullmatch(r"[0-9a-f]{40}", candidate or ""):
                if caller_revision is not None and caller_revision != candidate:
                    errors.append("execution checks disagree about immutable caller revision")
                caller_revision = candidate
        except (KeyError, ValueError, TypeError):
            pass
    if caller_revision is None:
        errors.append("published provenance lacks immutable trusted caller revision")
        caller_revision = run["head_sha"]
    workflow = api(f"{prefix}/contents/.github/workflows/dco.yml?ref={caller_revision}")
    source = base64.b64decode(workflow["content"]).decode("utf-8")
    if not args.allow_legacy_missing_run_link and any(run["html_url"] not in check.get("output", {}).get("summary", "") for check in identified):
        errors.append("published summary lacks the explicit certification workflow run link")
    if not args.allow_legacy_missing_run_link:
        for check in identified:
            try:
                text = check["output"]["text"]
                if not text.startswith("```json\n") or not text.endswith("\n```"):
                    raise ValueError("not fenced JSON")
                provenance = json.loads(text[8:-4])
                expected = {"run_url": run["html_url"], "run_id": args.run_id,
                            "attempt": run.get("run_attempt", 1), "external_id": check["external_id"],
                            "checker_revision": args.action_sha, "policy_version": "2", "caller_revision": caller_revision,
                            "evidence_digest": check["external_id"].rsplit(":", 1)[-1]}
                if any(str(provenance.get(key)) != str(value) for key, value in expected.items()):
                    errors.append("published execution provenance differs from the recorded action/run/evidence")
            except (KeyError, TypeError, ValueError):
                errors.append("published check lacks valid structured execution provenance")
    if f"paintedwolf-ai/dco-checker@{args.action_sha}" not in source:
        errors.append("immutable caller workflow does not pin the requested action revision")
    evidence_errors, retained_evidence = verify_evidence(logs, checks, run, repository=args.repository,
        head=args.head, action_sha=args.action_sha, caller_revision=caller_revision)
    errors += evidence_errors
    document = {"schema_version": 1, "qualification_kind": "hosted-token-bearing",
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "scenario": args.scenario, "action_sha": args.action_sha,
                "target_head": args.head, "expected_conclusion": args.expected_conclusion,
                "release_eligible": not args.allow_legacy_missing_run_link and not errors,
                "legacy_missing_run_link_allowed": args.allow_legacy_missing_run_link,
                "expected_state": expected_state, "statuses": statuses,
                **retained_evidence,
                "runner_logs": logs, "run": run, "jobs": jobs, "checks": checks, "caller_workflow": {"ref": caller_revision, "blob_sha": workflow["sha"], "source": source}, "errors": errors,
                "limitations": ["this record does not demonstrate required-context ruleset enforcement",
                                "historical execution evidence is not a claim about the latest merge decision"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n")
    print("; ".join(errors) if errors else f"Qualified {args.scenario}: {run['html_url']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
