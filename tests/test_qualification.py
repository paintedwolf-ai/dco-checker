"""Ensure hosted evidence cannot accidentally claim another check's outcome."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('qualification_record', Path(__file__).parent / 'qualification/record.py')
record = importlib.util.module_from_spec(spec)
spec.loader.exec_module(record)


class HostedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=42, repository={'full_name': 'org/repo'}, status='completed',
                        html_url='https://github.com/org/repo/actions/runs/42')
        self.jobs = [{'steps': [{'name': 'Certify original PR commits'}]}]
        self.check = dict(name='DCO-owned', head_sha='a'*40, details_url=self.run['html_url'],
                          status='completed', conclusion='success', app={'id': 15368},
                          external_id='dco:v2:42:1:'+'b'*64, output={'summary': 'Audited evidence'})

    def validate(self, checks):
        return record.verify(self.run, self.jobs, checks, repository='org/repo', run_id=42,
                             head='a'*40, conclusion='success', app_id=15368)

    def test_actual_run_target_app_and_evidence_are_required(self):
        self.assertEqual(self.validate([self.check]), [])
        for key, value in [('head_sha', 'c'*40), ('details_url', 'https://github.com/org/repo/actions/runs/43'),
                           ('app', {'id': 123}), ('conclusion', 'failure'), ('external_id', '')]:
            with self.subTest(key=key):
                self.assertTrue(self.validate([dict(self.check, **{key: value})]))

    def test_no_published_check_is_never_qualification(self):
        self.assertTrue(self.validate([]))


if __name__ == '__main__':
    unittest.main()
