"""Paged Git history loading for the commit picker."""

import re
from typing import Callable, Dict, List, Optional


COMMIT_SEPARATOR = "\x1f"
COMMIT_PATTERN = re.compile(
    r"^(?P<graph>[ |\\/*]+)?(?P<hash>[0-9a-f]{40})"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<short>[0-9a-f]+)"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<date>[^\x1f]*)"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<author>[^\x1f]*)"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<subject>.*)$"
)


class ProgressiveCommitLoader:
    """Load Git history in pages without retaining Git process state."""

    def __init__(self, git_runner: Callable[..., str], page_size: int = 200) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.git_runner = git_runner
        self.page_size = page_size
        self.reset()

    def reset(self, all_branches: bool = False) -> None:
        self.offset = 0
        self.all_branches = all_branches
        self.exhausted = False

    def load_next(self, all_branches: Optional[bool] = None) -> List[Dict[str, str]]:
        if all_branches is not None and all_branches != self.all_branches:
            self.reset(all_branches)
        if self.exhausted:
            return []

        log_args = ["log"]
        if self.all_branches:
            log_args.extend(["--branches", "--remotes"])
        log_args.extend([
            "--max-count={}".format(self.page_size),
            "--skip={}".format(self.offset),
            "--date=short",
            "--graph",
            "--decorate",
            "--pretty=format:%H" + COMMIT_SEPARATOR + "%h" + COMMIT_SEPARATOR + "%ad" + COMMIT_SEPARATOR + "%an" + COMMIT_SEPARATOR + "%s",
        ])
        raw = self.git_runner(*log_args)
        commits = self._parse(raw)
        self.offset += len(commits)
        self.exhausted = len(commits) < self.page_size
        return commits

    @staticmethod
    def _parse(raw: str) -> List[Dict[str, str]]:
        commits: List[Dict[str, str]] = []
        for line in raw.splitlines():
            match = COMMIT_PATTERN.match(line)
            if match:
                commits.append(match.groupdict())
        return commits
