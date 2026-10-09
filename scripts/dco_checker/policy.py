"""Versioned final-trailer policy and bounded contributor-facing output."""
from dataclasses import dataclass
import html
import re
from . import POLICY_VERSION

TRAILER = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)$")
SIGNOFF = re.compile(r"^(.+?)\s+<([^<>\s]+)>$")
EMAIL = re.compile(r"^[^@<>\s]+@[^@<>\s]+\.[^@<>\s]+$")


@dataclass(frozen=True)
class Evaluation:
    pr: int
    oid: str
    outcome: str
    reason: str


def trailers(message):
    lines = message.rstrip().splitlines()
    # Only the final paragraph is eligible. Fenced examples/body text are never trailers.
    start = len(lines)
    while start and lines[start - 1].strip():
        start -= 1
    block = lines[start:]
    result = []
    for line in block:
        match = TRAILER.fullmatch(line)
        if not match:
            return []
        result.append((match[1].casefold(), match[2].strip()))
    return result


def evaluate(commit, pr):
    oid = commit["oid"]
    if commit["parents"]["totalCount"] > 1:
        return Evaluation(pr, oid, "exempt", "merge commit (multiple parents)")
    if (commit.get("githubAuthor") or {}).get("type") == "Bot":
        return Evaluation(pr, oid, "exempt", "GitHub-associated Bot author")
    pairs = {(identity.get("name", "").strip().casefold(), identity.get("email", "").casefold())
             for identity in (commit["author"], commit["committer"])
             if identity.get("name") and identity.get("email")}
    values = [value for key, value in trailers(commit["message"]) if key == "signed-off-by"]
    if not values:
        return Evaluation(pr, oid, "failed", "missing Signed-off-by in final trailer block")
    parsed = [SIGNOFF.fullmatch(value) for value in values]
    valid = [match for match in parsed if match and EMAIL.fullmatch(match[2])]
    if any((match[1].strip().casefold(), match[2].casefold()) in pairs for match in valid):
        return Evaluation(pr, oid, "signed", "sign-off matches author or committer identity")
    return Evaluation(pr, oid, "failed", "sign-off identity does not match author or committer" if valid else "malformed sign-off identity or email")


def escape_markdown(value):
    return re.sub(r"([\\`*{}_\[\]()#+.!|>-])", r"\\\1", html.escape(str(value)))


def render(repository, evidence, results, *, error=None):
    failed = [result for result in results if result.outcome == "failed"]
    counts = {key: sum(result.outcome == key for result in results) for key in ("signed", "exempt", "failed")}
    text = ["## Original commit certification", "",
            f"Evaluated {len(results)} commit/PR contexts: {counts['signed']} signed, {counts['exempt']} exempt, {counts['failed']} failed.", ""]
    if error:
        text += ["**Evidence unavailable or changed:** " + escape_markdown(error), ""]
    for result in failed[:100]:
        text.append(f"- PR #{result.pr}: [{result.oid[:12]}](https://github.com/{repository}/commit/{result.oid}) — {result.reason}.")
    if len(failed) > 100:
        text.append(f"- {len(failed) - 100} additional failing commit/PR contexts omitted; inspect the workflow log.")
    if failed:
        text += ["", "Add a final `Signed-off-by: Name <email>` trailer matching the author or committer, then push the corrected commits. Use `git commit -s` for new commits; rewriting published commits requires coordinating with other contributors."]
    exempt = {reason: sum(r.reason == reason for r in results) for reason in sorted({r.reason for r in results if r.outcome == "exempt"})}
    for reason, count in exempt.items():
        text.append(f"- Exempt: {count} — {reason}.")
    text += ["", "Recheck using the DCO workflow's manual dispatch with the PR number. Check UI rerun requests are not supported.", "", "### Evidence", "", f"Target: `{evidence['sha']}`. Policy: `{POLICY_VERSION}`; checker: `{html.escape(evidence['revision'])}`; digest: `{evidence['digest']}`."]
    for member in evidence["members"]:
        text.append(f"- PR #{member['number']}: base `{member['baseRefOid']}`, head `{member['headRefOid']}`.")
    output = "\n".join(text)
    encoded = output.encode("utf-8")
    if len(encoded) > 60000:
        output = encoded[:59000].decode("utf-8", "ignore") + "\n\nAdditional evidence context omitted to respect GitHub output limits."
    return output
