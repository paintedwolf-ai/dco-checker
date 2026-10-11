"""Ensure hosted evidence cannot accidentally claim another check's outcome."""
import importlib.util
import hashlib
import json
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
        self.check = dict(name='DCO audit', head_sha='a'*40, details_url=self.run['html_url'],
                          status='completed', conclusion='success', app={'id': 15368},
                          external_id='dco:v2:42:1:'+'b'*64, output={'summary': 'Audited evidence'})

    def validate(self, checks):
        return record.verify(self.run, self.jobs, checks, repository='org/repo', run_id=42,
                             head='a'*40, conclusion='success', app_id=15368)

    def test_actual_run_target_app_and_evidence_are_required(self):
        self.assertEqual(self.validate([self.check]), [])
        for key, value in [('head_sha', 'c'*40), ('external_id', 'dco:v2:43:1:'+'b'*64),
                           ('app', {'id': 123}), ('conclusion', 'failure'), ('external_id', '')]:
            with self.subTest(key=key):
                self.assertTrue(self.validate([dict(self.check, **{key: value})]))

    def test_status_gate_matches_audit_execution_publisher_and_evidence(self):
        status = {'context':'DCO-owned','state':'success',
                  'creator': {'id':41898282,'login':'github-actions[bot]','type':'Bot'},
                  'target_url': self.run['html_url'] + '#' + self.check['external_id']}
        self.assertEqual(record.verify_gate([status], [self.check], self.run, 'success'), [])
        for key, value in [('state','failure'), ('creator',{'id':123,'login':'github-actions[bot]','type':'Bot'}),
                           ('target_url',self.run['html_url']+'#dco:v2:42:1:'+'c'*64), ('context','unrelated')]:
            with self.subTest(key=key):
                self.assertTrue(record.verify_gate([dict(status, **{key:value})], [self.check], self.run, 'success'))

    def test_no_published_check_is_never_qualification(self):
        self.assertTrue(self.validate([]))

    def test_canonical_digest_is_recomputed_and_missing_or_altered_logs_refuse(self):
        evidence = {'repository':'org/repo','sha':'a'*40,'revision':'c'*40,
                    'caller_revision':'d'*40,'policy':'2','members':[], 'group':None}
        evidence['digest'] = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        check = dict(self.check, external_id='dco:v2:42:1:'+evidence['digest'])
        def verify(payload):
            return record.verify_evidence(payload, [check], self.run, repository='org/repo',
                head='a'*40, action_sha='c'*40, caller_revision='d'*40)
        logs = 'certify\tstep\t2026-10-09 DCO evidence: '+json.dumps(evidence)
        errors, retained = verify(logs)
        self.assertEqual(errors, [])
        self.assertEqual(retained['canonical_evidence'], evidence)
        self.assertTrue(verify('')[0])
        altered = dict(evidence, members=[{'number':123}])
        self.assertTrue(verify('DCO evidence: '+json.dumps(altered))[0])
        self.assertTrue(verify(logs+'\nDCO evidence: '+json.dumps(altered))[0])

    def test_actual_group_event_and_protected_root_are_retained_and_checked(self):
        group = {'branch':'main','root':'e'*40,'head':'a'*40,'event_base':'f'*40}
        members = [{'number':n,'headRefOid':str(n)*40,'baseRefOid':'e'*40,'isDraft':False,'state':'OPEN'} for n in (1,2)]
        evidence = {'repository':'org/repo','sha':'a'*40,'revision':'c'*40,
                    'caller_revision':'d'*40,'policy':'2','members':members, 'group':group}
        evidence['digest'] = hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        check = dict(self.check,external_id='dco:v2:42:1:'+evidence['digest'])
        event = {'merge_group':{'head_sha':'a'*40,'base_sha':'f'*40,'base_ref':'refs/heads/main'}}
        nodes = [{'headCommit':{'oid':head},'baseCommit':{'oid':base},'pullRequest':member}
                 for head,base,member in [('f'*40,'e'*40,members[0]),('a'*40,'f'*40,members[1])]]
        queue = {'data':{'repository':{'baseRef':{'target':{'oid':'e'*40}},'mergeQueue':{'entries':{'totalCount':2,'pageInfo':{'hasNextPage':False},'nodes':nodes}}}}}
        def verify(event_value, queue_value):
            logs = '\n'.join(['DCO evidence: '+json.dumps(evidence),'DCO_QUALIFICATION_EVENT='+json.dumps(event_value),'DCO_QUALIFICATION_QUEUE='+json.dumps(queue_value)])
            return record.verify_evidence(logs,[check],self.run,repository='org/repo',head='a'*40,action_sha='c'*40,caller_revision='d'*40)
        errors, retained = verify(event,queue)
        self.assertEqual(errors,[])
        self.assertEqual(retained['captured_events'],[event])
        self.assertTrue(verify({'merge_group':{'head_sha':'b'*40,'base_sha':'f'*40}},queue)[0])
        changed = json.loads(json.dumps(queue))
        changed['data']['repository']['mergeQueue']['entries']['nodes'] = nodes[1:]
        changed['data']['repository']['mergeQueue']['entries']['totalCount'] = 1
        self.assertTrue(verify(event,changed)[0])
        changed = json.loads(json.dumps(queue))
        changed['data']['repository']['mergeQueue']['entries']['nodes'][0]['pullRequest']['headRefOid']='9'*40
        self.assertTrue(verify(event,changed)[0])
        self.assertTrue(verify({'merge_group':dict(event['merge_group'],base_ref='refs/heads/other')},queue)[0])
        self.assertTrue(record.verify_evidence('DCO evidence: '+json.dumps(evidence),[check],self.run,
            repository='org/repo',head='a'*40,action_sha='c'*40,caller_revision='d'*40)[0])
        queue['data']['repository']['baseRef']['target']['oid']='b'*40
        self.assertTrue(verify(event,queue)[0])


if __name__ == '__main__':
    unittest.main()
