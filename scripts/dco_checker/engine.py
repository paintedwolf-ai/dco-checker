"""Certification state machine for direct, fallback, manual and queue events."""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from . import Draft, Obsolete, POLICY_VERSION, Refused
from .checks import Publisher
from .evidence import SHA, queue_members
from .policy import evaluate, render


@dataclass(frozen=True)
class Config:
    revision: str
    run_id: int
    attempt: int
    run_url: str
    ci_workflow: str = "ci.yml"

    def __post_init__(self):
        if not SHA.fullmatch(self.revision):
            raise Refused("DCO_CHECKER_REVISION must be the full immutable action SHA")
        if type(self.run_id) is not int or self.run_id <= 0 or type(self.attempt) is not int or self.attempt <= 0:
            raise Refused("DCO_RUN_ID and DCO_RUN_ATTEMPT must be positive integers")
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/\d+", self.run_url):
            raise Refused("DCO_RUN_URL must identify a GitHub.com Actions run")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.ya?ml", self.ci_workflow) or self.ci_workflow.startswith("."):
            raise Refused("CI workflow must be a workflow filename")


def trusted_run_head(github, event, config):
    captured = event["workflow_run"]
    if type(captured["id"]) is not int or captured["id"] <= 0:
        raise Refused("Workflow run must have a positive captured run ID")
    run = github.api(f"repos/{github.repository}/actions/runs/{captured['id']}")
    workflow = github.api(f"repos/{github.repository}/actions/workflows/{config.ci_workflow}")
    if (type(run["id"]) is not int or type(run["workflow_id"]) is not int or
        type(captured["workflow_id"]) is not int or type(workflow["id"]) is not int or
        run["workflow_id"] <= 0 or run["id"] != captured["id"] or run["repository"]["full_name"] != github.repository or
        run["workflow_id"] != workflow["id"] or run["event"] != "pull_request" or run["status"] != "completed" or
        run["head_sha"] != captured["head_sha"] or run["workflow_id"] != captured["workflow_id"] or
        not isinstance(run["head_sha"], str) or not SHA.fullmatch(run["head_sha"])):
        raise Refused("Workflow run is not captured repository CI for a PR")
    associations = run["pull_requests"]
    if not isinstance(associations, list) or associations != captured["pull_requests"]:
        raise Refused("Workflow run association metadata is malformed or changed")
    if associations:
        if len(associations) != 1:
            raise Refused("Workflow run PR association is ambiguous")
        association = associations[0]
        if type(association["number"]) is not int or association["number"] <= 0:
            raise Refused("Workflow run association has an invalid PR number")
        if association["head"]["sha"] != run["head_sha"]:
            raise Refused("Workflow run contradicts the associated PR head")
        current = github.pull(association["number"])
        if current["headRefOid"] != run["head_sha"] or current["state"] != "OPEN":
            raise Obsolete("CI completion belongs to an obsolete PR generation")
        if current["isDraft"]:
            raise Draft("Draft PR left untouched")
    # CI completion is only a trusted wake-up, never certification of DCO.
    # GitHub can omit PR associations for real fork/bot runs. Its immutable
    # run head plus the complete live repository PR inventory identifies every
    # current context that can consume this SHA's check without branch heuristics.
    return run["head_sha"]


def select(github, event_name, event, config):
    group = None
    if event_name == "merge_group":
        captured = event["merge_group"]
        base, sha = captured["base_sha"], captured["head_sha"]
        branch = captured["base_ref"]
        if not branch.startswith("refs/heads/") or not SHA.fullmatch(base) or not SHA.fullmatch(sha):
            raise Refused("Malformed merge group identity")
        group = (branch.removeprefix("refs/heads/"), base, sha)
        members = queue_members(github.queue(group[0]), base, sha)
        for member in members:
            current = github.pull(member["number"])
            if current["isDraft"]:
                raise Draft("Queued PR returned to draft; check left untouched")
            if current != member:
                raise Obsolete("Queued PR no longer matches captured queue generation")
    elif event_name == "workflow_run":
        sha = trusted_run_head(github, event, config)
        members = github.contexts(sha)
        if not members:
            raise Obsolete("CI head has no current open PR contexts")
    else:
        if event_name == "pull_request_target":
            captured = event["pull_request"]
            current = github.pull(captured["number"])
            if current["headRefOid"] != captured["head"]["sha"]:
                raise Obsolete("PR event belongs to an obsolete head")
        elif event_name == "workflow_dispatch":
            number = str(event["inputs"]["pull_request"])
            if not re.fullmatch(r"[1-9][0-9]*", number):
                raise Refused("Manual pull_request input must be a positive PR number")
            current = github.pull(int(number))
        else:
            raise Refused("Unsupported DCO event")
        if current["isDraft"]:
            raise Draft("Draft PR left untouched")
        if current["state"] != "OPEN":
            raise Obsolete("PR is no longer open")
        sha = current["headRefOid"]
        members = github.contexts(sha)
        if current not in members:
            raise Refused("Current PR is absent from the complete open PR inventory")
    for member in members:
        if member["isDraft"]:
            raise Draft("A PR sharing this certification target is draft; check left untouched")
        if member["state"] != "OPEN":
            raise Obsolete("Certification member is no longer open")
    return sha, sorted(members, key=lambda member: member["number"]), group


def revalidate(github, sha, members, group):
    for member in members:
        current = github.pull(member["number"])
        if current["isDraft"]:
            raise Draft("PR returned to draft; pending check left untouched")
        if current != member:
            raise Obsolete("PR generation changed during certification")
    if group:
        queued = queue_members(github.queue(group[0]), group[1], group[2])
        if sorted(queued, key=lambda member: member["number"]) != members:
            raise Obsolete("Merge group membership changed during certification")
    else:
        current_contexts = github.contexts(sha)
        if any(member["isDraft"] for member in current_contexts):
            raise Draft("A same-head PR is draft; pending check left untouched")
        if current_contexts != members:
            raise Obsolete("Same-head PR contexts changed during certification")


def make_evidence(repository, sha, members, group, revision):
    evidence = {"repository": repository, "sha": sha, "members": members, "group": group,
                "revision": revision, "policy": POLICY_VERSION}
    evidence["digest"] = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return evidence


def run(github, event_name, event, config):
    publisher, results, evidence = None, [], None
    try:
        if config.run_url != f"https://github.com/{github.repository}/actions/runs/{config.run_id}":
            raise Refused("Run URL must match the publishing repository and run ID")
        sha, members, group = select(github, event_name, event, config)
        revalidate(github, sha, members, group)
        evidence = make_evidence(github.repository, sha, members, group, config.revision)
        publisher = Publisher(github, sha, evidence, config)
        publisher.start()
        if publisher.check.get("status") == "completed":
            # Duplicate delivery of this execution can reuse unchanged complete
            # evidence. Manual retries use a new run/attempt and create pending.
            print("Reused completed certification for identical immutable evidence")
            print(publisher.check.get("output", {}).get("summary", ""))
            return 0 if publisher.check.get("conclusion") == "success" else 1
        # Reserve a minute of the total HTTP budget for terminal publication.
        transport = getattr(github, "transport", None)
        deadline = getattr(transport, "deadline", None)
        if deadline is not None:
            transport.deadline = deadline - 60
        try:
            for member in members:
                results += [evaluate(commit, member["number"]) for commit in github.commits(member)]
            revalidate(github, sha, members, group)
        finally:
            if deadline is not None:
                transport.deadline = deadline
        conclusion = "failure" if any(result.outcome == "failed" for result in results) else "success"
        for result in results:
            print("DCO evaluation: " + json.dumps(asdict(result), sort_keys=True))
        summary = render(github.repository, evidence, results)
        publisher.finish(conclusion, summary)
        print(summary)
        return 0 if conclusion == "success" else 1
    except Draft as error:
        print(str(error))
        return 0 if publisher is None else 1
    except Obsolete as error:
        # A changed PR generation should fail its own pending check, but a newer
        # publisher has priority and prevents writing through reconcile().
        if publisher is None:
            print("Obsolete execution: " + str(error))
            return 0
        return fail(github, publisher, evidence, results, error)
    except (Refused, KeyError, TypeError, ValueError, AttributeError) as error:
        return fail(github, publisher, evidence, results, error)


def fail(github, publisher, evidence, results, error):
    message = str(error) if isinstance(error, Refused) else "Malformed or incomplete GitHub evidence: " + type(error).__name__
    print("DCO certification unavailable: " + message)
    if publisher is None or publisher.check is None:
        return 1
    try:
        # Publication after observed draft is forbidden, including failure writes.
        for member in evidence["members"]:
            if github.pull(member["number"])["isDraft"]:
                print("Draft observed; pending check left untouched")
                return 1
        publisher.finish("failure", render(github.repository, evidence, results, error=message))
    except (Refused, KeyError, TypeError, ValueError, AttributeError) as publication_error:
        print("Terminal publication unavailable: " + str(publication_error))
    return 1
