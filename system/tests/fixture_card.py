"""Loads the frozen fixture card (fixtures/card/) into any Transport.

The fixture is a real, verified ORHACK 0.52b install tree -- provenance
(Patchstorage id, file id, SHA-256) is pinned in docs/platform/README.md.
Every later phase that needs a card without touching hardware loads this
fixture into an InMemoryTransport, or points UsbMassStorage at it directly
once Phase 4 lands.
"""

from __future__ import annotations

from pathlib import Path

from rig.transport.base import Transport

FIXTURE_CARD_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "card"


def load_fixture_card(transport: Transport, root: Path = FIXTURE_CARD_ROOT) -> None:
    """Write every file under `root` into `transport`, at its card-relative path.

    `.gitkeep` markers (used to make otherwise-empty deploy.sh directories
    representable in git) become `mkdir` calls, not files -- a fresh card has
    an empty `recordings/` directory, not one containing a `.gitkeep`.
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.name == ".gitkeep":
            transport.mkdir(str(Path(rel).parent.as_posix()))
            continue
        transport.write(rel, path.read_bytes())

    # deploy.sh copies the package's canonical Init preset onto the card.
    init = root / "Patches" / "0RHACK" / "data" / "presets" / "Init"
    for path in sorted(init.rglob("*")):
        if path.is_file():
            rel = path.relative_to(init).as_posix()
            transport.write(f"data/orhack/presets/Init/{rel}", path.read_bytes())
