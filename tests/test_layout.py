"""CPU-view / chip-file coordinate mapping (adopted from survey: docs/initial-survey.md §2)."""
import pytest

from hgkairak import layout


def make_chips(n=16):
    u22 = bytes(range(0, n))
    u23 = bytes(range(0x80, 0x80 + n))
    return u22, u23


def test_cpu_image_interleaves_swapped_words():
    u22, u23 = make_chips(4)
    # u22 word0 = 00 01 -> swapped 01 00 ; u23 word0 = 80 81 -> 81 80
    img = layout.cpu_image(u22, u23)
    assert img[:8] == bytes([0x01, 0x00, 0x81, 0x80, 0x03, 0x02, 0x83, 0x82])


@pytest.mark.parametrize("addr", range(0, 16))
def test_main_addr_to_chip_matches_cpu_image(addr):
    u22, u23 = make_chips(16)
    img = layout.cpu_image(u22, u23)
    chip, off = layout.main_addr_to_chip(addr)
    src = {"1.u22": u22, "2.u23": u23}[chip]
    assert src[off] == img[addr]


def test_main_addr_to_chip_is_bijective():
    seen = {layout.main_addr_to_chip(a) for a in range(64)}
    assert len(seen) == 64


def test_gfx_offset_mapping_matches_region_order():
    l0, h0 = bytes(range(8)), bytes(range(0x40, 0x48))
    # region dword = l word + h word
    region = b"".join(l0[i:i + 2] + h0[i:i + 2] for i in range(0, 8, 2))
    for off in range(len(region)):
        f, o = layout.gfx_offset_to_file(off)
        assert {"0l.u2": l0, "0h.u11": h0}[f][o] == region[off]


def test_gfx_offset_selects_pair_by_8mb():
    assert layout.gfx_offset_to_file(0x800000)[0] == "1l.u3"
    assert layout.gfx_offset_to_file(0x1000002) == ("2h.u13", 0)
    with pytest.raises(ValueError):
        layout.gfx_offset_to_file(0x3000000)


def test_main_addr_out_of_range_rejected():
    with pytest.raises(ValueError):
        layout.main_addr_to_chip(0x100000)
