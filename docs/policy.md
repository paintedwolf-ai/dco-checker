# Certification policy v2

Certification applies to every commit reachable from the captured PR head that is
not reachable from its captured base. Every original PR in a merge group must pass.
A commit shared by multiple PR contexts is evaluated within each context.

## Sign-off grammar

A sign-off belongs in the final trailer paragraph, separated from the body by a
blank line. Every nonempty line in that paragraph must be an unindented
`Token: value` trailer. The `Signed-off-by` key is case insensitive. At least one
sign-off must match a complete author or committer name/email pair, using Unicode
case folding. Matching an author's name with a committer's email does not qualify.
Names and emails must be nonempty; email addresses need one `@`, no whitespace or
angle brackets, and a dotted domain. Multiple sign-offs and other trailers are
allowed. Coauthor trailers do not introduce additional required identities.

```text
Implement the change

Explain the behavior here.

Co-authored-by: Collaborator <collaborator@example.org>
Signed-off-by: Author Name <author@example.org>
```

A sign-off in prose, an indented quotation, a fenced example, or an earlier
paragraph is not a certification. Malformed trailers cannot qualify a commit.
Version 2 intentionally replaces the original anywhere-in-message parser with
final-trailer semantics; old messages containing only examples may now fail.

## Exemptions

Commits with more than one parent are exempt as merge commits. This includes
merges containing manual conflict resolutions; this policy does not separately
certify those resolutions. A GitHub-associated author of type `Bot` is exempt;
login or email resemblance to a bot is insufficient. Bot association does not
prove that automation created every change. These exemptions preserve the
established policy and appear with explicit reasons in audit summaries.

No repository owner, member, collaborator, or remediation exemption exists.
Cryptographic commit signing is separate from DCO certification and is not required.
Missing GitHub author association confers no bot exemption.

## Remediation

Use `git commit --signoff` for new contributions. To repair the last commit, use
`git commit --amend --no-edit --signoff`, then push the updated branch with
`--force-with-lease`. For several commits, use an interactive rebase and sign off
each affected commit; coordinate before rewriting a shared branch. Sign only when
you can certify the DCO. A check links failing commits and distinguishes missing,
malformed, and mismatched certifications. Dispatch DCO with the PR number to retry
after an infrastructure failure; changing commits ordinarily triggers a recheck.
