"""String parsing and Korean layout encoding against controlled fixtures."""
import struct

import pytest

from hgkairak import textblock
from hgkairak.textblock import Entry, LayoutError


def words(*ws):
    return struct.pack(">%dH" % len(ws), *ws)


def test_parse_strings_with_alignment_padding():
    # "AB" FFFF 0000 | "B C" FFFF | "D" FFFF (already 4-aligned, no pad)
    blob = words(0x0075, 0x0076, 0xFFFF, 0x0000, 0x0076, 0xFFFD, 0x0077, 0xFFFF, 0x0078, 0xFFFF)
    got = textblock.parse_strings(blob, base=0x1000, end=0x1000 + len(blob))
    assert [(a, c) for a, c, _ in got] == [
        (0x1000, [0x0075, 0x0076]), (0x1008, [0x0076, 0xFFFD, 0x0077]), (0x1010, [0x0078])]
    assert [cap for _, _, cap in got] == [4, 4, 2]  # words available incl. terminator/padding


def test_parse_rejects_nonzero_alignment_word():
    blob = words(0x0075, 0x0076, 0xFFFF, 0x1234, 0x0076, 0xFFFF)
    with pytest.raises(ValueError):
        textblock.parse_strings(blob, base=0, end=len(blob))


def entry(codes, cap):
    return Entry(addr=0x2000, codes=codes, capacity=cap, refs=[0x10])


SLOTS = {"가": 0x1A4, "나": 0x1A6}


def test_budget_from_source_lines():
    e = entry([0x75, 0x76, 0xFFFD, 0xFFFE, 0x77], cap=6)
    assert e.line_cells == [3, 1]
    assert e.width == 3 and e.rows == 2


def test_encode_pads_lines_to_source_cells():
    e = entry([0x75, 0x76, 0xFFFD, 0xFFFE, 0x77, 0xFFFD], cap=8)
    assert textblock.encode_ko(e, "가\n나", SLOTS) == [0x1A4, 0xFFFD, 0xFFFD, 0xFFFE, 0x1A6, 0xFFFD]


def test_encode_fills_missing_rows_with_blanks():
    e = entry([0x75, 0x76, 0xFFFE, 0x77, 0x78], cap=6)
    assert textblock.encode_ko(e, "가", SLOTS) == [0x1A4, 0xFFFD, 0xFFFE, 0xFFFD, 0xFFFD]


def test_encode_maps_ascii_to_fullwidth_and_space_to_blank():
    e = entry([0x75] * 4, cap=6)
    assert textblock.encode_ko(e, "가 !?", SLOTS) == [0x1A4, 0xFFFD, 0x0008, 0x0007]


def test_encode_rejects_too_wide_line():
    e = entry([0x75, 0x76], cap=4)
    with pytest.raises(LayoutError, match="width"):
        textblock.encode_ko(e, "가나가", SLOTS)


def test_encode_rejects_too_many_rows():
    e = entry([0x75, 0x76], cap=4)
    with pytest.raises(LayoutError, match="rows"):
        textblock.encode_ko(e, "가\n나", SLOTS)


def test_encode_rejects_unmapped_character():
    e = entry([0x75, 0x76], cap=4)
    with pytest.raises(LayoutError, match="unmapped"):
        textblock.encode_ko(e, "뷁", SLOTS)


def test_encode_rejects_overflow_of_in_place_capacity():
    # width 3 allows line 2 to grow beyond its source cells; storage must still fit
    e = entry([0x75, 0x76, 0x77, 0xFFFE, 0x78], cap=6)
    with pytest.raises(LayoutError, match="capacity"):
        textblock.encode_ko(e, "가나가\n가나가", SLOTS)


def test_serialize_in_place_pads_to_capacity():
    e = entry([0x75, 0x76], cap=4)
    out = textblock.serialize(e, [0x1A4])
    assert out == words(0x1A4, 0xFFFF, 0x0000, 0x0000)


def test_encode_rejects_kanji_whose_slot_now_holds_hangul():
    slots = {"가": 0x1A4}
    e = entry([0x75, 0x76], cap=4)
    from hgkairak.charmap import JP_TABLE
    with pytest.raises(LayoutError, match="Hangul slot"):
        textblock.encode_ko(e, JP_TABLE[0x1A4], slots)
    assert textblock.encode_ko(e, JP_TABLE[0x1A3], slots)[0] == 0x1A3   # untouched kanji still fine


@pytest.mark.parametrize("ch,code", [("~", 0x1F), ("〜", 0x1F), ("-", 0x3B)])
def test_encode_maps_tilde_wave_dash_and_hyphen(ch, code):
    from hgkairak.charmap import JP_TABLE
    assert JP_TABLE[code] in ("～", "－")
    e = entry([0x75, 0x76], cap=4)
    assert textblock.encode_ko(e, ch, SLOTS)[0] == code
