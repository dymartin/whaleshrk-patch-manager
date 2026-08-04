"""Shared helpers for building synthetic zip archives in catalog tests.

Every candidate archive fixture here is built offline with `zipfile` -- no
network, no real Patchstorage upload. Kept tiny and obviously synthetic per
the controller's guidance for archive-safety coverage the real fixture
cannot provide.
"""

from __future__ import annotations

import io
import zipfile

_S_IFLNK = 0o120000


def build_zip(files: dict[str, bytes], symlinks: dict[str, str] | None = None) -> bytes:
    """Build zip bytes from `{name: content}`, plus optional `{name: link_target}`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (_S_IFLNK | 0o777) << 16
            zf.writestr(info, target.encode("ascii"))
    return buf.getvalue()


def elf32_header(
    *,
    ei_class: int = 1,
    ei_data: int = 1,
    e_machine: int = 0x28,
    e_flags: int = (5 << 24) | 0x400,
) -> bytes:
    """A minimal, valid-shaped 64-byte ELF32 header for use as a bundled external."""
    import struct

    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4] = ei_class
    header[5] = ei_data
    header[6] = 1
    endian = "<" if ei_data == 1 else ">"
    struct.pack_into(endian + "H", header, 18, e_machine)
    struct.pack_into(endian + "I", header, 36, e_flags)
    return bytes(header)


MODULE_JSON = b'{"display": "Test Module", "parameters": []}'
MODULE_PD = b"#N canvas 0 0 100 100 10;\n#X obj 10 10 osc~ 440;\n"
