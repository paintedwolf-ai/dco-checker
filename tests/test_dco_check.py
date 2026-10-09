import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import dco_check as dco


def commit(oid="head", message="Signed-off-by: Author <author@example.org>", parents=1):
    return {"oid": oid, "githubAuthor": {"type": "User"}, "message": message, "author": {"name": "Author", "email": "author@example.org"},
            "committer": {"name": "Committer", "email": "committer@example.org"}, "parents": {"totalCount": parents}}


def pull(number=1, head="head", draft=False):
    return {"number": number, "headRefOid": head, "baseRefOid": "base", "isDraft": draft, "state": "OPEN"}


def comparison(commits, total, base="base"):
    return {"base_commit": {"sha": base}, "total_commits": total,
            "commits": [{"sha": c["oid"], "commit": {"message": c["message"], "author": c["author"], "committer": c["committer"]},
                         "author": c["githubAuthor"], "parents": [{}] * c["parents"]["totalCount"]} for c in commits]}


def entry(number, base, head):
    return {"id": str(number), "baseCommit": {"oid": base}, "headCommit": {"oid": head},
            "pullRequest": pull(number, "original" + str(number))}


class FakeGitHub:
    repository = "org/repo"

    def __init__(self, commits=None):
        self.original = pull()
        self.original_commits = commits or [commit()]
        self.writes = []
        self.bot = False

    def pull(self, number):
        return copy.deepcopy(self.original)

    def commits(self, number):
        return {key: self.original[key] for key in ("headRefOid", "baseRefOid", "isDraft", "state")}, self.original_commits

    def api(self, path, payload=None, method=None):
        if payload is None:
            return {"sha": self.original_commits[0]["oid"], "author": {"type": "Bot" if self.bot else "User"}}
        self.writes.append((path, payload, method))
        return {"id": 10}


class DCOExecutionTests(unittest.TestCase):
    def test_identity_matching_merges_bots_and_missing_signoffs(self):
        self.assertTrue(dco.signoff_valid(commit()))
        self.assertTrue(dco.signoff_valid(commit(message="SIGNED-OFF-BY: committer <COMMITTER@example.org>")))
        self.assertFalse(dco.signoff_valid(commit(message="Signed-off-by: Other <other@example.org>")))
        self.assertFalse(dco.signoff_valid(commit(message="Signed-off-by: Author <author@example>")))
        self.assertFalse(dco.signoff_valid(commit(message="Signed-off-by: Author <committer@example.org>")))
        self.assertFalse(dco.signoff_valid(commit(message="missing")))
        self.assertTrue(dco.signoff_valid(commit(message="missing", parents=2)))
        github = FakeGitHub([commit(message="missing")])
        self.assertEqual(dco.certify_pull(github, pull()), ["head"])
        github.original_commits[0]["githubAuthor"] = {"type": "Bot"}
        self.assertEqual(dco.certify_pull(github, pull()), [])

    def test_full_inventory_over_250_commits(self):
        github = dco.GitHub("org/repo")
        commits = [commit(str(i)) for i in range(276)] + [commit()]
        pages = [comparison(commits[:100], 277), comparison(commits[100:200], 277), comparison(commits[200:], 277)]
        with patch.object(github, "pull", return_value=pull()), patch.object(github, "api", side_effect=pages) as api:
            identity, result = github.commits(1)
        self.assertEqual(len(result), 277)
        self.assertEqual(identity["headRefOid"], "head")
        self.assertEqual([call.args[0].split("page=")[-1] for call in api.call_args_list], ["1", "2", "3"])

    def test_partial_duplicate_and_changed_pages_fail_closed(self):
        first = [commit(str(i)) for i in range(100)]
        cases = [
            [comparison([commit()], 2)],
            [comparison(first, 101), comparison([first[0]], 101)],
            [comparison(first, 101), comparison([commit()], 102)],
            [comparison([commit()], 1, base="wrong")],
            [comparison([commit("wronghead")], 1)],
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                github = dco.GitHub("org/repo")
                with patch.object(github, "pull", return_value=pull()), patch.object(github, "api", side_effect=pages), self.assertRaises(dco.Refused):
                    github.commits(1)
        for changed in [pull(head="new"), pull(draft=True), {**pull(), "baseRefOid": "newbase"}]:
            github = dco.GitHub("org/repo")
            with patch.object(github, "pull", side_effect=[pull(), changed]), patch.object(github, "api", return_value=comparison([commit()], 1)), self.assertRaises(dco.Refused):
                github.commits(1)

    def test_api_errors_reject_partial_graphql_and_transport_failure(self):
        github = dco.GitHub("org/repo")
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps({"data": {}, "errors": [{"message": "partial"}]}))), self.assertRaises(dco.Refused):
            github.query("name")
        with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gh")), self.assertRaises(subprocess.CalledProcessError):
            github.pull(1)

    def test_queue_uses_structured_ancestry_instead_of_synthetic_signoff(self):
        entries = [entry(1, "base", "queue1"), entry(2, "queue1", "queue2")]
        self.assertEqual([p["number"] for p in dco.queue_members(entries, "base", "queue2")], [1, 2])
        for invalid in [entries[:1], [entry(1, "missing", "queue2")], [entry(1, "queue2", "queue2")], entries + [entry(3, "base", "queue2")]]:
            with self.assertRaises(dco.Refused):
                dco.queue_members(invalid, "base", "queue2")

    def test_queue_inventory_paginates_and_rejects_truncation(self):
        github = dco.GitHub("org/repo")
        def connection(nodes, cursor, more, total=2):
            return {"mergeQueue": {"entries": {"nodes": nodes, "totalCount": total, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}}}
        a, b = entry(1, "base", "q1"), entry(2, "q1", "q2")
        with patch.object(github, "query", side_effect=[connection([a], "a", True), connection([b], None, False)]):
            self.assertEqual(github.queue("main"), [a, b])
        with patch.object(github, "query", return_value=connection([a], None, False)), self.assertRaises(dco.Refused):
            github.queue("main")
        with patch.object(github, "query", side_effect=[connection([a], "a", True), connection([a], "b", True)]), self.assertRaises(dco.Refused):
            github.queue("main")

    def test_pr_check_publishes_on_original_head_and_failure_does_not_pass(self):
        event = {"pull_request": {"number": 1, "head": {"sha": "head"}, "base": {"sha": "base"}, "draft": False}}
        github = FakeGitHub()
        self.assertEqual(dco.run(github, "pull_request_target", event), 0)
        self.assertEqual(github.writes[0][1]["head_sha"], "head")
        self.assertEqual(github.writes[-1][1]["conclusion"], "success")
        github = FakeGitHub([commit(message="missing")])
        self.assertEqual(dco.run(github, "pull_request_target", event), 1)
        self.assertEqual(github.writes[-1][1]["conclusion"], "failure")

    def test_live_draft_before_creation_remains_untouched(self):
        github = FakeGitHub()
        github.original["isDraft"] = True
        self.assertEqual(dco.run(github, "pull_request_target", {"pull_request": {"number": 1, "head": {"sha": "head"}, "base": {"sha": "base"}}}), 0)
        self.assertEqual(github.writes, [])

    def test_race_during_certification_cannot_publish_success(self):
        github = FakeGitHub()
        with patch.object(github, "pull", side_effect=[pull(), pull(), pull(head="new"), pull(head="new"), pull(head="new")]):
            self.assertEqual(dco.run(github, "workflow_dispatch", {"inputs": {"pull_request": "1"}}), 1)
        self.assertEqual(github.writes, [])


    def test_return_to_draft_publishes_no_check(self):
        github = FakeGitHub()
        with patch.object(github, "pull", side_effect=[pull(), pull(), pull(draft=True), pull(draft=True)]):
            self.assertEqual(dco.run(github, "workflow_dispatch", {"inputs": {"pull_request": "1"}}), 1)
        self.assertEqual(github.writes, [])

    def test_merge_group_checks_original_commits_and_detects_membership_race(self):
        github = FakeGitHub([commit(message="missing")])
        event = {"merge_group": {"base_ref": "refs/heads/main", "base_sha": "base", "head_sha": "queue"}}
        member = entry(1, "base", "queue")
        member["pullRequest"] = pull()
        with patch.object(github, "queue", create=True, return_value=[member]):
            self.assertEqual(dco.run(github, "merge_group", event), 1)
        self.assertEqual(github.writes[0][1]["head_sha"], "queue")
        self.assertEqual(github.writes[-1][1]["conclusion"], "failure")
        github = FakeGitHub()
        with patch.object(github, "queue", create=True, side_effect=[[member], []]):
            self.assertEqual(dco.run(github, "merge_group", event), 1)
        self.assertEqual(github.writes[-1][1]["conclusion"], "failure")


    def test_stale_event_base_cannot_certify_same_head(self):
        github = FakeGitHub()
        event = {"pull_request": {"number": 1, "head": {"sha": "head"}, "base": {"sha": "oldbase"}}}
        with self.assertRaises(dco.Refused):
            dco.run(github, "pull_request_target", event)
        self.assertEqual(github.writes, [])


    def test_workflow_run_requires_exact_ci_pr_association(self):
        github = FakeGitHub()
        association = {"number": 1, "head": {"sha": "head"}, "base": {"sha": "base"}}
        run = {"id": 99, "repository": {"full_name": "org/repo"}, "workflow_id": 7,
               "event": "pull_request", "status": "completed", "head_sha": "head", "pull_requests": [association]}
        event = {"workflow_run": run}
        with patch.object(github, "api", side_effect=[run, {"id": 7}]):
            self.assertEqual(dco.target("workflow_run", event, github), ("head", [pull()], None))
        for changed in [{**run, "pull_requests": []}, {**run, "pull_requests": [association, association]},
                        {**run, "head_sha": "new"}, {**run, "workflow_id": 8},
                        {**run, "event": "merge_group"}, {**run, "repository": {"full_name": "foreign/repo"}}]:
            with patch.object(github, "api", side_effect=[changed, {"id": 7}]), self.assertRaises(dco.Refused):
                dco.target("workflow_run", event, github)
        for changed in [pull(head="new"), {**pull(), "baseRefOid": "newbase"}]:
            with patch.object(github, "api", side_effect=[run, {"id": 7}]), patch.object(github, "pull", return_value=changed), self.assertRaises(dco.Refused):
                dco.target("workflow_run", event, github)
        with patch.object(github, "api", side_effect=[run, {"id": 7}]), patch.object(github, "pull", return_value=pull(draft=True)):
            self.assertIsNone(dco.target("workflow_run", event, github))
        self.assertEqual(github.writes, [])

    def test_shared_action_runs_its_pinned_source_without_caller_checkout(self):
        root = Path(__file__).parents[1]
        workflow = (root / "examples/dco.yml").read_text()
        action = (root / "action.yml").read_text()
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("ready_for_review, edited", workflow)
        self.assertIn("workflows: [CI]", workflow)
        self.assertIn("workflow_run.event == 'pull_request'", workflow)
        self.assertIn("merge_group:", workflow)
        self.assertIn("paintedwolf-ai/dco-checker@REPLACE_WITH_REVIEWED_COMMIT_SHA", workflow)
        self.assertNotIn("actions/checkout", workflow)
        self.assertNotIn("download-artifact", workflow)
        self.assertIn('python3 "$DCO_ACTION_PATH/scripts/dco_check.py"', action)
        self.assertNotIn("github.event.pull_request.head", action)

    def test_workflow_run_configures_ci_filename_and_rejects_other_paths(self):
        github = FakeGitHub()
        association = {"number": 1, "head": {"sha": "head"}, "base": {"sha": "base"}}
        run = {"id": 99, "repository": {"full_name": "org/repo"}, "workflow_id": 7,
               "event": "pull_request", "status": "completed", "head_sha": "head", "pull_requests": [association]}
        with patch.dict(dco.os.environ, {"DCO_CI_WORKFLOW": "verify.yaml"}), patch.object(github, "api", side_effect=[run, {"id": 7}]) as api:
            self.assertEqual(dco.target("workflow_run", {"workflow_run": run}, github), ("head", [pull()], None))
            self.assertEqual(api.call_args_list[1].args[0], "repos/org/repo/actions/workflows/verify.yaml")
        for invalid in ["../ci.yml", "https://example.org/ci.yml", "ci.yml?ref=other", "ci.yml#other"]:
            with patch.dict(dco.os.environ, {"DCO_CI_WORKFLOW": invalid}), patch.object(github, "api", return_value=run), self.assertRaises(dco.Refused):
                dco.target("workflow_run", {"workflow_run": run}, github)
        self.assertEqual(github.writes, [])
