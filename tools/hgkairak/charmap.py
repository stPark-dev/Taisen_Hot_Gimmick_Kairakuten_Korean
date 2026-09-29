"""Glyph code tables.

Source table (established, docs/initial-survey.md §3): code = index into a compacted JIS X 0208
subset; tile = code + FONT_TILE_BASE. 0xD38-0xD65 are hand-picked level-2 kanji identified
visually (PROVISIONAL; this revision adds 綺 and 腑 to the first game's list).
"""
FONT_TILE_BASE = 0x18788
FONT_GLYPHS = 0xD66
KANJI_START = 0x1A3

TOK_BLANK, TOK_NEWLINE, TOK_END = 0xFFFD, 0xFFFE, 0xFFFF
TOKEN_TEXT = {TOK_BLANK: " ", TOK_NEWLINE: "\n"}

# PROVISIONAL visual identification of codes 0xD38-0xD65.
EXTRA_KANJI = "并弍儡冑刮刹剋剌剪剽劈劵勁勍匍匐卍厠曼嘸哂喻嗟姜巫揉數暸曖曰杞發筌筐綺肛腑膣舐舖萬螢蟲蟠蠹踵"


def _jis(row: int, cell: int) -> str:
    s1 = (row + 0x101) >> 1 if row <= 62 else (row + 0x181) >> 1
    s2 = cell + (0x3F if cell <= 63 else 0x40) if row % 2 else cell + 0x9E
    return bytes((s1, s2)).decode("cp932")


def _build_jp_table() -> list[str]:
    t = [_jis(1, c) for c in range(2, 95)]
    t += [_jis(2, c) for c in range(1, 15)]
    for c in range(1, 95):
        try:
            ch = _jis(3, c)
        except UnicodeDecodeError:
            continue
        if ch.isalnum():
            t.append(ch)
    t += [_jis(4, c) for c in range(1, 84)]
    t += [_jis(5, c) for c in range(1, 87)]
    t += [_jis(6, c) for c in range(1, 25)] + [_jis(6, c) for c in range(33, 57)]
    t += [_jis(7, c) for c in range(1, 34)]
    for row in range(16, 48):
        t += [_jis(row, c) for c in range(1, 52 if row == 47 else 95)]
    t += list(EXTRA_KANJI)
    return t


JP_TABLE = _build_jp_table()
assert len(JP_TABLE) == FONT_GLYPHS, len(JP_TABLE)
JP_REVERSE = {ch: i for i, ch in enumerate(JP_TABLE)}

KS_HANGUL = [bytes((a, b)).decode("euc_kr") for a in range(0xB0, 0xC9) for b in range(0xA1, 0xFF)]


def decode(codes) -> str:
    out = []
    for v in codes:
        if v < FONT_GLYPHS:
            out.append(JP_TABLE[v])
        elif v in TOKEN_TEXT:
            out.append(TOKEN_TEXT[v])
        else:
            raise ValueError(f"unknown code {v:#06x}")
    return "".join(out)


def encode_source(text: str) -> list[int]:
    rev_tok = {v: k for k, v in TOKEN_TEXT.items()}
    return [rev_tok[ch] if ch in rev_tok else JP_REVERSE[ch] for ch in text]


def hangul_slots(used_codes: set[int]) -> dict[str, int]:
    """Fixed KS X 1001 Hangul order placed into kanji slots the source corpus does not use."""
    free = [c for c in range(KANJI_START, FONT_GLYPHS) if c not in used_codes]
    if len(free) < len(KS_HANGUL):
        raise ValueError(f"not enough free glyph slots: {len(free)} < {len(KS_HANGUL)}")
    return dict(zip(KS_HANGUL, free))
