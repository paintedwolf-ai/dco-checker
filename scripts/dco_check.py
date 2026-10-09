#!/usr/bin/env python3
"""Trusted-source action entry point; never executes PR contents."""
import json
import os
from pathlib import Path
import sys

from dco_checker import Refused
from dco_checker.engine import Config, run
from dco_checker.evidence import GitHub
from dco_checker.transport import Transport


def main():
    try:
        if sys.version_info < (3, 11):
            raise Refused("DCO checker requires Python 3.11 or newer")
        if os.environ.get("GITHUB_SERVER_URL", "https://github.com") != "https://github.com" or os.environ.get("GITHUB_API_URL", "https://api.github.com") != "https://api.github.com":
            raise Refused("Only GitHub.com is currently supported")
        config = Config(os.environ["DCO_CHECKER_REVISION"], int(os.environ["DCO_RUN_ID"]),
                        int(os.environ["DCO_RUN_ATTEMPT"]), os.environ["DCO_RUN_URL"], os.environ.get("DCO_CI_WORKFLOW", "ci.yml"))
        github = GitHub(os.environ["GITHUB_REPOSITORY"], Transport(os.environ["GH_TOKEN"]))
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        return run(github, os.environ["GITHUB_EVENT_NAME"], event, config)
    except (Refused, KeyError, ValueError, TypeError, OSError) as error:
        message = str(error) if isinstance(error, Refused) else "Invalid action configuration or event: " + type(error).__name__
        print("DCO check failed: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
