"""Whether a merge commit is exactly the automatic merge of its parents.

A merge whose tree equals Git's own conflict-free merge of its two parents adds no
authored content. Any other merge carries a resolution or extra changes someone wrote,
which a sign-off must certify. Objects come from a blob-less partial clone; blobs the
merge reads are fetched on demand. The token travels as an HTTP header in Git's
environment, never in arguments.
"""
import base64
import os
import subprocess
import tempfile

from . import Refused
from .evidence import SHA


class Merges:
    def __init__(self, repository, token, *, remote=None, run=subprocess.run, timeout=300):
        self.remote = remote or f"https://github.com/{repository}.git"
        self.token, self.run, self.timeout = token, run, timeout
        self.directory = None

    def git(self, *args, check=True):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        if self.token:
            header = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.extraheader", GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {header}")
        try:
            result = self.run(["git", "-C", self.directory, *args], env=env, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Refused("Git is unavailable for merge certification: " + type(error).__name__) from error
        if check and result.returncode:
            raise Refused("Git could not read merge evidence: " + " ".join(args[:2]))
        return result

    def repository(self):
        if self.directory is None:
            self.directory = tempfile.mkdtemp(prefix="dco-merges-")
            self.git("init", "--bare", "--quiet")
            self.git("remote", "add", "origin", self.remote)
            self.git("config", "remote.origin.promisor", "true")
            self.git("config", "remote.origin.partialclonefilter", "blob:none")
        return self.directory

    def clean(self, oid, parents, tree):
        """True when the merge is a two-parent merge identical to Git's conflict-free merge."""
        if len(parents) != 2 or not all(SHA.fullmatch(value) for value in (oid, tree, *parents)):
            return False
        self.repository()
        self.git("fetch", "--quiet", "--no-tags", "--filter=blob:none", "origin", oid)
        recorded = self.git("rev-list", "--parents", "-n", "1", oid).stdout.split()
        if recorded != [oid, *parents] or self.git("rev-parse", oid + "^{tree}").stdout.strip() != tree:
            raise Refused("Merge commit objects contradict API evidence")
        merged = self.git("merge-tree", "--write-tree", "--no-messages", *parents, check=False)
        if merged.returncode == 1:
            return False
        if merged.returncode:
            raise Refused("Git could not merge the parents of " + oid[:12])
        return merged.stdout.split()[0] == tree
