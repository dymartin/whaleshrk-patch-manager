"""ELF32 ABI check for bundled externals.

Reads the header directly with `struct` -- no dependency on an ELF library.
Criteria and their evidentiary status (measured against the real 145-candidate
fixture) are in docs/catalog.md "ELF ABI check". `DT_NEEDED` resolution needs
bytes far past the 64-byte header (`.dynamic`/`.dynstr`), which the frozen
fixture never carries -- see docs/catalog.md "Warn, do not reject". It is
warn-only and never gates a reject.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

ELF_MAGIC = b"\x7fELF"
ELF32_HEADER_SIZE = 52  # e_shstrndx, the last ELF32 header field, ends at byte 52.

EM_ARM = 0x28
ELFCLASS32 = 1
ELFDATA2LSB = 1
EF_ARM_ABI_FLOAT_HARD = 0x400
EABI_VERSION_5 = 5


class ElfError(ValueError):
    """Bytes cannot be read as an ELF header -- too short or bad magic.

    Raised rather than reading past the end or guessing at missing fields.
    """


@dataclass(frozen=True)
class ElfHeader:
    ei_class: int
    ei_data: int
    e_machine: int
    e_flags: int

    @property
    def eabi_version(self) -> int:
        return self.e_flags >> 24

    @property
    def is_hard_float(self) -> bool:
        return bool(self.e_flags & EF_ARM_ABI_FLOAT_HARD)


def parse_elf_header(data: bytes) -> ElfHeader:
    """Parse just the fields the ABI check needs, from the first 64 bytes.

    Endianness for `e_machine`/`e_flags` is read using `e_ident[EI_DATA]`,
    itself endianness-independent (a single byte).
    """
    if len(data) < 6:
        raise ElfError(f"too short to carry e_ident: {len(data)} bytes")
    if data[:4] != ELF_MAGIC:
        raise ElfError("not an ELF file: bad magic")
    if len(data) < ELF32_HEADER_SIZE:
        raise ElfError(
            f"too short to carry a full ELF32 header: {len(data)} of "
            f"{ELF32_HEADER_SIZE} bytes"
        )
    ei_class = data[4]
    ei_data = data[5]
    endian = "<" if ei_data == ELFDATA2LSB else ">"
    (e_machine,) = struct.unpack_from(endian + "H", data, 18)
    (e_flags,) = struct.unpack_from(endian + "I", data, 36)
    return ElfHeader(ei_class=ei_class, ei_data=ei_data, e_machine=e_machine, e_flags=e_flags)


def check_abi(header: ElfHeader) -> list[str]:
    """Enforced ABI criteria. Empty list means the external passes.

    EABI version is logged by the caller, never checked here -- measured
    uniformly version 5 across the sample, but not gated (docs/catalog.md).
    """
    problems = []
    if header.e_machine != EM_ARM:
        problems.append(f"not EM_ARM: e_machine=0x{header.e_machine:x}")
    if header.ei_class != ELFCLASS32:
        problems.append(f"not ELF32: ei_class={header.ei_class}")
    if header.ei_data != ELFDATA2LSB:
        problems.append(f"not little-endian: ei_data={header.ei_data}")
    if not header.is_hard_float:
        problems.append(f"not hard-float: e_flags=0x{header.e_flags:x}")
    return problems


# Known-good DT_NEEDED set, derived from ORHACK 0.52b's own 64 ELF binaries --
# see docs/catalog.md "Warn, do not reject" for the measurement.
KNOWN_GOOD_ROOTFS_LIBS = {
    "libc.so.6",
    "libm.so.6",
    "libstdc++.so.6",
    "libgcc_s.so.1",
    "libatomic.so.1",
    "libpthread.so.0",
    "libdl.so.2",
    "libasound.so.2",
    "libusb-1.0.so.0",
    "libcairo.so.2",
}
KNOWN_GOOD_ORHACK_LIBS = {
    "libcjson.so",
    "liboscpack.so",
    "libpicodecoder.so",
    "libeigenapi.so",
    "libsplite.so",
    "libportaudio.so",
    "librtmidi.so",
}
_KNOWN_GOOD_ORHACK_PREFIX = "libmec-"


def is_known_good_dependency(name: str) -> bool:
    if name in KNOWN_GOOD_ROOTFS_LIBS or name in KNOWN_GOOD_ORHACK_LIBS:
        return True
    return name.startswith(_KNOWN_GOOD_ORHACK_PREFIX) and name.endswith(".so")


# --- Full-binary DT_NEEDED extraction (warn-only, best-effort) -------------
#
# Needs the program header table and the .dynamic section, both well past the
# 64-byte header the frozen fixture carries. Only reachable with a full
# binary (the live ingest path, or a synthetic test ELF) -- never exercised
# against the frozen fixture, which cannot carry this data (see module
# docstring).

PT_DYNAMIC = 2
DT_NEEDED = 1
DT_STRTAB = 5
DT_NULL = 0


def find_dt_needed(data: bytes) -> list[str] | None:
    """Best-effort DT_NEEDED extraction from a full ELF32 binary.

    Returns None if the program header table or .dynamic section is not
    present in `data` -- not an error, just "cannot determine", which the
    caller must treat as "nothing to warn about" rather than a failure.
    """
    header = parse_elf_header(data)
    if len(data) < 32:
        return None
    endian = "<" if header.ei_data == ELFDATA2LSB else ">"
    (e_phoff,) = struct.unpack_from(endian + "I", data, 28)
    (e_phentsize,) = struct.unpack_from(endian + "H", data, 42)
    (e_phnum,) = struct.unpack_from(endian + "H", data, 44)
    if e_phoff == 0 or e_phentsize == 0:
        return None

    dynamic_off = dynamic_size = None
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + 16 > len(data):
            return None
        (p_type,) = struct.unpack_from(endian + "I", data, off)
        if p_type == PT_DYNAMIC:
            (p_offset,) = struct.unpack_from(endian + "I", data, off + 4)
            (p_filesz,) = struct.unpack_from(endian + "I", data, off + 16)
            dynamic_off, dynamic_size = p_offset, p_filesz
            break
    if dynamic_off is None:
        return None
    if dynamic_off + dynamic_size > len(data):
        return None

    # Walk .dynamic entries (tag, value pairs of 4 bytes each) to find
    # DT_STRTAB and every DT_NEEDED offset into it.
    strtab_off = None
    needed_str_offsets = []
    pos = dynamic_off
    end = dynamic_off + dynamic_size
    while pos + 8 <= end:
        tag, val = struct.unpack_from(endian + "iI", data, pos)
        if tag == DT_NULL:
            break
        if tag == DT_STRTAB:
            strtab_off = val
        elif tag == DT_NEEDED:
            needed_str_offsets.append(val)
        pos += 8

    if strtab_off is None or strtab_off >= len(data):
        return None

    names = []
    for str_off in needed_str_offsets:
        start = strtab_off + str_off
        if start >= len(data):
            continue
        end_off = data.find(b"\x00", start)
        if end_off == -1:
            continue
        names.append(data[start:end_off].decode("utf-8", errors="replace"))
    return names
