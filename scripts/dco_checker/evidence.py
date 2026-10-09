"""Live authority snapshots and immutable, complete commit inventories."""
import re
from . import Refused

PR_FIELDS = "number headRefOid baseRefOid isDraft state"
PAGE = "pageInfo { hasNextPage endCursor } totalCount"
SHA = re.compile(r"^[0-9a-f]{40}$")


def snapshot(value):
    if not isinstance(value, dict):
        raise Refused("Missing pull request snapshot")
    result = {key: value[key] for key in ("number", "headRefOid", "baseRefOid", "isDraft", "state")}
    if (type(result["number"]) is not int or result["number"] <= 0 or
        not all(SHA.fullmatch(result[key]) for key in ("headRefOid", "baseRefOid")) or
        type(result["isDraft"]) is not bool or result["state"] not in ("OPEN", "CLOSED", "MERGED")):
        raise Refused("Malformed pull request snapshot")
    return result


def next_page(connection, cursor):
    page = connection["pageInfo"]
    if not page["hasNextPage"]:
        return None
    following = page["endCursor"]
    if not connection["nodes"] or not following or following == cursor:
        raise Refused("Pagination did not advance")
    return following


class GitHub:
    def __init__(self, repository, transport):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise Refused("GITHUB_REPOSITORY must be owner/name")
        self.repository, self.transport = repository, transport
        self.owner, self.name = repository.split("/")

    def api(self, path, payload=None, method=None):
        return self.transport.request(path, payload, method)

    def query(self, body, **variables):
        kinds = {"owner": "String!", "name": "String!", "number": "Int!", "branch": "String!", "cursor": "String"}
        declaration = ",".join(f"${key}:{kind}" for key, kind in kinds.items() if "$" + key in body or key in ("owner", "name"))
        result = self.api("graphql", {"query": "query(" + declaration + "){repository(owner:$owner,name:$name){" + body + "}}",
            "variables": {"owner": self.owner, "name": self.name, **variables}})
        repository = result["data"]["repository"]
        if not isinstance(repository, dict):
            raise Refused("GitHub repository is unavailable")
        return repository

    def pull(self, number):
        return snapshot(self.query("pullRequest(number:$number){" + PR_FIELDS + "}", number=number)["pullRequest"])

    def contexts(self, sha):
        # REST commit association includes contexts across different target branches.
        found, seen, page = [], set(), 1
        while True:
            nodes = self.api(f"repos/{self.repository}/commits/{sha}/pulls?per_page=100&page={page}")
            if not isinstance(nodes, list):
                raise Refused("Malformed commit PR associations")
            for node in nodes:
                if node["number"] in seen:
                    raise Refused("Duplicate commit PR association")
                seen.add(node["number"])
                current = self.pull(node["number"])
                if current["state"] == "OPEN" and current["headRefOid"] == sha:
                    found.append(current)
            if len(nodes) < 100:
                return sorted(found, key=lambda pr: pr["number"])
            page += 1

    def commits(self, expected):
        commits, seen, total, page = [], set(), None, 1
        while True:
            response = self.api(f"repos/{self.repository}/compare/{expected['baseRefOid']}...{expected['headRefOid']}?per_page=100&page={page}")
            if response["base_commit"]["sha"] != expected["baseRefOid"]:
                raise Refused("Comparison base differs from captured PR base")
            count = response["total_commits"]
            if type(count) is not int or count < 0 or (total is not None and total != count):
                raise Refused("Comparison commit count changed or is invalid")
            total = count
            nodes = response["commits"]
            for node in nodes:
                if not SHA.fullmatch(node["sha"]) or node["sha"] in seen:
                    raise Refused("Invalid or repeated comparison commit")
                seen.add(node["sha"])
                raw = node["commit"]
                if not isinstance(raw["message"], str) or not isinstance(node["parents"], list):
                    raise Refused("Malformed commit evidence")
                commits.append({"oid": node["sha"], "message": raw["message"], "author": raw["author"],
                    "committer": raw["committer"], "parents": {"totalCount": len(node["parents"])}, "githubAuthor": node.get("author")})
            if len(commits) == total:
                break
            if len(nodes) != 100 or len(commits) > total:
                raise Refused("Incomplete paginated comparison")
            page += 1
        if not commits or expected["headRefOid"] not in seen:
            raise Refused("Comparison omitted the PR head or contains no commits")
        return commits

    def queue(self, branch):
        entries, cursor, total = [], None, None
        while True:
            queue = self.query("mergeQueue(branch:$branch){entries(first:100,after:$cursor){" + PAGE +
                " nodes{id baseCommit{oid} headCommit{oid} pullRequest{" + PR_FIELDS + "}}}}", branch=branch, cursor=cursor)["mergeQueue"]
            if queue is None:
                raise Refused("Merge queue is unavailable")
            connection = queue["entries"]
            if total is not None and total != connection["totalCount"]:
                raise Refused("Merge queue changed during pagination")
            total = connection["totalCount"]
            entries += connection["nodes"]
            if len(entries) > total or len({entry["id"] for entry in entries}) != len(entries):
                raise Refused("Repeated merge queue page")
            cursor = next_page(connection, cursor)
            if cursor is None:
                break
        if len(entries) != total:
            raise Refused("Incomplete merge queue inventory")
        return entries


def queue_members(entries, base, head):
    by_head = {}
    for entry in entries:
        if entry["headCommit"] is not None:
            oid = entry["headCommit"]["oid"]
            if oid in by_head:
                raise Refused("Ambiguous merge queue commit")
            by_head[oid] = entry
    members, visited = [], set()
    while head != base:
        if head in visited or head not in by_head:
            raise Refused("Merge group cannot be mapped to original PRs")
        visited.add(head)
        entry = by_head[head]
        if entry["baseCommit"] is None or entry["pullRequest"] is None:
            raise Refused("Incomplete merge queue entry")
        members.append(snapshot(entry["pullRequest"]))
        head = entry["baseCommit"]["oid"]
    if not members or len({pr["number"] for pr in members}) != len(members):
        raise Refused("Empty or duplicate merge-group membership")
    return list(reversed(members))
