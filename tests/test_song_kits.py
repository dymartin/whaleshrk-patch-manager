from __future__ import annotations

from pathlib import Path

import pytest

from rig.song.kits import KitsError, parse_kits


def write_kits(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "kits.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_is_an_empty_config(tmp_path: Path):
    config = parse_kits(tmp_path / "kits.yaml")
    assert config.aliases == {}


def test_parses_alias_to_kit_number(tmp_path: Path):
    path = write_kits(tmp_path, "warehouse: 1\ntape: 2\n")
    config = parse_kits(path)
    assert config.aliases == {"warehouse": 1, "tape": 2}


def test_more_than_24_aliases_is_a_hard_error(tmp_path: Path):
    text = "\n".join(f"kit{i}: {i}" for i in range(1, 26))
    path = write_kits(tmp_path, text)
    with pytest.raises(KitsError, match="24"):
        parse_kits(path)


def test_duplicate_kit_number_is_a_hard_error(tmp_path: Path):
    path = write_kits(tmp_path, "warehouse: 1\ntape: 1\n")
    with pytest.raises(KitsError, match="kit-1"):
        parse_kits(path)


def test_symlinked_kit_directory_is_a_hard_error(tmp_path: Path):
    path = write_kits(tmp_path, "warehouse: 1\n")
    media_root = tmp_path / "media"
    kits_dir = media_root / "kits"
    kits_dir.mkdir(parents=True)
    real_dir = tmp_path / "elsewhere"
    real_dir.mkdir()
    try:
        (kits_dir / "warehouse").symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires elevated privileges on this system")
    with pytest.raises(KitsError, match="symlink"):
        parse_kits(path, media_root=media_root)
