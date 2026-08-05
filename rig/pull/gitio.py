"""Git and `gh` plumbing: the seam pull's branch/commit/PR step runs through.

Pure plumbing, no working-tree checkout. `GitRepo.commit_branch` builds a
commit from a base ref's tree plus explicit file overrides via a scratch
index (`GIT_INDEX_FILE`), so a live pull run never disturbs whatever branch
the caller's own checkout happens to have out -- it only ever writes objects
and moves a ref. That is what makes it safe to run against a real repo
without a `git checkout` in sight; tests still always point it at a
throwaway `git init` repo, never this worktree (Ruling #5).

`gh` is a runtime prerequisite pull cannot function without
(docs/workflows/pull.md: "not installed on the development machine as of
2026-08-02") -- `SubprocessGhClient` shells out to it and turns a missing
binary into `GhError` with a clear message rather than a crash. Every
behavioural pull test injects `GhClient` fake instead; nothing here is
exercised against a real `gh` process in the test suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Protocol


class GitError(RuntimeError):
    """A `git` plumbing command failed, or `git` itself is not installed."""


class GhError(RuntimeError):
    """A `gh` command failed, or `gh` itself is not installed."""


class GitRepo:
    """Plumbing over one git repository, addressed by its working directory.

    Every history-changing method builds the new commit off a base ref's
    tree and a scratch index rather than the repo's real index -- nothing
    here runs `git checkout`, so the repo's actual working tree and staged
    changes are untouched no matter what branch it has checked out.
    """

    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)

    def _run(self, *args: str, env: Optional[dict] = None, input_bytes: Optional[bytes] = None) -> bytes:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_dir), *args],
                capture_output=True,
                input=input_bytes,
                env=env,
            )
        except FileNotFoundError as exc:
            raise GitError("`git` is not installed") from exc
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout

    def rev_parse(self, ref: str) -> str:
        return self._run("rev-parse", ref).decode().strip()

    def branch_exists(self, branch: str) -> bool:
        try:
            self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
            return True
        except GitError:
            return False

    def read_blob(self, ref: str, path: str) -> bytes:
        """`git show <ref>:<path>` -- for callers (tests, mainly) that want
        to confirm what a commit actually contains without a checkout."""
        return self._run("show", f"{ref}:{path}")

    def commit_branch(self, *, base_ref: str, branch: str, files: dict[str, Optional[bytes]], message: str) -> str:
        """Build one commit on top of `base_ref`'s tree with `files`
        overridden (`None` deletes a path) and force-point
        `refs/heads/<branch>` at it. Returns the new commit sha.

        Local only -- publish with `push_branch`. Using a scratch index
        (`GIT_INDEX_FILE` pointed at a throwaway temp file) rather than the
        repo's default index is what lets this run with any branch checked
        out, including one with uncommitted changes: `read-tree`/
        `update-index`/`write-tree` below only ever touch the scratch file.
        """
        base_commit = self.rev_parse(base_ref)
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index"
            env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
            self._run("read-tree", base_commit, env=env)
            for path, content in files.items():
                if content is None:
                    self._run("update-index", "--force-remove", path, env=env)
                    continue
                blob_sha = self._run("hash-object", "-w", "--stdin", env=env, input_bytes=content).decode().strip()
                self._run("update-index", "--add", "--cacheinfo", f"100644,{blob_sha},{path}", env=env)
            tree_sha = self._run("write-tree", env=env).decode().strip()
            commit_sha = (
                self._run("commit-tree", tree_sha, "-p", base_commit, "-m", message, env=env).decode().strip()
            )
        self._run("update-ref", f"refs/heads/{branch}", commit_sha)
        return commit_sha

    def push_branch(self, branch: str, remote: str = "origin") -> None:
        self._run("push", "--force", remote, f"refs/heads/{branch}:refs/heads/{branch}")


class GhClient(Protocol):
    """One pull request per branch -- the only thing pull needs from `gh`."""

    def ensure_pr(self, *, branch: str, base: str, title: str, body: str) -> str:
        """Return the PR's URL. Reuses an already-open PR for `branch` --
        force-pushing the branch already carries the new diff into it -- and
        opens one via `gh pr create` only when none is open
        (docs/workflows/pull.md "Branches and PRs")."""
        ...


class SubprocessGhClient:
    """Real `gh` CLI, run from `repo_dir`."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(["gh", *args], cwd=self.repo_dir, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise GhError(
                "the `gh` CLI is not installed -- required to open pull requests. "
                "Install it (https://cli.github.com) and retry."
            ) from exc
        if result.returncode != 0:
            raise GhError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout

    def _find_open_pr(self, branch: str) -> Optional[str]:
        out = self._run("pr", "list", "--head", branch, "--state", "open", "--json", "url")
        data = json.loads(out) if out.strip() else []
        return data[0]["url"] if data else None

    def ensure_pr(self, *, branch: str, base: str, title: str, body: str) -> str:
        existing = self._find_open_pr(branch)
        if existing is not None:
            return existing
        out = self._run("pr", "create", "--head", branch, "--base", base, "--title", title, "--body", body)
        return out.strip().splitlines()[-1]
