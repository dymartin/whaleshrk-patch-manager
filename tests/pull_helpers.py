"""Shared fixtures for `rig.pull` tests.

`make_git_repo` builds a throwaway local repo plus a local bare "origin" --
`git push` to it is plain filesystem I/O (the "file" transport), not a
network socket, so it works under `tests/conftest.py`'s network block and
never touches this worktree (Ruling #5: pull's branch/commit/PR code is only
ever exercised against a temporary repo). `FakeGhClient` stands in for `gh`,
which the pull tests must never shell out to for real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rig.pull.gitio import GitRepo


def make_git_repo(tmp_path: Path, *, initial_files: dict[str, bytes]) -> tuple[GitRepo, Path]:
    """A local repo on branch `main`, with `initial_files` committed and
    pushed to a local bare `origin`."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(origin)], check=True)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "remote", "add", "origin", str(origin)], check=True)

    for rel_path, content in initial_files.items():
        path = repo_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        subprocess.run(["git", "-C", str(repo_dir), "add", rel_path], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "--quiet", "-m", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "push", "--quiet", "origin", "main"], check=True)

    return GitRepo(repo_dir), repo_dir


class FakeGhClient:
    """Records every call so a test can assert reuse-vs-create behaviour
    without a real `gh` process."""

    def __init__(self) -> None:
        self.open_prs: dict[str, str] = {}
        self.ensure_calls: list[str] = []
        self.create_calls: list[str] = []

    def ensure_pr(self, *, branch: str, base: str, title: str, body: str) -> str:
        self.ensure_calls.append(branch)
        if branch in self.open_prs:
            return self.open_prs[branch]
        url = f"https://example.invalid/pull/{len(self.open_prs) + 1}"
        self.open_prs[branch] = url
        self.create_calls.append(branch)
        return url
