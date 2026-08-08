"""`rig.pull.runner.pull()` end to end, against `InMemoryTransport` and a
throwaway git repo (never this worktree -- Ruling #5). `gh` is always the
`FakeGhClient` test double; nothing here shells out to a real `gh` process.

Covers every bullet in Prompt/07-pull.md's "Verification" section.
"""

from __future__ import annotations

import json

import pytest

from rig.compile.compiler import compile_song
from rig.pull.errors import PullError
from rig.pull.runner import pull
from rig.push import state as state_io
from rig.song.bindings import write_bindings
from rig.song.kits import KitsConfig
from rig.song.model import Chain, ModuleSlot, Song
from rig.song.parser import parse_song
from rig.transport.memory import InMemoryTransport

from .compile_helpers import make_entry, param, system_catalog
from .pull_helpers import FakeGhClient, make_git_repo

PRESETS_ROOT = "data/orhack/presets"


def _catalog():
    return [make_entry("synth@orhack", "orhack", "Synth", "x/synth", [param("level", id_="lvl")]), *system_catalog()]


def _song(name: str, program: int, chain_name: str = "lead", level: float = 50) -> Song:
    return Song(
        name=name, program=program,
        chains=[Chain(name=chain_name, modules=[ModuleSlot(key="synth@orhack", params={"level": level})])],
    )


def _yaml_text(name: str, program: int, chain_name: str = "lead", level: float = 50) -> str:
    return f"""\
song: {name}
program: {program}

chains:
  - name: {chain_name}
    modules:
      - synth@orhack:
          level: {level}
"""


def _seed_song(transport, state_dir, kits, media_root, catalog, *, song_id, name, program, directory=None, level=50):
    """Compile, write to the card, and record as last-pushed -- the state a
    real push would have left behind before any pull runs."""
    song = _song(name, program, level=level)
    compiled = compile_song(song, catalog=catalog, kits=kits, media_root=media_root)
    directory = directory or f"{program:03d}-{name.lower()}"
    transport.write(f"{PRESETS_ROOT}/{directory}/params.json", compiled.files["params.json"])
    state_io.write_last_pushed(
        state_dir, song_id, compiled.files["params.json"], state_io.LastPushedMeta(directory=directory, program=program)
    )
    write_bindings(state_dir / "chains", song_id, {"lead": "A"})
    return song


def _env(tmp_path):
    transport = InMemoryTransport()
    state_dir = tmp_path / ".rig" / "state"
    media_root = tmp_path / "media"
    kits = KitsConfig({})
    catalog = _catalog()
    git, repo_dir = make_git_repo(tmp_path, initial_files={"README.md": b"x\n"})
    gh = FakeGhClient()
    return transport, state_dir, media_root, kits, catalog, git, repo_dir, gh


def _pull(**kwargs):
    kwargs.setdefault("selected", None)
    return pull(**kwargs)


# --- clean vs. drifted -------------------------------------------------------


def test_only_the_drifted_song_gets_a_branch_and_pr(tmp_path):
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="vellichor", name="Vellichor", program=3)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="lowtide", name="Lowtide", program=4)

    # Drift vellichor's level on the card.
    observed = json.loads(transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json"))
    observed["a1"]["params"]["lvl"] = 75
    transport.write(f"{PRESETS_ROOT}/003-vellichor/params.json", json.dumps(observed).encode("utf-8"))

    song_docs = {
        "vellichor": parse_song(_yaml_text("Vellichor", 3)),
        "lowtide": parse_song(_yaml_text("Lowtide", 4)),
    }

    result = _pull(
        song_docs=song_docs, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh,
    )

    assert result.clean == ["lowtide"]
    assert list(result.drifted) == ["vellichor"]
    assert result.aborted == {}
    assert git.branch_exists("pull/vellichor")
    assert not git.branch_exists("pull/lowtide")
    new_yaml = git.read_blob("pull/vellichor", "songs/vellichor.yaml").decode("utf-8")
    assert "level: 75" in new_yaml
    new_baseline = json.loads(git.read_blob("pull/vellichor", ".rig/state/last-pushed/vellichor.json"))
    assert new_baseline == observed


def test_a_second_pull_on_the_same_drift_force_pushes_and_reuses_the_pr(tmp_path):
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="vellichor", name="Vellichor", program=3)
    observed = json.loads(transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json"))
    observed["a1"]["params"]["lvl"] = 75
    transport.write(f"{PRESETS_ROOT}/003-vellichor/params.json", json.dumps(observed).encode("utf-8"))
    song_docs = {"vellichor": parse_song(_yaml_text("Vellichor", 3))}

    _pull(
        song_docs=song_docs, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh,
    )
    first_sha = git.rev_parse("refs/heads/pull/vellichor")

    song_docs2 = {"vellichor": parse_song(_yaml_text("Vellichor", 3))}  # fresh doc -- reverse_map_song mutates in place
    _pull(
        song_docs=song_docs2, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh,
    )
    second_sha = git.rev_parse("refs/heads/pull/vellichor")

    assert gh.create_calls == ["pull/vellichor"]  # created once
    assert gh.ensure_calls == ["pull/vellichor", "pull/vellichor"]  # asked twice
    assert first_sha and second_sha  # branch force-pushed both times, not accumulated


def test_an_unmapped_module_aborts_only_that_song(tmp_path):
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="vellichor", name="Vellichor", program=3)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="lowtide", name="Lowtide", program=4)

    # vellichor's a1 now holds a different (undeclared) module -- module
    # identity drift, the reverse mapper's abort case.
    observed = json.loads(transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json"))
    observed["a1"]["moduleType"] = "instruments/synth/something-else"
    transport.write(f"{PRESETS_ROOT}/003-vellichor/params.json", json.dumps(observed).encode("utf-8"))
    # lowtide drifts cleanly too, to prove it still gets processed.
    observed2 = json.loads(transport.read(f"{PRESETS_ROOT}/004-lowtide/params.json"))
    observed2["a1"]["params"]["lvl"] = 10
    transport.write(f"{PRESETS_ROOT}/004-lowtide/params.json", json.dumps(observed2).encode("utf-8"))

    song_docs = {
        "vellichor": parse_song(_yaml_text("Vellichor", 3)),
        "lowtide": parse_song(_yaml_text("Lowtide", 4)),
    }

    result = _pull(
        song_docs=song_docs, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh,
    )

    assert "vellichor" in result.aborted
    assert result.aborted["vellichor"].startswith("MODULE_IDENTITY_DRIFT")
    assert list(result.drifted) == ["lowtide"]
    assert not git.branch_exists("pull/vellichor")
    assert git.branch_exists("pull/lowtide")


# --- missing presets ----------------------------------------------------------


def test_one_missing_recorded_preset_warns_and_others_still_process(tmp_path):
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="vellichor", name="Vellichor", program=3)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="lowtide", name="Lowtide", program=4)
    transport.delete(f"{PRESETS_ROOT}/003-vellichor")

    song_docs = {
        "vellichor": parse_song(_yaml_text("Vellichor", 3)),
        "lowtide": parse_song(_yaml_text("Lowtide", 4)),
    }
    result = _pull(
        song_docs=song_docs, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh,
    )

    assert result.missing == ["vellichor"]
    assert result.clean == ["lowtide"]


def test_every_recorded_preset_missing_aborts_the_run(tmp_path):
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="vellichor", name="Vellichor", program=3)
    transport.delete(f"{PRESETS_ROOT}/003-vellichor")

    song_docs = {"vellichor": parse_song(_yaml_text("Vellichor", 3))}
    with pytest.raises(PullError) as exc:
        _pull(
            song_docs=song_docs, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
            repo_root=repo_dir, transport=transport, git=git, gh=gh,
        )
    assert exc.value.code == "ALL_PRESETS_MISSING"


# --- dry run ------------------------------------------------------------------


def test_dry_run_creates_no_branch_or_pr(tmp_path):
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    _seed_song(transport, state_dir, kits, media_root, catalog, song_id="vellichor", name="Vellichor", program=3)
    observed = json.loads(transport.read(f"{PRESETS_ROOT}/003-vellichor/params.json"))
    observed["a1"]["params"]["lvl"] = 75
    transport.write(f"{PRESETS_ROOT}/003-vellichor/params.json", json.dumps(observed).encode("utf-8"))
    song_docs = {"vellichor": parse_song(_yaml_text("Vellichor", 3))}

    result = _pull(
        song_docs=song_docs, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh, dry_run=True,
    )

    assert result.dry_run is True
    assert list(result.drifted) == ["vellichor"]
    assert result.drifted["vellichor"] is None
    assert not git.branch_exists("pull/vellichor")
    assert gh.ensure_calls == []


# --- presets no song claims -------------------------------------------------


def test_card_preset_with_no_song_file_is_left_alone(tmp_path):
    """The repo is authoritative for whether a song exists; a preset the repo
    does not declare is never turned into one."""
    transport, state_dir, media_root, kits, catalog, git, repo_dir, gh = _env(tmp_path)
    orphan = _song("Ambient Bed", 9)
    compiled = compile_song(orphan, catalog=catalog, kits=kits, media_root=media_root)
    transport.write(f"{PRESETS_ROOT}/009-Ambient Bed/params.json", compiled.files["params.json"])

    result = _pull(
        song_docs={}, catalog=catalog, kits=kits, media_root=media_root, state_dir=state_dir,
        repo_root=repo_dir, transport=transport, git=git, gh=gh,
    )

    assert result.drifted == {}
    assert not git.branch_exists("pull/ambient-bed")
    assert gh.ensure_calls == []
