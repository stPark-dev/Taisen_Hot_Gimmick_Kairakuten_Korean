"""Dialogue string block: parsing, layout budget, Korean encoding, in-place serialization.

Engine facts (docs/initial-survey.md §3; same string format as the first game): 16-bit codes, FFFE = newline
(x reset, y += line spacing), FFFD = blank cell (draws blank tile, erases previous glyph),
FFFF = end; strings start 4-byte aligned (0000 pad). No auto-wrap or column clipping, so the
window width comes from the source layout (padding).
"""
import struct
from dataclasses import dataclass, field

from .charmap import JP_REVERSE, TOK_BLANK, TOK_END, TOK_NEWLINE

BLOCK_START, BLOCK_END = 0x7881C, 0x7FDE4   # first pointer target .. last string end
POINTER_SCAN_END = BLOCK_START             # pointer table 0x7741C-0x78818 lies before the block


class LayoutError(ValueError):
    pass


@dataclass
class Entry:
    addr: int
    codes: list[int]
    capacity: int          # words available in place, incl. terminator and padding
    refs: list[int] = field(default_factory=list)

    @property
    def line_cells(self) -> list[int]:
        cells = [0]
        for v in self.codes:
            if v == TOK_NEWLINE:
                cells.append(0)
            else:
                cells[-1] += 1
        return cells

    @property
    def width(self) -> int:
        return max(self.line_cells)

    @property
    def rows(self) -> int:
        return len(self.line_cells)

    @property
    def id(self) -> str:
        return f"T{self.addr:06X}"


def parse_strings(blob: bytes, base: int, end: int) -> list[tuple[int, list[int], int]]:
    n = (end - base) // 2
    w = struct.unpack(">%dH" % n, blob[:n * 2])
    out, i = [], 0
    while i < n:
        s = i
        while w[i] != TOK_END:
            i += 1
        term = i
        i += 1
        if (base + i * 2) % 4 and i < n:
            if w[i] != 0:
                raise ValueError(f"non-zero alignment word at {base + i * 2:#x}")
            i += 1
        out.append((base + s * 2, list(w[s:term]), i - s))
    return out


def find_pointers(image: bytes, lo: int, hi: int) -> dict[int, list[int]]:
    refs: dict[int, list[int]] = {}
    for off in range(0, POINTER_SCAN_END, 4):
        v = struct.unpack_from(">I", image, off)[0]
        if lo <= v < hi:
            refs.setdefault(v, []).append(off)
    return refs


def load_entries(image: bytes) -> list[Entry]:
    refs = find_pointers(image, BLOCK_START, BLOCK_END)
    if min(refs) != BLOCK_START:
        raise ValueError(f"first pointer target {min(refs):#x} != block start {BLOCK_START:#x}")
    strs = parse_strings(image[BLOCK_START:BLOCK_END], BLOCK_START, BLOCK_END)
    starts = {a for a, _, _ in strs}
    stray = sorted(t for t in refs if t not in starts)
    if stray:
        raise ValueError("pointer targets inside strings: " + ", ".join(f"{t:#x}" for t in stray))
    return [Entry(a, c, cap, refs.get(a, [])) for a, c, cap in strs]


def _char_code(ch: str, slots: dict[str, int]) -> int:
    if ch == " ":
        return TOK_BLANK
    if ch in slots:
        return slots[ch]
    if "!" <= ch <= "~":
        ch = chr(ord(ch) + 0xFEE0)
    ch = {"〜": "～"}.get(ch, ch)   # wave dash -> fullwidth tilde glyph
    if ch not in JP_REVERSE:
        raise LayoutError(f"unmapped character {ch!r}")
    code = JP_REVERSE[ch]
    if code in slots.values():
        raise LayoutError(f"character {ch!r} uses a glyph code now holding a Hangul slot")
    return code


def encode_ko(entry: Entry, text: str, slots: dict[str, int]) -> list[int]:
    lines = text.split("\n")
    src = entry.line_cells
    if len(lines) > entry.rows:
        raise LayoutError(f"rows {len(lines)} > {entry.rows}")
    out: list[int] = []
    for i, cells in enumerate(src):
        line = lines[i] if i < len(lines) else ""
        if len(line) > entry.width:
            raise LayoutError(f"line {i + 1} width {len(line)} > {entry.width}")
        if i:
            out.append(TOK_NEWLINE)
        codes = [_char_code(ch, slots) for ch in line]
        out += codes + [TOK_BLANK] * max(0, cells - len(codes))
    if len(out) + 1 > entry.capacity:
        raise LayoutError(f"in-place capacity {entry.capacity} words < {len(out) + 1}")
    return out


def serialize(entry: Entry, codes: list[int]) -> bytes:
    words = codes + [TOK_END]
    if len(words) > entry.capacity:
        raise LayoutError(f"in-place capacity {entry.capacity} words < {len(words)}")
    words += [0] * (entry.capacity - len(words))
    return struct.pack(">%dH" % len(words), *words)
