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
from dco_checker.evidence import GitHub, QueueInventory, queue_chain
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
        self.statuses = []
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
        return QueueInventory(sha(1000), copy.deepcopy(self.entries))
    def queue_members(self, inventory, base, head):
        return queue_chain(inventory, base, head)[1]
    def api(self, path, payload=None, method=None):
        if '/actions/runs/' in path:
            return copy.deepcopy(self.ci)
        if '/actions/workflows/' in path:
            return {'id': 7}
        if payload is None:
            if '/statuses?' in path:
                page = int(path.rsplit('page=', 1)[-1])
                return copy.deepcopy(list(reversed(self.statuses))[(page - 1) * 100:page * 100])
            if '/check-runs/' in path:
                return copy.deepcopy(self.checks[int(path.rsplit('/', 1)[-1]) - 1])
            return {'total_count': len(self.checks), 'check_runs': copy.deepcopy(self.checks)}
        self.writes.append((method, copy.deepcopy(payload)))
        if '/statuses/' in path:
            status = dict(payload, id=len(self.statuses) + 1,
                          creator=dict(id=41898282, login='github-actions[bot]', type='Bot'))
            self.statuses.append(status)
            return copy.deepcopy(status)
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
        config = Config(sha(900), run_id, 1, f'https://github.com/org/repo/actions/runs/{run_id}', sha(901))
        with redirect_stdout(io.StringIO()):
            return run(github, event, payload or {'inputs': {'pull_request': '1'}}, config)

    def test_duplicate_delivery_converges_on_identified_check(self):
        github = Consumer()
        self.assertEqual(self.execute(github), 0)
        self.assertEqual(self.execute(github), 0)
        self.assertEqual(len(github.checks), 1)
        self.assertEqual(github.checks[0]['conclusion'], 'success')
        self.assertEqual(sum(method == 'POST' and payload.get('name') == 'DCO audit' for method, payload in github.writes), 1)
        self.assertEqual(len(github.statuses), 2)

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
        self.assertEqual(github.statuses[-2]['state'], 'pending')
        self.assertEqual(github.checks[-1]['name'], 'DCO audit')

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

    def test_queue_event_base_is_checkpoint_not_unsigned_prefix_exemption(self):
        github = Consumer([pull(), pull(2)])
        github.entries = [dict(id='one', baseCommit={'oid': sha(1000)}, headCommit={'oid': sha(2001)}, pullRequest=pull()),
                          dict(id='two', baseCommit={'oid': sha(2001)}, headCommit={'oid': sha(2002)}, pullRequest=pull(2))]
        github.inventory[1] = [commit(sha(1), signed=False)]
        payload = {'merge_group': {'base_ref': 'refs/heads/main', 'base_sha': sha(2001), 'head_sha': sha(2002)}}
        self.assertEqual(self.execute(github, 'merge_group', payload), 1)
        self.assertEqual(github.statuses[-1]['state'], 'failure')
        self.assertIn('PR #1', github.checks[-1]['output']['summary'])

    def test_queue_root_change_after_scan_cannot_publish_success(self):
        github = Consumer()
        entry = dict(id='one', baseCommit={'oid': sha(1000)}, headCommit={'oid': sha(2001)}, pullRequest=pull())
        payload = {'merge_group': {'base_ref': 'refs/heads/main', 'base_sha': sha(1000), 'head_sha': sha(2001)}}
        with patch.object(github, 'queue', side_effect=[QueueInventory(sha(1000), [entry]),
                QueueInventory(sha(1000), [entry]), QueueInventory(sha(1001), [entry])]):
            self.assertEqual(self.execute(github, 'merge_group', payload), 1)
        self.assertNotEqual(github.statuses[-1]['state'], 'success')

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
        with patch.object(github, 'queue', side_effect=[QueueInventory(sha(1000), [entry]), QueueInventory(sha(1000), [entry]), QueueInventory(sha(1000), [])]):
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
        self.assertEqual(len(github.writes), 2)
        self.assertEqual(github.statuses[-1]['state'], 'pending')

    def test_gate_pending_precedes_audit_and_terminal_gate_follows_audit(self):
        github = Consumer()
        self.assertEqual(self.execute(github), 0)
        self.assertEqual([payload.get('state') or payload.get('status') for _, payload in github.writes],
                         ['pending', 'in_progress', 'completed', 'success'])
        self.assertEqual(github.writes[0][1]['context'], 'DCO-owned')
        self.assertEqual(github.writes[1][1]['name'], 'DCO audit')

    def test_audit_api_failure_after_target_resolution_invalidates_old_success(self):
        github = Consumer(); self.execute(github)
        original_api = github.api
        def unavailable(path, payload=None, method=None):
            if '/check-runs' in path:
                raise APIError('audit API unavailable')
            return original_api(path, payload, method)
        github.api = unavailable
        self.assertEqual(self.execute(github, run_id=11), 1)
        self.assertEqual(github.statuses[-1]['state'], 'pending')
        self.assertIn('/runs/11#', github.statuses[-1]['target_url'])

    def test_infrastructure_error_blocks_gate_and_has_distinct_state(self):
        github = Consumer()
        with patch.object(github, 'commits', side_effect=Refused('incomplete comparison')):
            self.assertEqual(self.execute(github), 1)
        self.assertEqual(github.statuses[-1]['state'], 'error')
        self.assertEqual(github.checks[-1]['conclusion'], 'failure')

    def test_lost_terminal_status_response_recovers_complete_publication(self):
        github = Consumer()
        original_api = github.api
        lost = [False]
        def response_lost(path, payload=None, method=None):
            result = original_api(path, payload, method)
            if payload is not None and payload.get('state') == 'success':
                lost[0] = True
                raise APIError('terminal response lost', ambiguous=True)
            if '/statuses?' in path and lost[0]:
                lost[0] = False
                raise APIError('first reconciliation unavailable')
            return result
        github.api = response_lost
        self.assertEqual(self.execute(github), 0)
        self.assertEqual([s['state'] for s in github.statuses], ['pending', 'success'])
        self.assertEqual(github.checks[-1]['conclusion'], 'success')

    def test_malformed_unapplied_audit_completion_cannot_green_gate(self):
        github = Consumer(); original_api = github.api
        def malformed(path, payload=None, method=None):
            if method == 'PATCH':
                return {'unexpected': 'body'}
            return original_api(path, payload, method)
        github.api = malformed
        self.assertEqual(self.execute(github), 1)
        self.assertEqual(github.statuses[-1]['state'], 'pending')
        self.assertNotIn('success', [status['state'] for status in github.statuses])

    def test_malformed_applied_audit_response_requires_verified_get_before_green(self):
        github = Consumer(); original_api = github.api
        verified_get = []
        def malformed(path, payload=None, method=None):
            result = original_api(path, payload, method)
            if method == 'PATCH':
                return {}
            if '/check-runs/' in path and payload is None:
                verified_get.append(result)
                return copy.deepcopy(github.checks[int(path.rsplit('/', 1)[-1])-1])
            return result
        github.api = malformed
        self.assertEqual(self.execute(github), 0)
        self.assertEqual(len(verified_get), 1)
        self.assertEqual(github.statuses[-1]['state'], 'success')

    def recorded_ci(self, name, members=None):
        fixture = Path(__file__).parent / 'fixtures' / name
        recorded = json.loads(fixture.read_text())['workflow_run']
        github = Consumer(members)
        github.repository = recorded['repository']['full_name']
        github.ci = copy.deepcopy(recorded)
        original_api = github.api
        def fixture_api(path, payload=None, method=None):
            if '/actions/workflows/' in path:
                return {'id': recorded['workflow_id']}
            return original_api(path, payload, method)
        github.api = fixture_api
        return github, recorded

    def execute_recorded(self, github, recorded):
        config = Config(sha(900), 10, 1, f'https://github.com/{github.repository}/actions/runs/10', sha(901))
        with redirect_stdout(io.StringIO()):
            return run(github, 'workflow_run', {'workflow_run': recorded}, config)

    def test_recorded_contradictory_ci_association_cannot_publish(self):
        github, recorded = self.recorded_ci('historical-ci-association-refreshed.json')
        self.assertEqual(self.execute_recorded(github, recorded), 1)
        self.assertEqual(github.writes, [])

    def test_recorded_empty_ci_association_certifies_complete_live_head_contexts(self):
        recorded = json.loads((Path(__file__).parent / 'fixtures/ci-association-absent.json').read_text())['workflow_run']
        github, recorded = self.recorded_ci('ci-association-absent.json',
            [pull(1, head=recorded['head_sha']), pull(2, head=recorded['head_sha'], base=sha(1001))])
        self.assertEqual(self.execute_recorded(github, recorded), 0)
        self.assertEqual(github.checks[-1]['head_sha'], recorded['head_sha'])
        self.assertIn('PR #2', github.checks[-1]['output']['summary'])
        github, recorded = self.recorded_ci('ci-association-absent.json',
            [pull(1, head=recorded['head_sha']), pull(2, head=recorded['head_sha'], base=sha(1001))])
        github.inventory[2] = [commit(recorded['head_sha'], signed=False)]
        self.assertEqual(self.execute_recorded(github, recorded), 1)
        self.assertEqual(github.checks[-1]['conclusion'], 'failure')

    def test_recorded_empty_ci_association_skips_obsolete_head_and_draft(self):
        github, recorded = self.recorded_ci('ci-association-absent.json')
        self.assertEqual(self.execute_recorded(github, recorded), 0)
        self.assertEqual(github.writes, [])
        github, recorded = self.recorded_ci('ci-association-absent.json', [pull(1, head=recorded['head_sha'], draft=True)])
        self.assertEqual(self.execute_recorded(github, recorded), 0)
        self.assertEqual(github.writes, [])

    def test_recorded_empty_ci_association_requires_complete_inventory_and_trusted_run(self):
        recorded = json.loads((Path(__file__).parent / 'fixtures/ci-association-absent.json').read_text())['workflow_run']
        github, recorded = self.recorded_ci('ci-association-absent.json', [pull(1, head=recorded['head_sha'])])
        with patch.object(github, 'contexts', side_effect=Refused('Incomplete open PR inventory')):
            self.assertEqual(self.execute_recorded(github, recorded), 1)
        self.assertEqual(github.writes, [])
        for field, value in [('repository', {'full_name': 'foreign/repo'}), ('event', 'push'),
                             ('head_sha', sha(888)), ('pull_requests', None), ('id', 123)]:
            with self.subTest(field=field):
                github, recorded = self.recorded_ci('ci-association-absent.json', [pull(1, head=recorded['head_sha'])])
                github.ci[field] = value
                self.assertEqual(self.execute_recorded(github, recorded), 1)
                self.assertEqual(github.writes, [])


if __name__ == '__main__':
    unittest.main()
