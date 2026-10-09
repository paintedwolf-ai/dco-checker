"""Validate modern workflow concurrency alongside the narrowly scoped actionlint exception."""
import re
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).parents[1]
EXPRESSION = re.compile(r'^\$\{\{\s*.+?\s*\}\}$', re.DOTALL)


class WorkflowLoader(yaml.SafeLoader):
    """GitHub YAML treats `on` as a key, rather than YAML 1.1 boolean syntax."""


WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != 'tag:yaml.org,2002:bool']
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false)$', re.I), list('tTfF'))


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'duplicate workflow key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


WorkflowLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load(source):
    result = yaml.load(source, Loader=WorkflowLoader)
    if not isinstance(result, dict):
        raise ValueError('workflow must be a mapping')
    return result


def concurrency(value):
    if isinstance(value, str):
        if not value.strip():
            raise ValueError('concurrency group must be nonempty')
        return
    if not isinstance(value, dict) or set(value) - {'group', 'cancel-in-progress', 'queue'}:
        raise ValueError('unsupported concurrency configuration')
    group = value.get('group')
    if not isinstance(group, str) or not group.strip():
        raise ValueError('concurrency group must be a nonempty string')
    queue = value.get('queue', 'single')
    if queue not in ('single', 'max'):
        raise ValueError('queue must be single or max')
    cancel = value.get('cancel-in-progress', False)
    if not (type(cancel) is bool or isinstance(cancel, str) and EXPRESSION.fullmatch(cancel)):
        raise ValueError('cancel-in-progress must be boolean or an expression')
    if queue == 'max' and cancel is not False:
        raise ValueError('queue max cannot cancel in-progress runs')


def validate(workflow):
    if 'concurrency' in workflow:
        concurrency(workflow['concurrency'])
    jobs = workflow.get('jobs', {})
    if not isinstance(jobs, dict):
        raise ValueError('jobs must be a mapping')
    for job in jobs.values():
        if not isinstance(job, dict):
            raise ValueError('job must be a mapping')
        if 'concurrency' in job:
            concurrency(job['concurrency'])


class WorkflowContracts(unittest.TestCase):
    def test_all_workflow_concurrency_sections_are_valid(self):
        files = sorted((ROOT / '.github/workflows').glob('*.yml'))
        files += [ROOT / 'examples/dco.yml', ROOT / 'tests/qualification/consumer.template.yml']
        for path in files:
            with self.subTest(path=path):
                validate(load(path.read_text()))

    def test_every_dco_caller_has_same_serial_fifo_contract(self):
        for path in [ROOT / '.github/workflows/dco.yml', ROOT / 'examples/dco.yml',
                     ROOT / 'tests/qualification/consumer.template.yml']:
            with self.subTest(path=path):
                workflow = load(path.read_text())
                self.assertEqual(workflow['concurrency'],
                                 {'group': 'dco-certification', 'queue': 'max', 'cancel-in-progress': False})
                self.assertEqual(set(workflow['on']), {'pull_request_target','workflow_run','merge_group','workflow_dispatch'})
                self.assertEqual(workflow['permissions'],
                                 {'contents': 'read','pull-requests': 'read','actions': 'read','checks': 'write'})
                self.assertEqual(workflow['jobs']['certify']['runs-on'], 'ubuntu-24.04')

    def test_legal_concurrency_fixtures(self):
        for value in ['fixed-group', '${{ github.workflow }}', {'group':'fixed'},
                      {'group':'fixed','queue':'single','cancel-in-progress':True},
                      {'group':'fixed','queue':'single','cancel-in-progress':'${{ github.ref != \'refs/heads/main\' }}'},
                      {'group':'fixed','queue':'max','cancel-in-progress':False}]:
            with self.subTest(value=value):
                concurrency(value)
                validate({'jobs': {'test': {'concurrency': value}}})

    def test_illegal_concurrency_fixtures(self):
        for value in [None, False, '', {}, {'group':True}, {'group':''}, {'group':'fixed','queue':'unbounded'},
                      {'group':'fixed','queue':True}, {'group':'fixed','cancel-in-progress':'false'},
                      {'group':'fixed','queue':'max','cancel-in-progress':True},
                      {'group':'fixed','queue':'max','cancel-in-progress':'${{ true }}'},
                      {'group':'fixed','queu':'max'}, {'group':'fixed','queue':['max']}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                concurrency(value)
            with self.subTest(job_value=value), self.assertRaises(ValueError):
                validate({'jobs': {'test': {'concurrency': value}}})

    def test_duplicate_keys_are_rejected_and_on_remains_string(self):
        self.assertIn('on', load('on: [push]\nconcurrency:\n  group: fixed\n  queue: max\n  cancel-in-progress: false'))
        with self.assertRaises(ValueError):
            load('concurrency:\n  queue: max\n  queue: single')


if __name__ == '__main__':
    unittest.main()
