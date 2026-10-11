import copy
import unittest
from unittest.mock import Mock
from dco_checker import Refused
from dco_checker.evidence import GitHub


def pull(number, *, head='a' * 40, base='b' * 40):
    return dict(number=number, headRefOid=head, baseRefOid=base, isDraft=False, state='OPEN')


def page(nodes, total, *, following=None, more=False):
    return {'pullRequests': dict(nodes=nodes, totalCount=total, pageInfo=dict(endCursor=following, hasNextPage=more))}


class OpenInventoryTests(unittest.TestCase):
    def github(self):
        return GitHub('org/repo', Mock())

    def test_fork_head_context_does_not_depend_on_commit_association(self):
        github = self.github()
        # The historical REST association endpoint returned [] for this fork
        # head; a GraphQL repository PR remains authoritative regardless.
        github.query = Mock(return_value=page([pull(4)], 1))
        github.api = Mock(side_effect=AssertionError('REST association must not be used'))
        self.assertEqual(github.contexts('a' * 40), [pull(4)])
        self.assertIn('states:[OPEN]', github.query.call_args.args[0])

    def test_pagination_filters_head_only_after_fetching_complete_inventory(self):
        github = self.github()
        github.query = Mock(side_effect=[page([pull(4), pull(9, head='c' * 40)], 3, following='next', more=True),
                                       page([pull(2, base='d' * 40)], 3)])
        self.assertEqual(github.contexts('a' * 40), [pull(2, base='d' * 40), pull(4)])
        self.assertEqual(github.query.call_args_list[1].kwargs['cursor'], 'next')

    def test_changed_partial_duplicate_and_stalled_inventory_are_refused(self):
        cases = [
            [page([pull(1)], 2)],
            [page([pull(1)], 2, following='next', more=True), page([pull(2)], 3)],
            [page([pull(1)], 2, following='next', more=True), page([pull(1)], 2)],
            [page([pull(1)], 2, more=True)],
            [page([], 2, following='next', more=True)],
            [page([pull(1)], 0)],
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                github = self.github()
                github.query = Mock(side_effect=pages)
                with self.assertRaises(Refused):
                    github.contexts('a' * 40)

    def test_null_invalid_identity_and_malformed_pagination_cannot_certify(self):
        nodes = [None, {**pull(1), 'headRefOid': 'wrong'}, {**pull(1), 'baseRefOid': None},
                 {**pull(1), 'number': True}, {**pull(1), 'isDraft': 'false'}, {**pull(1), 'state': 'CLOSED'}]
        for node in nodes:
            github = self.github()
            github.query = Mock(return_value=page([node], 1))
            # Boundary normalization in the engine catches the missing/malformed
            # response shape; valid-shaped authorities are refused directly.
            with self.assertRaises(Refused):
                github.contexts('a' * 40)
        for field, value in [('totalCount', True), ('nodes', None), ('pageInfo', {'hasNextPage': 'false', 'endCursor': None})]:
            connection = page([], 0)
            connection['pullRequests'][field] = value
            github = self.github()
            github.query = Mock(return_value=connection)
            with self.assertRaises(Refused):
                github.contexts('a' * 40)

    def test_recorded_authentic_fork_context_is_discovered(self):
        import json
        from pathlib import Path
        fixture = json.loads((Path(__file__).parent / 'fixtures/authentic-fork-association.json').read_text())
        self.assertEqual(fixture['rest_commit_pulls'], [])
        authority = fixture['graphql']['data']['repository']
        fork = authority['pullRequest']
        transport = Mock()
        transport.request.return_value = fixture['graphql']
        github = GitHub('paintedwolf-ai/dco-checker-qualification', transport)
        self.assertEqual(github.contexts(fork['headRefOid']), [fork])
        self.assertEqual(transport.request.call_args.args[0], 'graphql')
        self.assertIn('pullRequests(first:100', transport.request.call_args.args[1]['query'])


class QueueAuthorityTests(unittest.TestCase):
    def github(self):
        return GitHub('org/repo', Mock())

    def entry(self, number, base, head):
        return dict(id=str(number), baseCommit={'oid': base}, headCommit={'oid': head}, pullRequest=pull(number))

    def response(self, nodes, total, root='b'*40, following=None, more=False):
        return dict(baseRef={'target': {'oid': root}}, mergeQueue={'entries': dict(nodes=nodes,
                    totalCount=total, pageInfo=dict(endCursor=following, hasNextPage=more))})

    def test_root_captured_in_every_complete_paginated_queue_query(self):
        github = self.github()
        github.query = Mock(side_effect=[self.response([], 0)])
        inventory = github.queue('main')
        self.assertEqual(inventory.root, 'b'*40)
        self.assertEqual(inventory.entries, [])
        self.assertIn('baseRef:ref(qualifiedName:$ref)', github.query.call_args.args[0])
        self.assertEqual(github.query.call_args.kwargs['ref'], 'refs/heads/main')
        first = self.entry(1, 'b'*40, 'c'*40)
        second = self.entry(2, 'c'*40, 'd'*40)
        github.query = Mock(side_effect=[self.response([first], 2, following='next', more=True),
                                       self.response([second], 2)])
        self.assertEqual(github.queue('main').entries, [first, second])

    def test_changed_missing_root_and_partial_queue_refused(self):
        first = self.entry(1, 'b'*40, 'c'*40)
        for responses in ([self.response([first], 2)],
                [self.response([first], 2, following='next', more=True), self.response([], 2, root='e'*40)],
                [self.response([], 0, root=None)]):
            github = self.github()
            github.query = Mock(side_effect=responses)
            with self.assertRaises(Refused):
                github.queue('main')

    def test_immutable_first_parent_must_corroborate_queue_edge(self):
        from dco_checker.evidence import QueueInventory
        github = self.github()
        inventory = QueueInventory('b'*40, [self.entry(1, 'b'*40, 'c'*40)])
        cases = [None, {'sha': 'c'*40, 'parents': []},
                 {'sha': 'd'*40, 'parents': [{'sha': 'b'*40}]},
                 {'sha': 'c'*40, 'parents': [{'sha': 'e'*40}]},
                 {'sha': 'c'*40, 'parents': [{'sha': 'b'*40}, {'sha': 'b'*40}]}]
        for response in cases:
            github.api = Mock(return_value=response)
            with self.assertRaises(Refused):
                github.queue_members(inventory, 'b'*40, 'c'*40)
        github.api = Mock(return_value={'sha': 'c'*40, 'parents': [{'sha': 'b'*40}]})
        self.assertEqual(github.queue_members(inventory, 'b'*40, 'c'*40), [pull(1)])

    def test_recorded_cumulative_chain_includes_prefix_and_rejects_withdrawal(self):
        import json
        from pathlib import Path
        from dco_checker.evidence import QueueInventory
        fixture = json.loads((Path(__file__).parent / 'fixtures/authentic-cumulative-queue-prefix.json').read_text())
        root, commits = fixture['protected_root'], fixture['immutable_commits']
        def replay(capture):
            entries = copy.deepcopy(fixture[capture]['data']['repository']['mergeQueue']['entries']['nodes'])
            for entry in entries:
                pr = fixture['recorded_pull_requests'][str(entry['pullRequest']['number'])]
                # Historical state/base and absent initial baseCommit are
                # explicit replay assumptions documented in fixture provenance.
                entry['pullRequest'] = pull(pr['number'], head=pr['head']['sha'], base=root)
                entry.setdefault('baseCommit', {'oid': commits[entry['headCommit']['oid']]['parents'][0]['sha']})
            return entries
        github = self.github()
        github.api = Mock(side_effect=lambda path: commits[path.rsplit('/', 1)[-1]])
        initial = replay('initial_queue_capture')
        event_base = commits[initial[-1]['headCommit']['oid']]['parents'][0]['sha']
        head = initial[-1]['headCommit']['oid']
        inventory = QueueInventory(root, initial)
        self.assertEqual([pr['number'] for pr in github.queue_members(inventory, event_base, head)], [11, 13])
        with self.assertRaises(Refused):
            github.queue_members(QueueInventory(root, initial[1:]), event_base, head)
        rewritten = copy.deepcopy(initial[1:])
        rewritten[0]['baseCommit']['oid'] = root
        with self.assertRaises(Refused):
            github.queue_members(QueueInventory(root, rewritten), root, head)
        with self.assertRaises(Refused):
            github.queue_members(inventory, 'a'*40, head)
        rebuilt = replay('rebuilt_queue_capture')
        self.assertEqual([pr['number'] for pr in github.queue_members(QueueInventory(root, rebuilt),
                        rebuilt[-1]['baseCommit']['oid'], rebuilt[-1]['headCommit']['oid'])], [13, 16])
