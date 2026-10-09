import io
import json
import unittest
import urllib.error
from unittest.mock import Mock
from dco_checker.transport import Transport, APIError


class Response(io.BytesIO):
    pass


class TransportTests(unittest.TestCase):
    def test_read_retries_and_explicit_contract(self):
        opener = Mock()
        opener.open.side_effect = [urllib.error.URLError("network"), Response(b'{"ok":true}')]
        sleep = Mock()
        transport = Transport("secret", opener=opener, sleep=sleep)
        self.assertEqual(transport.request("repos/org/repo"), {"ok": True})
        self.assertEqual(sleep.call_args.args, (1,))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/org/repo")
        self.assertEqual(request.headers["X-github-api-version"], "2022-11-28")

    def test_mutation_never_blindly_retries(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("secret transport lost")
        with self.assertRaises(APIError) as caught:
            Transport("secret", opener=opener).request("repos/org/repo/check-runs", {"name": "DCO-owned"})
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)

    def test_permanent_errors_and_partial_json_are_actionable(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError("url", 403, "Forbidden", {"X-GitHub-Request-Id": "request123"}, io.BytesIO(b'permission denied'))
        with self.assertRaisesRegex(APIError, "request123.*permission denied"):
            Transport("secret", opener=opener).request("repos/org/repo")
        self.assertEqual(opener.open.call_count, 1)
        opener.open.side_effect = [Response(b'{"errors":[{"message":"incomplete"}],"data":{}}')]
        with self.assertRaisesRegex(APIError, "GraphQL"):
            Transport("secret", opener=opener).request("graphql", {"query": "query{}"})

    def test_budget_prevents_sleep_beyond_deadline(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError("url", 429, "rate", {"Retry-After": "100"}, io.BytesIO(b'limited'))
        sleep = Mock()
        with self.assertRaisesRegex(APIError, "budget"):
            Transport("secret", opener=opener, budget=10, sleep=sleep).request("repos/org/repo")
        sleep.assert_not_called()

    def test_path_cannot_send_credentials_to_another_origin(self):
        opener = Mock()
        with self.assertRaisesRegex(APIError, "path"):
            Transport("secret", opener=opener).request("https://evil.example")
        opener.open.assert_not_called()

    def test_immutable_comparison_uses_real_transport_path_contract(self):
        from dco_checker.evidence import GitHub
        base, head = "a" * 40, "b" * 40
        comparison = {"base_commit": {"sha": base}, "total_commits": 1, "commits": [{
            "sha": head, "commit": {"message": "subject\n\nSigned-off-by: A <a@example.org>",
            "author": {"name": "A", "email": "a@example.org"}, "committer": {"name": "A", "email": "a@example.org"}},
            "author": {"type": "User"}, "parents": [{"sha": base}]}]}
        opener = Mock()
        opener.open.return_value = Response(json.dumps(comparison).encode())
        github = GitHub("org/repo", Transport("secret", opener=opener))
        commits = github.commits({"baseRefOid": base, "headRefOid": head})
        self.assertEqual(commits[0]["oid"], head)
        self.assertIn("/compare/" + base + "..." + head, opener.open.call_args.args[0].full_url)

    def test_slow_error_body_is_wall_bounded(self):
        import time
        class SlowBody(io.BytesIO):
            def read(self, size=-1):
                time.sleep(0.05)
                return super().read(size)
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError("url", 403, "denied", {}, SlowBody(b'forbidden'))
        with self.assertRaisesRegex(APIError, "body unavailable"):
            Transport("secret", opener=opener, timeout=0.005).request("repos/org/repo")
        self.assertEqual(opener.open.call_count, 1)
