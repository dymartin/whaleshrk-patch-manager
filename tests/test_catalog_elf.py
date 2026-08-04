"""ELF32 ABI check -- docs/catalog.md "ELF ABI check".

The real fixture trims every bundled external to 64 bytes (controller note
3), which covers e_ident/e_machine/e_flags but never the `.dynamic` section
DT_NEEDED lives in. Every scenario here is a synthetic ELF built offline
with `struct`, exercising what the frozen fixture structurally cannot.
"""

from __future__ import annotations

import struct

import pytest

from rig.catalog.elf import (
    EABI_VERSION_5,
    EF_ARM_ABI_FLOAT_HARD,
    ELFCLASS32,
    ELFDATA2LSB,
    EM_ARM,
    ElfError,
    check_abi,
    find_dt_needed,
    is_known_good_dependency,
    parse_elf_header,
)


def _elf32_header(
    *,
    ei_class: int = ELFCLASS32,
    ei_data: int = ELFDATA2LSB,
    e_machine: int = EM_ARM,
    e_flags: int = (EABI_VERSION_5 << 24) | EF_ARM_ABI_FLOAT_HARD,
    e_phoff: int = 0,
    e_phentsize: int = 0,
    e_phnum: int = 0,
) -> bytearray:
    header = bytearray(52)
    header[0:4] = b"\x7fELF"
    header[4] = ei_class
    header[5] = ei_data
    header[6] = 1  # EI_VERSION
    endian = "<" if ei_data == ELFDATA2LSB else ">"
    struct.pack_into(endian + "H", header, 16, 2)  # e_type: ET_DYN
    struct.pack_into(endian + "H", header, 18, e_machine)
    struct.pack_into(endian + "I", header, 20, 1)  # e_version
    struct.pack_into(endian + "I", header, 24, 0)  # e_entry
    struct.pack_into(endian + "I", header, 28, e_phoff)
    struct.pack_into(endian + "I", header, 32, 0)  # e_shoff
    struct.pack_into(endian + "I", header, 36, e_flags)
    struct.pack_into(endian + "H", header, 40, 52)  # e_ehsize
    struct.pack_into(endian + "H", header, 42, e_phentsize)
    struct.pack_into(endian + "H", header, 44, e_phnum)
    return header


# --- parse_elf_header --------------------------------------------------


def test_parse_valid_arm_header():
    header = parse_elf_header(bytes(_elf32_header()))
    assert header.e_machine == EM_ARM
    assert header.ei_class == ELFCLASS32
    assert header.ei_data == ELFDATA2LSB
    assert header.eabi_version == EABI_VERSION_5
    assert header.is_hard_float


def test_parse_rejects_too_short_data_cleanly():
    with pytest.raises(ElfError):
        parse_elf_header(b"\x7fELF\x01\x01")  # 6 bytes: magic + class + data only


def test_parse_rejects_bad_magic_cleanly():
    with pytest.raises(ElfError):
        parse_elf_header(b"not an elf file at all, 52+ bytes of junk data......")


def test_parse_big_endian_header():
    header = parse_elf_header(bytes(_elf32_header(ei_data=2, e_machine=EM_ARM)))
    assert header.e_machine == EM_ARM


# --- check_abi -----------------------------------------------------------


def test_check_abi_accepts_a_genuine_arm_hardfloat_binary():
    header = parse_elf_header(bytes(_elf32_header()))
    assert check_abi(header) == []


def test_check_abi_rejects_x86():
    # e_machine=0x03 (EM_386) is every real wrong-arch hit measured in the
    # fixture (tb_peakcomp~/ds_peakcomp~) -- see docs/catalog.md.
    header = parse_elf_header(bytes(_elf32_header(e_machine=0x03, e_flags=0)))
    problems = check_abi(header)
    assert any("EM_ARM" in p for p in problems)


def test_check_abi_rejects_elf64():
    header = parse_elf_header(bytes(_elf32_header(ei_class=2)))
    problems = check_abi(header)
    assert any("ELF32" in p for p in problems)


def test_check_abi_rejects_soft_float():
    header = parse_elf_header(bytes(_elf32_header(e_flags=EABI_VERSION_5 << 24)))
    problems = check_abi(header)
    assert any("hard-float" in p for p in problems)


def test_check_abi_rejects_big_endian():
    header = parse_elf_header(bytes(_elf32_header(ei_data=2)))
    problems = check_abi(header)
    assert any("little-endian" in p for p in problems)


def test_check_abi_does_not_gate_eabi_version():
    # EABI5 is logged, never gated -- an ARM/ELF32/LE/hard-float binary with
    # a different EABI version must still pass.
    header = parse_elf_header(bytes(_elf32_header(e_flags=(3 << 24) | EF_ARM_ABI_FLOAT_HARD)))
    assert check_abi(header) == []
    assert header.eabi_version == 3


# --- known-good DT_NEEDED set ---------------------------------------------


def test_known_good_rootfs_and_orhack_libs():
    assert is_known_good_dependency("libc.so.6")
    assert is_known_good_dependency("libcjson.so")
    assert is_known_good_dependency("libmec-eigenharp.so")  # wildcard prefix


def test_unknown_dependency_is_not_known_good():
    assert not is_known_good_dependency("libsomerandomthing.so.1")


# --- find_dt_needed (full synthetic binary) -------------------------------


def _synthetic_elf_with_needed(names: list[str]) -> bytes:
    """A full ELF32 binary with a PT_DYNAMIC segment listing DT_NEEDED entries."""
    phdr_off = 52
    phentsize = 32
    dynamic_off = phdr_off + phentsize

    strtab = b"\x00"
    name_offsets = []
    for name in names:
        name_offsets.append(len(strtab))
        strtab += name.encode("ascii") + b"\x00"

    dynamic_entries = [(5, 0)]  # DT_STRTAB, patched below once strtab_off is known
    for off in name_offsets:
        dynamic_entries.append((1, off))  # DT_NEEDED
    dynamic_entries.append((0, 0))  # DT_NULL

    dynamic_size = len(dynamic_entries) * 8
    strtab_off = dynamic_off + dynamic_size
    dynamic_entries[0] = (5, strtab_off)

    header = _elf32_header(e_phoff=phdr_off, e_phentsize=phentsize, e_phnum=1)

    phdr = bytearray(32)
    struct.pack_into("<I", phdr, 0, 2)  # p_type = PT_DYNAMIC
    struct.pack_into("<I", phdr, 4, dynamic_off)  # p_offset
    struct.pack_into("<I", phdr, 16, dynamic_size)  # p_filesz

    dynamic = bytearray()
    for tag, val in dynamic_entries:
        dynamic += struct.pack("<iI", tag, val)

    return bytes(header) + bytes(phdr) + bytes(dynamic) + strtab


def test_find_dt_needed_extracts_library_names():
    data = _synthetic_elf_with_needed(["libfoo.so", "libbar.so.1"])
    needed = find_dt_needed(data)
    assert needed == ["libfoo.so", "libbar.so.1"]


def test_find_dt_needed_returns_none_when_dynamic_section_absent():
    # This is exactly the frozen fixture's shape: a 64-byte header with no
    # program header table at all.
    header = bytes(_elf32_header())
    assert find_dt_needed(header) is None
