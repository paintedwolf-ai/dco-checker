import unittest
from dco_checker.policy import evaluate, render, trailers
from dco_checker.engine import make_evidence


def commit(message, *, author=None, committer=None, parents=1, bot=False):
    return {"oid": "a" * 40, "message": message,
        "author": author or {"name": "Alice", "email": "alice@example.org"},
        "committer": committer or {"name": "Bob", "email": "bob@example.org"},
        "parents": {"totalCount": parents}, "githubAuthor": {"type": "Bot" if bot else "User"}}


class PolicyTests(unittest.TestCase):
    def test_final_trailers_and_identity_pairs(self):
        for message in ["subject\n\nSigned-off-by: Alice <alice@example.org>", "subject\n\nSIGNED-OFF-BY: ALICE <ALICE@example.org>\nCo-authored-by: C <c@example.org>", "Signed-off-by: Bob <bob@example.org>"]:
            self.assertEqual(evaluate(commit(message), 1).outcome, "signed")
        for message in ["subject\n\n```\nSigned-off-by: Alice <alice@example.org>\n```", "Signed-off-by: Alice <alice@example.org>\n\nbody", "subject\nSigned-off-by: Alice <alice@example.org>", "subject\n\nSigned-off-by: Alice <bob@example.org>", "subject\n\nSigned-off-by: Alice <alice@example>"]:
            self.assertEqual(evaluate(commit(message), 1).outcome, "failed")

    def test_exemption_is_explicit_and_account_associated(self):
        self.assertEqual(evaluate(commit("no trailer", parents=2), 1).reason, "merge commit (multiple parents)")
        self.assertEqual(evaluate(commit("no trailer", bot=True), 1).reason, "GitHub-associated Bot author")
        value = commit("no trailer", author={"name": "bot[bot]", "email": "bot@users.noreply.github.com"})
        value["githubAuthor"] = None
        self.assertEqual(evaluate(value, 1).outcome, "failed")

    def test_output_bounds_failures_and_escapes_errors(self):
        evidence = make_evidence("org/repo", "a" * 40, [], None, "b" * 40)
        results = [evaluate(commit("no trailer"), 1) for _ in range(130)]
        output = render("org/repo", evidence, results, error="<script>bad</script>")
        self.assertIn("30 additional", output)
        self.assertNotIn("<script>", output)
        self.assertLess(len(output.encode()), 60000)
        self.assertIn("130 failed", output)

    def test_evidence_digest_binds_every_context_and_policy(self):
        first = make_evidence("org/repo", "a" * 40, [{"number": 1}], None, "b" * 40)
        second = make_evidence("org/repo", "a" * 40, [{"number": 2}], None, "b" * 40)
        self.assertNotEqual(first["digest"], second["digest"])
