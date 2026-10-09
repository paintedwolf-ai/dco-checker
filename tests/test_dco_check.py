"""Independent execution-level certification contracts; no contribution code runs."""
import copy
import io
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from dco_checker import Refused
from dco_checker.engine import Config, run
from dco_checker.evidence import GitHub
from dco_checker.transport import APIError


def sha(number):
    return f'{number:040x}'


def pull(number=1, head=None, base=None, draft=False):
    return dict(number=number, headRefOid=head or sha(number), baseRefOid=base or sha(1000), isDraft=draft, state='OPEN')


def commit(oid, signed=True):
    identity = dict(name='Author', email='author@example.org')
    return dict(oid=oid, message='Change\n\nSigned-off-by: Author <author@example.org>' if signed else 'Change',
                author=identity, committer=identity, parents=dict(totalCount=1), githubAuthor=dict(type='User'))


class Consumer:
    repository = 'org/repo'
    def __init__(self, members=None):
        self.members = members or [pull()]
        self.inventory = {p['number']: [commit(p['headRefOid'])] for p in self.members}
        self.checks = []
        self.writes = []
        self.entries = []
        self.ambiguous = False
        self.ci = None
    def pull(self, number):
        return copy.deepcopy(next(p for p in self.members if p['number'] == number))
    def contexts(self, head):
        return copy.deepcopy([p for p in self.members if p['headRefOid'] == head])
    def commits(self, expected):
        return copy.deepcopy(self.inventory[expected['number']])
    def queue(self, branch):
        return copy.deepcopy(self.entries)
    def api(self, path, payload=None, method=None):
        if '/actions/runs/' in path:
            return copy.deepcopy(self.ci)
        if '/actions/workflows/' in path:
            return {'id': 7}
        if payload is None:
            return {'total_count': len(self.checks), 'check_runs': copy.deepcopy(self.checks)}
        self.writes.append((method, copy.deepcopy(payload)))
        if method == 'POST':
            check = dict(payload, id=len(self.checks) + 1, app={"id": 15368})
            self.checks.append(check)
            if self.ambiguous:
                self.ambiguous = False
                raise APIError('response lost after server committed POST', ambiguous=True)
        else:
            check = self.checks[int(path.rsplit('/', 1)[-1]) - 1]
            check.update(payload)
        return copy.deepcopy(check)


class ExecutionContracts(unittest.TestCase):
    def execute(self, github, event='workflow_dispatch', payload=None, run_id=10):
        config = Config(sha(900), run_id, 1, f'https://github.com/org/repo/actions/runs/{run_id}')
        with redirect_stdout(io.StringIO()):
            return run(github, event, payload or {'inputs': {'pull_request': '1'}}, config)

    def test_duplicate_delivery_converges_on_identified_check(self):
        github = Consumer()
        self.assertEqual(self.execute(github), 0)
        self.assertEqual(self.execute(github), 0)
        self.assertEqual(len(github.checks), 1)
        self.assertEqual(github.checks[0]['conclusion'], 'success')
        self.assertEqual([method for method, _ in github.writes].count('POST'), 1)

    def test_ambiguous_post_reconciles_without_duplicate(self):
        github = Consumer(); github.ambiguous = True
        self.assertEqual(self.execute(github), 0)
        self.assertEqual(len(github.checks), 1)
        self.assertEqual(github.checks[0]['status'], 'completed')

    def test_same_head_new_base_gets_new_evidence_and_pending(self):
        github = Consumer()
        self.execute(github)
        digest = github.checks[0]['external_id'].rsplit(':', 1)[-1]
        github.members[0]['baseRefOid'] = sha(1001)
        self.assertEqual(self.execute(github, run_id=11), 0)
        self.assertNotEqual(digest, github.checks[-1]['external_id'].rsplit(':', 1)[-1])
        self.assertEqual(github.writes[-2][1]['status'], 'in_progress')

    def test_failed_inventory_invalidates_current_attempt(self):
        github = Consumer(); self.execute(github)
        with patch.object(github, 'commits', side_effect=Refused('incomplete comparison')):
            self.assertEqual(self.execute(github, run_id=11), 1)
        self.assertEqual(github.checks[-1]['conclusion'], 'failure')
        self.assertIn('Evidence unavailable', github.checks[-1]['output']['summary'])

    def test_newer_execution_prevents_older_overwrite(self):
        github = Consumer(); self.execute(github, run_id=20)
        before = copy.deepcopy(github.writes)
        self.assertEqual(self.execute(github, run_id=10), 1)
        self.assertEqual(github.writes, before)

    def test_interrupted_scan_remains_pending_and_new_attempt_recovers(self):
        github = Consumer()
        with patch.object(github, 'commits', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.execute(github)
        self.assertEqual(github.checks[0]['status'], 'in_progress')
        self.assertEqual(self.execute(github, run_id=11), 0)
        self.assertEqual(github.checks[-1]['conclusion'], 'success')

    def test_shared_head_all_contexts_certified_and_draft_blocks_writes(self):
        github = Consumer([pull(), pull(2, head=sha(1), base=sha(1001))])
        github.inventory[2] = [commit(sha(1), signed=False)]
        self.assertEqual(self.execute(github), 1)
        self.assertIn('PR #2', github.checks[-1]['output']['summary'])
        github.members[1]['isDraft'] = True
        before = copy.deepcopy(github.writes)
        self.assertEqual(self.execute(github, run_id=11), 0)
        self.assertEqual(github.writes, before)

    def test_multi_member_queue_evaluates_originals_and_group_head(self):
        github = Consumer([pull(), pull(2)])
        github.entries = [dict(id='one', baseCommit={'oid': sha(1000)}, headCommit={'oid': sha(2001)}, pullRequest=pull()),
                          dict(id='two', baseCommit={'oid': sha(2001)}, headCommit={'oid': sha(2002)}, pullRequest=pull(2))]
        payload = {'merge_group': {'base_ref': 'refs/heads/main', 'base_sha': sha(1000), 'head_sha': sha(2002)}}
        self.assertEqual(self.execute(github, 'merge_group', payload), 0)
        self.assertEqual(github.checks[-1]['head_sha'], sha(2002))
        github.inventory[2] = [commit(sha(2), signed=False)]
        self.assertEqual(self.execute(github, 'merge_group', payload, run_id=11), 1)
        self.assertIn('PR #2', github.checks[-1]['output']['summary'])

    def test_fork_and_dependabot_ci_associations_are_authoritative(self):
        for fork in (False, True):
            github = Consumer()
            github.ci = {'id': 99, 'repository': {'full_name': 'org/repo'}, 'workflow_id': 7, 'event': 'pull_request',
                         'status': 'completed', 'head_sha': sha(1), 'actor': {'login': 'dependabot[bot]'},
                         'head_repository': {'full_name': 'other/repo' if fork else 'org/repo'},
                         'pull_requests': [{'number': 1, 'head': {'sha': sha(1)}, 'base': {'sha': sha(1000)}}]}
            self.assertEqual(self.execute(github, 'workflow_run', {'workflow_run': copy.deepcopy(github.ci)}), 0)
            github.members[0]['headRefOid'] = sha(2)
            before = copy.deepcopy(github.writes)
            self.assertEqual(self.execute(github, 'workflow_run', {'workflow_run': copy.deepcopy(github.ci)}, run_id=11), 0)
            self.assertEqual(github.writes, before)

    def test_unsigned_after_250_fails_entire_certification(self):
        github = Consumer([pull(head=sha(251))])
        nodes = []
        for number in range(1, 252):
            c = commit(sha(number), signed=number != 251)
            nodes.append({'sha': c['oid'], 'commit': {key: c[key] for key in ('message','author','committer')},
                          'author': c['githubAuthor'], 'parents': [{'sha': sha(number-1)}]})
        transport = type('Recorded', (), {})()
        transport.request = lambda path, payload=None, method=None: {'base_commit': {'sha': sha(1000)}, 'total_commits': 251,
            'commits': nodes[(int(path.rsplit('page=', 1)[-1])-1)*100:int(path.rsplit('page=',1)[-1])*100]}
        inventory = GitHub('org/repo', transport)
        github.commits = inventory.commits
        self.assertEqual(self.execute(github), 1)
        self.assertIn(sha(251)[:12], github.checks[-1]['output']['summary'])
        self.assertIn('250 signed, 0 exempt, 1 failed', github.checks[-1]['output']['summary'])

    def test_partial_duplicate_and_missing_head_inventories_cannot_pass(self):
        first = commit(sha(1))
        raw = {'sha': first['oid'], 'commit': {key: first[key] for key in ('message','author','committer')},
               'author': first['githubAuthor'], 'parents': [{'sha': sha(0)}]}
        cases = [dict(base_commit={'sha': sha(1000)}, total_commits=2, commits=[raw]),
                 dict(base_commit={'sha': sha(1000)}, total_commits=2, commits=[raw, raw]),
                 dict(base_commit={'sha': sha(999)}, total_commits=1, commits=[raw]),
                 dict(base_commit={'sha': sha(1000)}, total_commits=1, commits=[dict(raw, sha=sha(2))])]
        for response in cases:
            with self.subTest(response=response):
                transport = type('Recorded', (), {})()
                transport.request = lambda *a, **kw: response
                with self.assertRaises(Refused):
                    GitHub('org/repo', transport).commits(pull())

    def test_queue_membership_disappearing_never_finishes_success(self):
        github = Consumer()
        entry = dict(id='one', baseCommit={'oid': sha(1000)}, headCommit={'oid': sha(2001)}, pullRequest=pull())
        payload = {'merge_group': {'base_ref': 'refs/heads/main', 'base_sha': sha(1000), 'head_sha': sha(2001)}}
        with patch.object(github, 'queue', side_effect=[[entry], [entry], []]):
            self.assertEqual(self.execute(github, 'merge_group', payload), 1)
        self.assertEqual(github.checks[-1]['conclusion'], 'failure')

    def test_return_to_draft_leaves_pending_untouched(self):
        github = Consumer()
        def inventory(expected):
            github.members[0]['isDraft'] = True
            return [commit(sha(1))]
        github.commits = inventory
        self.assertEqual(self.execute(github), 1)
        self.assertEqual(github.checks[-1]['status'], 'in_progress')
        self.assertEqual(len(github.writes), 1)

    def test_recorded_github_ci_associations_fail_closed(self):
        for fixture in (Path(__file__).parent / 'fixtures').glob('*.json'):
            content = json.loads(fixture.read_text())
            if 'workflow_run' not in content:
                continue
            recorded = content['workflow_run']
            github = Consumer()
            github.repository = recorded['repository']['full_name']
            github.ci = copy.deepcopy(recorded)
            original_api = github.api
            def fixture_api(path, payload=None, method=None):
                if '/actions/workflows/' in path:
                    return {'id': recorded['workflow_id']}
                return original_api(path, payload, method)
            github.api = fixture_api
            config = Config(sha(900), 10, 1, f'https://github.com/{github.repository}/actions/runs/10')
            with self.subTest(fixture=fixture.name), redirect_stdout(io.StringIO()):
                self.assertEqual(run(github, 'workflow_run', {'workflow_run': recorded}, config), 1)
                self.assertEqual(github.writes, [])


if __name__ == '__main__':
    unittest.main()
