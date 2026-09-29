"""Coordinate mapping between CPU/region views and ROM chip files.

Established in docs/initial-survey.md §2 (MAME psikyo4 hgkairak ROM map, images checked against runtime):
- main CPU 0x000000-0x0FFFFF: each dword = 1.u22 word (byte-swapped) + 2.u23 word (byte-swapped)
- gfx1 region 48MB: per 8MB pair k, each dword = kl word + kh word (bytes as stored)
"""
MAIN_SIZE = 0x100000
MAIN_CHIPS = ("1.u22", "2.u23")
GFX_PAIR = 0x800000
GFX_FILES = (("0l.u2", "0h.u11"), ("1l.u3", "1h.u12"), ("2l.u4", "2h.u13"),
             ("3l.u5", "3h.u14"), ("4l.u6", "4h.u15"), ("5l.u7", "5h.u16"))
GFX_SIZE = len(GFX_FILES) * GFX_PAIR


def cpu_image(u22: bytes, u23: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(u22), 2):
        out += bytes((u22[i + 1], u22[i], u23[i + 1], u23[i]))
    return bytes(out)


def main_addr_to_chip(addr: int) -> tuple[str, int]:
    if not 0 <= addr < MAIN_SIZE:
        raise ValueError(f"main address out of range: {addr:#x}")
    chip = MAIN_CHIPS[0] if addr % 4 < 2 else MAIN_CHIPS[1]
    return chip, (addr // 4) * 2 + (1 - addr % 2)


def gfx_offset_to_file(off: int) -> tuple[str, int]:
    if not 0 <= off < GFX_SIZE:
        raise ValueError(f"gfx offset out of range: {off:#x}")
    k, r = divmod(off, GFX_PAIR)
    return GFX_FILES[k][0 if r % 4 < 2 else 1], (r // 4) * 2 + r % 2
