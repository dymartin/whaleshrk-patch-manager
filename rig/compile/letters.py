"""Chain letter assignment: which chain compiles to A/B/C/D.

Pure function, no I/O -- callers pass in the recorded bindings
(`rig.song.bindings`) and get an assignment back. Capacity is asymmetric
(A=3, B=4, C=3, D=4), so assignment is capacity-aware, not declaration order
(`docs/schema.md` "Chains", `docs/decisions.md` #22, #30).

Two passes, both in declaration order, after recorded bindings leave the
pool:

1. Unbound chains needing 4 slots claim B, then D.
2. Every remaining unbound chain claims the next free letter in the fixed
   order A, C, B, D.

The rules are total: every capacity-valid input has exactly one assignment,
and a cold rebuild from an all-bound input reproduces the recorded bindings
exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

CAPACITY = {"A": 3, "B": 4, "C": 3, "D": 4}
PASS2_ORDER = ("A", "C", "B", "D")
FOUR_SLOT_LETTERS = ("B", "D")
MAX_FOUR_SLOT_CHAINS = len(FOUR_SLOT_LETTERS)


class LetterAssignmentError(ValueError):
    """A chain layout has no valid letter assignment, or a binding is invalid.

    `code` identifies which rule failed, for callers that fold this into a
    song's list of validation findings.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ChainSlots:
    """The one thing letter assignment cares about a chain: its name and how
    many module slots it needs."""

    name: str
    slot_count: int


def assign_letters(chains: list[ChainSlots], bindings: dict[str, str]) -> dict[str, str]:
    """Return chain name -> letter.

    `bindings` is name -> letter for chains a previous push recorded; those
    win and leave the pool before either pass runs. Callers are expected to
    have already rejected a chain needing more than 4 slots and more than 4
    chains total -- those are song-level capacity errors with their own
    messages, not letter-assignment errors.
    """
    pool = ["A", "B", "C", "D"]
    result: dict[str, str] = {}
    unbound: list[ChainSlots] = []
    four_slot_bound = 0

    for chain in chains:
        letter = bindings.get(chain.name)
        if letter is None:
            unbound.append(chain)
            continue
        if letter not in pool:
            raise LetterAssignmentError(
                "BOUND_LETTER_TAKEN",
                f"chain {chain.name!r} is bound to letter {letter!r}, already assigned "
                "to another chain",
            )
        if chain.slot_count > CAPACITY[letter]:
            raise LetterAssignmentError(
                "BOUND_CHAIN_OUTGROWN",
                f"chain {chain.name!r} needs {chain.slot_count} slots but is bound to "
                f"letter {letter}, which holds {CAPACITY[letter]}",
            )
        pool.remove(letter)
        result[chain.name] = letter
        # Counted by which letter it occupies, not its own slot_count: nothing
        # requires a bound chain to fill its letter's capacity (it may have
        # shrunk since the push that recorded the binding), but a bound B or D
        # still spends one of the two 4-slot letters either way.
        if letter in FOUR_SLOT_LETTERS:
            four_slot_bound += 1

    needing_four = [c for c in unbound if c.slot_count == 4]
    total_needing_four = four_slot_bound + len(needing_four)
    if total_needing_four > MAX_FOUR_SLOT_CHAINS:
        raise LetterAssignmentError(
            "CHAINS_NEEDING_4_SLOTS_EXCEEDED",
            f"{total_needing_four} chains need 4 slots; only letters "
            f"{', '.join(FOUR_SLOT_LETTERS)} hold that many",
        )

    needing_four_names = {c.name for c in needing_four}
    remaining = [c for c in unbound if c.name not in needing_four_names]
    for chain in needing_four:
        for letter in FOUR_SLOT_LETTERS:
            if letter in pool:
                pool.remove(letter)
                result[chain.name] = letter
                break
        else:  # pragma: no cover -- unreachable: the count check above already
            # rejected total_needing_four > 2, and every bound chain on B/D was
            # counted into that total regardless of its own slot_count, so the
            # two 4-slot letters can never run out here.
            raise LetterAssignmentError(
                "CHAINS_NEEDING_4_SLOTS_EXCEEDED",
                f"chain {chain.name!r} needs 4 slots but no letter is free",
            )

    for chain in remaining:
        for letter in PASS2_ORDER:
            if letter in pool:
                pool.remove(letter)
                result[chain.name] = letter
                break
        else:
            raise LetterAssignmentError(
                "CHAINS_EXCEEDED",
                f"chain {chain.name!r} has no free letter; {len(chains)} chains declared "
                "for 4 letters",
            )

    return result
