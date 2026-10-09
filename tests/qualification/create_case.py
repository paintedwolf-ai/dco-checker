#!/usr/bin/env python3
"""Create a signed/unsigned PR in an explicitly named disposable consumer.

Mutates only the named qualification repository. Installs the real pinned action
and publishes original commits via GitHub's Git database API. Never run on a
production repository. The operator provisions the repository separately.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess


def api(path, payload=None, method=None):
    args = ["gh", "api", path]
    if method:
        args += ["--method", method]
    if payload is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--action-sha", required=True)
    parser.add_argument("--scenario", choices=["signed", "unsigned", "unsigned-after-250", "draft"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-install", action="store_true", help="Use existing reviewed default-branch callers installed via Git SSH")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/(?:dco-qualification-[A-Za-z0-9_.-]+|dco-checker-qualification)", args.repository):
        parser.error("repository must be an explicitly named disposable DCO qualification repository")
    if not re.fullmatch(r"[0-9a-f]{40}", args.action_sha):
        parser.error("action-sha must be a full immutable SHA")
    prefix = f"repos/{args.repository}"
    repository = api(prefix)
    branch = repository["default_branch"]
    current = api(f"{prefix}/git/ref/heads/{branch}")["object"]["sha"]
    parent = api(f"{prefix}/git/commits/{current}")
    workflow = Path(__file__).with_name("consumer.template.yml").read_text().replace("ACTION_SHA", args.action_sha)
    # Install source atomically in one signed base commit. No untrusted checkout.
    ci = "name: CI\non: [pull_request, merge_group]\npermissions: {}\njobs:\n  probe:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: 'true'\n"
    login = api("user")["login"]
    identity = {"name": login, "email": f"{login}@users.noreply.github.com"}
    signoff = f"\n\nSigned-off-by: {identity['name']} <{identity['email']}>"
    if args.skip_install:
        tree = {"sha": parent["tree"]["sha"]}
        configured = {"sha": current}
    else:
        tree = api(f"{prefix}/git/trees", {"base_tree": parent["tree"]["sha"], "tree": [
            {"path": ".github/workflows/dco.yml", "mode": "100644", "type": "blob", "content": workflow},
            {"path": ".github/workflows/ci.yml", "mode": "100644", "type": "blob", "content": ci}]}, "POST")
        configured = api(f"{prefix}/git/commits", {"message": "Install qualification caller" + signoff,
                         "tree": tree["sha"], "parents": [current], "author": identity, "committer": identity}, "POST")
        api(f"{prefix}/git/refs/heads/{branch}", {"sha": configured["sha"], "force": False}, "PATCH")
    count = 251 if args.scenario == "unsigned-after-250" else 1
    head = configured["sha"]
    changed_tree = api(f"{prefix}/git/trees", {"base_tree": tree["sha"], "tree": [{"path": f"qualification/{args.scenario}-{current[:12]}.txt", "mode": "100644", "type": "blob", "content": args.scenario + "\n"}]}, "POST")
    for number in range(1, count + 1):
        unsigned = args.scenario in {"unsigned", "unsigned-after-250"} and number == count
        commit = api(f"{prefix}/git/commits", {"message": f"Qualification {args.scenario} {number}" + ("" if unsigned else signoff),
                     "tree": changed_tree["sha"] if number == count else tree["sha"], "parents": [head], "author": identity, "committer": identity}, "POST")
        head = commit["sha"]
    ref = f"qualification/{args.scenario}-{head[:12]}"
    api(f"{prefix}/git/refs", {"ref": f"refs/heads/{ref}", "sha": head}, "POST")
    pr = api(f"{prefix}/pulls", {"title": f"Qualify {args.scenario}", "head": ref, "base": branch,
             "body": "Disposable hosted qualification of the pinned composite action.", "draft": args.scenario == "draft"}, "POST")
    evidence = {"schema_version": 1, "repository": args.repository, "action_sha": args.action_sha,
                "scenario": args.scenario, "pull_request": pr["number"], "url": pr["html_url"],
                "base_sha": configured["sha"], "head_sha": head, "commits": count,
                "expected_conclusion": "failure" if args.scenario in {"unsigned", "unsigned-after-250"} else "success",
                "draft_expects_no_check": args.scenario == "draft"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(pr["html_url"])


if __name__ == "__main__":
    main()
