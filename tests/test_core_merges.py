import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from dco_checker import Refused
from dco_checker.merges import Merges

IDENTITY = {"GIT_AUTHOR_NAME": "Author", "GIT_AUTHOR_EMAIL": "author@example.org",
            "GIT_COMMITTER_NAME": "Author", "GIT_COMMITTER_EMAIL": "author@example.org"}


class Source:
    """A real repository served to the checker over file://, with filtered fetches allowed."""

    def __init__(self, root):
        self.root = Path(root)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "uploadpack.allowFilter", "true")
        self.git("config", "uploadpack.allowAnySHA1InWant", "true")

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(IDENTITY, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", "-C", str(self.root), *args], env=env, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, message, **files):
        for name, body in files.items():
            (self.root / name).write_text(body)
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def merge(self, branch, resolution=None, extra=None):
        """Merge `branch` into the current branch; `resolution` settles conflicts and `extra` adds edits."""
        result = subprocess.run(["git", "-C", str(self.root), "merge", "--no-ff", "--no-commit", branch], capture_output=True,
                                env={**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **IDENTITY,
                                     "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        if result.returncode and not resolution:
            raise AssertionError(result.stderr)
        for name, body in {**(resolution or {}), **(extra or {})}.items():
            (self.root / name).write_text(body)
        self.git("add", "-A")
        self.git("commit", "--quiet", "--no-edit", "-m", "Merge " + branch)
        return self.facts("HEAD")

    def facts(self, ref):
        oid = self.git("rev-parse", ref)
        return oid, self.git("rev-parse", ref + "^@").split(), self.git("rev-parse", ref + "^{tree}")


class MergeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Source(directory.name)
        self.source.commit("base", **{"a.txt": "one\n", "b.txt": "two\n"})
        self.source.git("branch", "feature")
        self.source.commit("main edit", **{"a.txt": "one main\n"})
        self.source.git("checkout", "--quiet", "feature")
        self.source.commit("feature edit", **{"b.txt": "two feature\n"})
        self.merges = Merges("org/repo", None, remote="file://" + str(self.source.root))

    def test_a_clean_merge_is_identical_to_the_automatic_merge(self):
        oid, parents, tree = self.source.merge("main")
        self.assertTrue(self.merges.clean(oid, parents, tree))

    def test_a_clean_merge_with_added_edits_is_not(self):
        oid, parents, tree = self.source.merge("main", extra={"c.txt": "slipped in\n"})
        self.assertFalse(self.merges.clean(oid, parents, tree))

    def test_a_conflict_resolution_is_not(self):
        self.source.commit("feature conflicts", **{"a.txt": "one feature\n"})
        oid, parents, tree = self.source.merge("main", resolution={"a.txt": "one resolved\n"})
        self.assertFalse(self.merges.clean(oid, parents, tree))

    def test_only_two_parent_merges_can_be_clean(self):
        self.source.git("checkout", "--quiet", "-b", "third", "main~1")
        self.source.commit("third edit", **{"c.txt": "three\n"})
        self.source.git("checkout", "--quiet", "feature")
        self.source.git("merge", "--quiet", "--no-edit", "main", "third")
        self.assertFalse(self.merges.clean(*self.source.facts("HEAD")))
        self.assertFalse(Merges("org/repo", None, run=self.fail).clean("a" * 40, ["b" * 40], "c" * 40))

    def test_evidence_that_contradicts_the_objects_is_refused(self):
        oid, parents, tree = self.source.merge("main")
        with self.assertRaisesRegex(Refused, "contradict"):
            self.merges.clean(oid, parents, "f" * 40)
        with self.assertRaisesRegex(Refused, "contradict"):
            self.merges.clean(oid, list(reversed(parents)), tree)

    def test_an_unreachable_commit_is_refused_and_the_token_stays_out_of_arguments(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs["env"]))
            return subprocess.CompletedProcess(command, 128 if "fetch" in command else 0, "", "")
        with self.assertRaisesRegex(Refused, "could not read"):
            Merges("org/repo", "secret-token", run=run).clean("a" * 40, ["b" * 40, "c" * 40], "d" * 40)
        self.assertTrue(all("secret-token" not in " ".join(command) for command, _ in calls))
        self.assertTrue(all(env["GIT_CONFIG_KEY_0"] == "http.extraheader" for _, env in calls))


if __name__ == "__main__":
    unittest.main()
