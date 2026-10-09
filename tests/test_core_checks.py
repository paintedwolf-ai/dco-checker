import copy
import unittest
from dco_checker import Obsolete, Refused
from dco_checker.checks import Audit
from dco_checker.engine import Config, make_evidence
from dco_checker.transport import APIError


class API:
    repository = "org/repo"
    def __init__(self):
        self.checks, self.posts = [], 0
        self.post_error, self.patch_error = False, False
    def api(self, path, payload=None, method=None):
        if method == "POST":
            self.posts += 1
            check = {"id": len(self.checks) + 1, "app": {"id": 15368}, **copy.deepcopy(payload)}
            self.checks.append(check)
            if self.post_error:
                self.post_error = False
                raise APIError("lost response", ambiguous=True)
            return check
        if method == "PATCH":
            check = self.checks[int(path.split('/')[-1]) - 1]
            check.update(copy.deepcopy(payload))
            if self.patch_error:
                self.patch_error = False
                raise APIError("lost response", ambiguous=True)
            return check
        if "check-runs?" in path:
            return {"total_count": len(self.checks), "check_runs": copy.deepcopy(self.checks)}
        return copy.deepcopy(self.checks[int(path.split('/')[-1]) - 1])


def publisher(api, run_id=10, attempt=1):
    evidence = make_evidence("org/repo", "a" * 40, [], None, "b" * 40, "c" * 40)
    return Audit(api, "a" * 40, evidence, Config("b" * 40, run_id, attempt, "https://github.com/org/repo/actions/runs/10", "c" * 40))


class ChecksTests(unittest.TestCase):
    def test_lost_post_response_reconciles_without_second_post(self):
        api = API()
        api.post_error = True
        check = publisher(api)
        check.start()
        check.finish("success", "certified")
        self.assertEqual(api.posts, 1)
        self.assertEqual(api.checks[0]["conclusion"], "success")

    def test_lost_patch_response_reconciles_applied_result(self):
        api = API()
        check = publisher(api)
        check.start()
        api.patch_error = True
        check.finish("failure", "missing sign-off")
        self.assertTrue(api.checks[0]["output"]["summary"].endswith("missing sign-off"))

    def test_newer_execution_blocks_obsolete_publication(self):
        api = API()
        old, new = publisher(api, 10), publisher(api, 11)
        old.start()
        new.start()
        new.finish("failure", "current evidence rejected")
        with self.assertRaises(Obsolete):
            old.finish("success", "obsolete result")
        self.assertEqual(api.checks[0]["status"], "in_progress")
        self.assertEqual(api.checks[1]["conclusion"], "failure")

    def test_duplicate_execution_identity_is_refused(self):
        api = API()
        check = publisher(api)
        check.start()
        api.checks.append({**api.checks[0], "id": 2})
        with self.assertRaisesRegex(Refused, "Duplicate"):
            check.finish("success", "ambiguous")

    def test_same_evidence_retry_recovers_its_identified_check(self):
        api = API()
        publisher(api).start()
        retry = publisher(api)
        retry.start()
        retry.finish("success", "recovered")
        self.assertEqual(api.posts, 1)

    def test_unexpected_app_and_target_are_refused(self):
        for field, value in [("app", {"id": 1}), ("head_sha", "c" * 40), ("name", "other")]:
            api = API()
            check = publisher(api)
            check.start()
            api.checks[0][field] = value
            with self.assertRaises(Refused):
                check.finish("success", "bad publisher")

    def test_completed_duplicate_reuses_same_immutable_check(self):
        api = API()
        first = publisher(api)
        first.start()
        first.finish("success", "certified")
        duplicate = publisher(api)
        duplicate.start()
        self.assertEqual(duplicate.check["status"], "completed")
        self.assertEqual(api.posts, 1)

    def test_pending_and_terminal_output_identify_actual_execution(self):
        import json
        api = API()
        check = publisher(api)
        check.start()
        pending = api.checks[0]["output"]
        self.assertIn("[Certification run](https://github.com/org/repo/actions/runs/10)", pending["summary"])
        record = json.loads(pending["text"].removeprefix("```json\n").removesuffix("\n```"))
        self.assertEqual(record["external_id"], check.external_id)
        self.assertEqual(record["run_id"], 10)
        self.assertEqual(record["checker_revision"], "b" * 40)
        self.assertEqual(record["caller_revision"], "c" * 40)
        # Mimic GitHub's suite/details URL rewriting; explicit provenance survives.
        api.checks[0]["details_url"] = "https://github.com/org/repo/runs/123"
        check.finish("success", "certified")
        self.assertEqual(api.checks[0]["output"]["text"], pending["text"])
        self.assertIn("actions/runs/10", api.checks[0]["output"]["summary"])

    def test_malformed_success_response_recovers_confirmed_get(self):
        api = API(); check = publisher(api); check.start()
        original_api = api.api
        def malformed(path, payload=None, method=None):
            response = original_api(path, payload, method)
            return {"unexpected": "body"} if method == "PATCH" else response
        api.api = malformed
        check.finish("success", "certified")
        self.assertEqual(check.check["status"], "completed")
        self.assertEqual(check.check["conclusion"], "success")

    def test_unconfirmed_normal_patch_responses_never_claim_completion(self):
        api = API(); check = publisher(api); check.start()
        original_api = api.api
        patches = []
        def ignored(path, payload=None, method=None):
            if method == "PATCH":
                patches.append(payload)
                return {"unexpected": "body"}
            return original_api(path, payload, method)
        api.api = ignored
        with self.assertRaisesRegex(Refused, "could not be confirmed"):
            check.finish("success", "certified")
        self.assertEqual(len(patches), 2)
        self.assertEqual(api.checks[0]["status"], "in_progress")

    def test_contradictory_completion_get_refuses_before_retry(self):
        api = API(); check = publisher(api); check.start()
        original_api = api.api
        patches = []
        def contradictory(path, payload=None, method=None):
            if method == "PATCH":
                patches.append(payload)
                return {}
            response = original_api(path, payload, method)
            if payload is None and "check-runs?" not in path:
                response["head_sha"] = "d" * 40
            return response
        api.api = contradictory
        with self.assertRaises(Refused):
            check.finish("success", "certified")
        self.assertEqual(len(patches), 1)
