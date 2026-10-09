import copy
import unittest
from dco_checker import Obsolete, Refused
from dco_checker.engine import Config, make_evidence
from dco_checker.statuses import Gate
from dco_checker.transport import APIError

CREATOR = dict(id=41898282, login='github-actions[bot]', type='Bot')


class API:
    repository = 'org/repo'
    def __init__(self):
        self.statuses, self.writes = [], []
        self.lose_response = False
        self.apply = True
    def api(self, path, payload=None, method=None):
        if payload is None:
            page = int(path.rsplit('page=', 1)[-1])
            return copy.deepcopy(list(reversed(self.statuses))[(page-1)*100:page*100])
        self.writes.append(copy.deepcopy(payload))
        status = dict(payload, id=len(self.statuses)+1, creator=CREATOR)
        if self.apply:
            self.statuses.append(status)
        if self.lose_response:
            self.lose_response = False
            raise APIError('lost mutation response', ambiguous=True)
        return copy.deepcopy(status)


def gate(api, run_id=10):
    evidence = make_evidence('org/repo', 'a'*40, [], None, 'b'*40, 'c'*40)
    config = Config('b'*40, run_id, 1, f'https://github.com/org/repo/actions/runs/{run_id}', 'c'*40)
    return Gate(api, 'a'*40, evidence, config)


def historical(api, count, state='success'):
    for number in range(count):
        api.statuses.append(dict(id=number+1, context='DCO-owned', state=state,
            target_url='https://github.com/org/repo/actions/runs/1#dco:v2:1:1:'+'d'*64, creator=CREATOR))


class GateTests(unittest.TestCase):
    def test_pending_and_terminal_are_distinct_identified_records(self):
        api = API(); selected = gate(api)
        selected.start(); selected.finish('success', 'certified')
        self.assertEqual([s['state'] for s in api.statuses], ['pending', 'success'])
        self.assertEqual(api.statuses[-1]['context'], 'DCO-owned')
        self.assertEqual(api.statuses[-1]['target_url'], selected.target_url)
        self.assertIn(selected.evidence['digest'], selected.target_url)

    def test_ambiguous_append_is_reconciled_without_replaying_post(self):
        api = API(); api.lose_response = True
        selected = gate(api); selected.start()
        self.assertEqual(len(api.writes), 1)
        api.lose_response = True
        selected.finish('success', 'certified')
        self.assertEqual(len(api.writes), 2)

    def test_unresolved_ambiguous_append_does_not_replay(self):
        api = API(); api.lose_response = True; api.apply = False
        with self.assertRaisesRegex(Refused, 'unknown'):
            gate(api).start()
        self.assertEqual(len(api.writes), 1)

    def test_newer_status_execution_prevents_obsolete_writes(self):
        api = API(); gate(api, 11).start()
        with self.assertRaises(Obsolete):
            gate(api, 10).start()
        self.assertEqual(len(api.writes), 1)

    def test_duplicate_pending_and_terminal_converge(self):
        api = API(); selected = gate(api)
        selected.start(); selected.start()
        self.assertEqual(len(api.writes), 1)
        selected.finish('failure', 'missing sign-off')
        selected.finish('failure', 'missing sign-off')
        self.assertEqual(len(api.writes), 2)

    def test_last_success_always_retains_a_blocking_capacity_slot(self):
        api = API(); historical(api, 997)
        selected = gate(api); selected.start(); selected.finish('success', 'certified')
        self.assertEqual(len(api.statuses), 999)
        with self.assertRaisesRegex(Refused, 'fresh signed head'):
            gate(api, 11).start()
        self.assertEqual(len(api.statuses), 1000)
        self.assertEqual(api.statuses[-1]['state'], 'pending')
        with self.assertRaisesRegex(Refused, 'capacity'):
            gate(api, 12).start()
        self.assertEqual(len(api.statuses), 1000)

    def test_near_capacity_blocks_before_scanning_and_preserves_remaining_slots(self):
        api = API(); historical(api, 998)
        with self.assertRaisesRegex(Refused, 'capacity'):
            gate(api).start()
        self.assertEqual(api.statuses[-1]['state'], 'pending')
        self.assertEqual(len(api.statuses), 999)
        with self.assertRaisesRegex(Refused, 'capacity'):
            gate(api, 11).start()
        self.assertEqual(len(api.statuses), 999)

    def test_unknown_legacy_exhausted_success_is_reported_without_claimed_recovery(self):
        api = API(); historical(api, 1000)
        with self.assertRaisesRegex(Refused, 'fresh signed head'):
            gate(api).start()
        self.assertEqual(len(api.writes), 0)
        self.assertEqual(api.statuses[-1]['state'], 'success')

    def test_unexpected_actor_malformed_provenance_and_duplicate_page_refuse(self):
        for field, value in [('creator', dict(id=1, login='somebody', type='User')),
                             ('target_url', 'https://example.org/run'), ('state', 'neutral')]:
            api = API(); historical(api, 1)
            api.statuses[0][field] = value
            with self.assertRaises(Refused):
                gate(api).start()
            self.assertEqual(api.writes, [])
        api = API(); historical(api, 101)
        api.statuses[100]['id'] = api.statuses[0]['id']
        with self.assertRaisesRegex(Refused, 'repeated'):
            gate(api).start()

    def test_nonpositive_identifiers_and_oversized_pages_cannot_publish(self):
        for field, value in [('id', 0), ('target_url', 'https://github.com/org/repo/actions/runs/0#dco:v2:0:1:'+'d'*64),
                             ('target_url', 'https://github.com/org/repo/actions/runs/1#dco:v2:1:0:'+'d'*64)]:
            api = API(); historical(api, 1); api.statuses[0][field] = value
            with self.assertRaises(Refused):
                gate(api).start()
            self.assertEqual(api.writes, [])
        api = API(); historical(api, 101)
        api.api = lambda *args, **kwargs: copy.deepcopy(api.statuses)
        with self.assertRaisesRegex(Refused, 'Malformed'):
            gate(api).start()
        self.assertEqual(api.writes, [])
