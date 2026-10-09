"""Bounded GitHub.com JSON transport; credentials never leave this origin."""
import json
import http.client
import signal
from contextlib import contextmanager
import re
import socket
import time
import urllib.error
import urllib.request
from . import Refused


class APIError(Refused):
    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


class Transport:
    def __init__(self, token, *, budget=600, timeout=20, opener=None, clock=time.monotonic, sleep=time.sleep):
        if not token or any(c.isspace() for c in token):
            raise Refused("GH_TOKEN must contain a GitHub Actions token")
        self.token, self.timeout = token, timeout
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + budget
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def sanitize(self, value):
        return re.sub(r"[\x00-\x1f\x7f]", " ", str(value).replace(self.token, "[redacted]"))[:500]

    def request(self, path, payload=None, method=None):
        if (path.startswith(("/", "http")) or "\\" in path or any(ord(c) < 32 for c in path) or
            any(segment in (".", "..") for segment in path.split("?")[0].split("/"))):
            raise APIError("Invalid API path")
        method = method or ("POST" if payload is not None else "GET")
        retryable = method == "GET" or (path == "graphql" and method == "POST" and
            isinstance(payload, dict) and str(payload.get("query", "")).lstrip().startswith("query"))
        for attempt in range(4):
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                raise APIError("GitHub API execution budget exhausted")
            request = urllib.request.Request("https://api.github.com/" + path,
                data=json.dumps(payload).encode() if payload is not None else None,
                method=method, headers={"Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "paintedwolf-dco-checker"})
            delay = min(2 ** attempt, 8)
            request_end = self.clock() + min(self.timeout, remaining)
            try:
                with request_deadline(min(self.timeout, remaining)):
                    with self.opener.open(request, timeout=min(self.timeout, remaining)) as response:
                        raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise APIError("GitHub response exceeds supported size", ambiguous=not retryable)
                result = json.loads(raw)
                if not isinstance(result, (dict, list)):
                    raise APIError("GitHub returned an unexpected JSON shape", ambiguous=not retryable)
                if isinstance(result, dict) and result.get("errors"):
                    raise APIError("GraphQL rejected evidence: " + self.sanitize(result["errors"]))
                return result
            except urllib.error.HTTPError as error:
                try:
                    body_budget = request_end - self.clock()
                    if body_budget <= 0:
                        body = "error response body unavailable (request deadline)"
                    else:
                        with request_deadline(body_budget):
                            body = error.read(4096).decode("utf-8", "replace")
                except (TimeoutError, OSError, http.client.HTTPException):
                    body = "error response body unavailable (transport deadline)"
                finally:
                    error.close()
                request_id = self.sanitize(error.headers.get("X-GitHub-Request-Id", "unknown"))
                message = f"{method} {path.split('?')[0]}: HTTP {error.code}; request {request_id}; {self.sanitize(body)}"
                transient = error.code in (429, 500, 502, 503, 504) or (error.code == 403 and
                    (error.headers.get("X-RateLimit-Remaining") == "0" or error.headers.get("Retry-After")))
                try:
                    delay = max(delay, float(error.headers.get("Retry-After", "0")))
                    if error.headers.get("X-RateLimit-Remaining") == "0":
                        delay = max(delay, float(error.headers.get("X-RateLimit-Reset", "0")) - time.time())
                except ValueError:
                    pass
                if not retryable or not transient or attempt == 3:
                    raise APIError(message, ambiguous=method not in ("GET", "HEAD") and error.code >= 500) from None
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError, http.client.HTTPException) as error:
                message = f"{method} {path.split('?')[0]}: transport unavailable: {self.sanitize(error)}"
                if not retryable or attempt == 3:
                    raise APIError(message, ambiguous=method not in ("GET", "HEAD")) from None
            except (ValueError, UnicodeError) as error:
                raise APIError("GitHub returned malformed JSON: " + self.sanitize(error), ambiguous=not retryable) from None
            if delay >= self.deadline - self.clock():
                raise APIError("GitHub retry exceeds remaining execution budget")
            self.sleep(delay)
        raise APIError("GitHub retry limit exhausted")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        raise APIError("GitHub API redirect refused")


@contextmanager
def request_deadline(seconds):
    """Wall deadline also bounds slow-drip headers/bodies on supported Linux runners."""
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise TimeoutError("request wall deadline exceeded")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
