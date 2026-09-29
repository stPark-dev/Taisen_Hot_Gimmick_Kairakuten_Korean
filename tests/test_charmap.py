"""Source glyph-code table and Hangul slot allocation."""
import pytest

from hgkairak import charmap


def test_table_size_matches_font_extent():
    assert len(charmap.JP_TABLE) == charmap.FONT_GLYPHS == 0xD66


@pytest.mark.parametrize("code,ch", [
    (0x000, "、"), (0x008, "！"), (0x06B, "０"), (0x182, "А"),
    (0x1A2, "Я"), (0x1A3, "亜"), (0x86E, "対"), (0xD37, "腕"),
    (0xD38, "并"), (0xD59, "筐"), (0xD5A, "綺"), (0xD5B, "肛"), (0xD5C, "腑"), (0xD65, "踵"),
])
def test_known_codes_from_runtime_observation(code, ch):
    assert charmap.JP_TABLE[code] == ch


def test_jp_table_has_no_duplicates():
    assert len(set(charmap.JP_TABLE)) == len(charmap.JP_TABLE)


def test_decode_tokens_roundtrip():
    codes = [0x086E, 0xFFFD, 0x0008, 0xFFFE, 0x0000]
    text = charmap.decode(codes)
    assert text == "対 ！\n、"
    assert charmap.encode_source(text) == codes


def test_decode_rejects_unknown_code():
    with pytest.raises(ValueError):
        charmap.decode([0x0D66])


def test_hangul_repertoire_is_ks_x_1001():
    hs = charmap.KS_HANGUL
    assert len(hs) == 2350 and hs[0] == "가" and hs[-1] == "힝"


def test_hangul_slots_avoid_used_codes_and_stay_in_kanji_area():
    used = {0x1A3, 0x1A5, 0x86E}
    slots = charmap.hangul_slots(used)
    assert len(slots) == 2350
    assert not (set(slots.values()) & used)
    assert all(0x1A3 <= s < 0xD66 for s in slots.values())
    assert slots["가"] == 0x1A4


def test_hangul_slots_fail_when_capacity_exhausted():
    with pytest.raises(ValueError):
        charmap.hangul_slots(set(range(0x1A3, 0x900)))
