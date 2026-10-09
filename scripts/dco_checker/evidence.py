"""Live authority snapshots and immutable, complete commit inventories."""
import re
from . import Refused

PR_FIELDS = "number headRefOid baseRefOid isDraft state"
PAGE = "pageInfo { hasNextPage endCursor } totalCount"
SHA = re.compile(r"^[0-9a-f]{40}$")


def snapshot(value):
    if not isinstance(value, dict):
        raise Refused("Missing pull request snapshot")
    fields = ("number", "headRefOid", "baseRefOid", "isDraft", "state")
    if not all(key in value for key in fields):
        raise Refused("Incomplete pull request snapshot")
    result = {key: value[key] for key in fields}
    if (type(result["number"]) is not int or result["number"] <= 0 or
        not all(isinstance(result[key], str) and SHA.fullmatch(result[key]) for key in ("headRefOid", "baseRefOid")) or
        type(result["isDraft"]) is not bool or result["state"] not in ("OPEN", "CLOSED", "MERGED")):
        raise Refused("Malformed pull request snapshot")
    return result


def validate_connection(connection):
    if (not isinstance(connection, dict) or type(connection.get("totalCount")) is not int or
        connection["totalCount"] < 0 or not isinstance(connection.get("nodes"), list) or
        not isinstance(connection.get("pageInfo"), dict)):
        raise Refused("Malformed paginated inventory")
    page = connection["pageInfo"]
    if (type(page.get("hasNextPage")) is not bool or
        (page.get("endCursor") is not None and not isinstance(page["endCursor"], str))):
        raise Refused("Malformed pagination authority")


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
        # Commit-to-PR associations are incomplete for fork heads. The base
        # repository's complete open PR inventory is the authority for every
        # context that can consume a check attached to this SHA.
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise Refused("Invalid target SHA for open PR inventory")
        found, seen, cursor, total = [], set(), None, None
        while True:
            connection = self.query(
                "pullRequests(first:100,after:$cursor,states:[OPEN],orderBy:{field:CREATED_AT,direction:ASC}){" +
                PAGE + " nodes{" + PR_FIELDS + "}}", cursor=cursor)["pullRequests"]
            validate_connection(connection)
            if total is not None and total != connection["totalCount"]:
                raise Refused("Open PR inventory changed during pagination")
            total = connection["totalCount"]
            for node in connection["nodes"]:
                current = snapshot(node)
                if current["state"] != "OPEN" or current["number"] in seen:
                    raise Refused("Closed or repeated PR in open PR inventory")
                seen.add(current["number"])
                if current["headRefOid"] == sha:
                    found.append(current)
            if len(seen) > total:
                raise Refused("Open PR inventory exceeds declared count")
            cursor = next_page(connection, cursor)
            if cursor is None:
                break
        if len(seen) != total:
            raise Refused("Incomplete open PR inventory")
        return sorted(found, key=lambda pr: pr["number"])

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
            validate_connection(connection)
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
