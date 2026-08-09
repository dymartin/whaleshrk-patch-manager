"""`rig.pull.gitio` -- git plumbing and the `gh` seam.

Exercised against a throwaway repo built by `tests/pull_helpers.make_git_repo`,
never this worktree (Ruling #5). `gh` absence is simulated by monkeypatching
`subprocess.run` to raise `FileNotFoundError`, since `gh` actually is
installed on this machine and the test must not depend on that.
"""

from __future__ import annotations

import subprocess

import pytest

from rig.pull.gitio import GhError, GitError, SubprocessGhClient
from tests.pull_helpers import make_git_repo


def test_commit_branch_builds_a_commit_without_touching_the_checkout(tmp_path):
    git, repo_dir = make_git_repo(tmp_path, initial_files={"songs/a.yaml": b"song: A\n"})
    before = (repo_dir / "songs" / "a.yaml").read_bytes()

    sha = git.commit_branch(
        base_ref="main", branch="pull/a", files={"songs/a.yaml": b"song: A2\n"}, message="edit a"
    )

    assert sha
    assert (repo_dir / "songs" / "a.yaml").read_bytes() == before  # checkout untouched
    assert git.read_blob("pull/a", "songs/a.yaml") == b"song: A2\n"
    # Untouched files carry over unchanged from the base tree.
    assert git.branch_exists("pull/a")
    assert not git.branch_exists("pull/does-not-exist")


def test_commit_branch_can_delete_a_path(tmp_path):
    git, repo_dir = make_git_repo(
        tmp_path, initial_files={"songs/a.yaml": b"song: A\n", "keep.txt": b"keep\n"}
    )

    git.commit_branch(base_ref="main", branch="pull/a", files={"songs/a.yaml": None}, message="remove a")

    with pytest.raises(GitError):
        git.read_blob("pull/a", "songs/a.yaml")
    assert git.read_blob("pull/a", "keep.txt") == b"keep\n"


def test_commit_branch_reset_moves_the_branch_pointer(tmp_path):
    git, repo_dir = make_git_repo(tmp_path, initial_files={"songs/a.yaml": b"song: A\n"})

    first = git.commit_branch(base_ref="main", branch="pull/a", files={"songs/a.yaml": b"v1\n"}, message="v1")
    second = git.commit_branch(base_ref="main", branch="pull/a", files={"songs/a.yaml": b"v2\n"}, message="v2")

    assert first != second
    assert git.rev_parse("refs/heads/pull/a") == second
    assert git.read_blob("pull/a", "songs/a.yaml") == b"v2\n"


def test_push_branch_publishes_to_the_local_origin(tmp_path):
    git, repo_dir = make_git_repo(tmp_path, initial_files={"songs/a.yaml": b"song: A\n"})
    git.commit_branch(base_ref="main", branch="pull/a", files={"songs/a.yaml": b"v1\n"}, message="v1")

    git.push_branch("pull/a")

    origin = tmp_path / "origin.git"
    out = subprocess.run(
        ["git", "--git-dir", str(origin), "show", "pull/a:songs/a.yaml"], capture_output=True, check=True
    )
    assert out.stdout == b"v1\n"


def test_subprocess_gh_client_reports_a_clear_error_when_gh_is_missing(tmp_path, monkeypatch):
    def _raise_missing(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", _raise_missing)
    client = SubprocessGhClient(tmp_path)

    with pytest.raises(GhError, match="not installed"):
        client.ensure_pr(branch="pull/a", base="main", title="t", body="b")
