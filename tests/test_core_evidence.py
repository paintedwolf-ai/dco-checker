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
