"""Sprite-sheet pixel access, palette quantization and protected-region composition."""
import pytest
from PIL import Image

from hgkairak import graphics
from hgkairak.graphics import GraphicsError, SpriteSheet


def test_sheet_pixels_are_row_major_tiles():
    sheet = SpriteSheet(tiles=(0x10,), w=2, h=2)
    # tile k of the sheet = tnum 0x10 + k, row-major: k = ty*w + tx
    assert sheet.tile_of(17, 3) == (0x10 + 1, 3 * 16 + 1)
    assert sheet.tile_of(3, 20) == (0x10 + 2, 4 * 16 + 3)
    two = SpriteSheet(tiles=(0x10, 0x20), w=1, h=1)
    assert two.width == 32 and two.tile_of(16, 0) == (0x20, 0)


def test_sheet_read_write_roundtrip():
    sheet = SpriteSheet(tiles=(0x2,), w=2, h=1)
    region = bytearray(256 * 8)
    for i in range(256 * 2):
        region[0x2 * 256 + i] = i % 251
    rows = sheet.read(lambda off, n: bytes(region[off:off + n]))
    tiles = sheet.encode(rows)
    assert set(tiles) == {0x2, 0x3}
    for tn, data in tiles.items():
        assert data == bytes(region[tn * 256:(tn + 1) * 256])


def test_quantize_picks_nearest_allowed_index():
    palette = {5: (255, 0, 0), 9: (0, 0, 255), 11: (250, 5, 5)}
    assert graphics.nearest(palette, (240, 10, 10)) == 11
    assert graphics.nearest(palette, (10, 10, 200)) == 9


def _src_rows(bg=30, logo=7, w=64, h=32, box=(10, 5, 50, 25)):
    return [[logo if box[0] <= x <= box[2] and box[1] <= y <= box[3] else bg for x in range(w)] for y in range(h)]


def test_compose_erases_box_draws_art_and_keeps_outside():
    src = _src_rows()
    art = Image.new("RGBA", (20, 10), (0, 0, 255, 255))
    palette = {30: (200, 200, 200), 7: (255, 0, 0), 9: (0, 0, 255)}
    out = graphics.compose(src, art, box=(10, 5, 50, 25), bg=30, palette=palette, alpha_cut=128)
    for y, row in enumerate(out):
        for x, v in enumerate(row):
            inside = 10 <= x <= 50 and 5 <= y <= 25
            if not inside:
                assert v == src[y][x]
            else:
                assert v in (30, 9)
    assert sum(v == 9 for row in out for v in row) > 0
    assert all(v != 7 for row in out for v in row)   # old logo fully erased


def test_compose_treats_transparent_pixels_as_background():
    src = _src_rows()
    art = Image.new("RGBA", (20, 10), (0, 0, 255, 0))
    out = graphics.compose(src, art, box=(10, 5, 50, 25), bg=30, palette={30: (1, 1, 1), 9: (0, 0, 255)}, alpha_cut=128)
    assert all(v == 30 for row in out for v in row if True)


def test_compose_rejects_non_background_outside_box():
    src = _src_rows()
    src[0][0] = 7
    with pytest.raises(GraphicsError, match="outside"):
        graphics.compose(src, Image.new("RGBA", (4, 4)), box=(10, 5, 50, 25), bg=30, palette={30: (0, 0, 0)}, alpha_cut=128)


def test_canvas_maps_parts_and_marks_uncovered():
    from hgkairak.graphics import Canvas
    c = Canvas(parts=((0x10, 2, 1, 16, 0), (0x20, 3, 1, 0, 16)))
    assert (c.width, c.height) == (48, 32)
    assert c.tile_of(16, 0) == (0x10, 0)
    assert c.tile_of(0, 0) is None            # top-left not covered by any part
    assert c.tile_of(40, 20) == (0x22, 4 * 16 + 8)


def test_canvas_roundtrip_and_uncovered_none():
    from hgkairak.graphics import Canvas
    c = Canvas(parts=((0x1, 1, 1, 16, 0), (0x2, 2, 1, 0, 16)))
    region = bytearray(256 * 4)
    for i in range(len(region)):
        region[i] = (i * 7) % 256
    rows = c.read(lambda o, n: bytes(region[o:o + n]))
    assert rows[0][0] is None and rows[0][16] is not None
    tiles = c.encode(rows)
    assert tiles == {tn: bytes(region[tn * 256:(tn + 1) * 256]) for tn in (1, 2, 3)}


def test_compose_text_fills_parts_and_rejects_art_outside():
    from hgkairak.graphics import Canvas
    c = Canvas(parts=((0x1, 1, 1, 16, 0), (0x2, 2, 1, 0, 16)))
    src = [[None if c.tile_of(x, y) is None else 5 for x in range(c.width)] for y in range(c.height)]
    pal = {17: (16, 16, 16), 31: (244, 244, 244)}
    art = Image.new("RGBA", (c.width, c.height), (0, 0, 0, 0))
    for x in range(16, 32):
        art.putpixel((x, 3), (250, 250, 250, 255))
    out = graphics.compose_text(src, art, pal, transparent=0, alpha_cut=128)
    assert out[3][20] == 31 and out[4][20] == 0 and out[0][0] is None
    art.putpixel((2, 2), (250, 250, 250, 255))       # inside canvas bbox but not covered by a part
    with pytest.raises(GraphicsError, match="outside"):
        graphics.compose_text(src, art, pal, transparent=0, alpha_cut=128)


NANUM_XB = "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf"


@pytest.mark.skipif(not __import__("os").path.exists(NANUM_XB), reason="font missing")
def test_text_art_fits_canvas_with_outline():
    art = graphics.text_art(["코인을", "넣어 주세요!"], NANUM_XB, size=16, width=144, height=48,
                            fill=(244, 244, 244), outline=(16, 16, 16), outline_px=1)
    assert art.size == (144, 48)
    px = [art.getpixel((x, y)) for y in range(48) for x in range(144)]
    assert any(p[3] > 200 and p[0] > 200 for p in px) and any(p[3] > 200 and p[0] < 40 for p in px)


@pytest.mark.skipif(not __import__("os").path.exists(NANUM_XB), reason="font missing")
def test_text_art_rejects_text_too_large():
    with pytest.raises(GraphicsError, match="fit"):
        graphics.text_art(["아주 긴 문장이 들어가요"], NANUM_XB, size=16, width=40, height=16,
                          fill=(255, 255, 255), outline=(0, 0, 0), outline_px=1)


def test_compose_box_erases_box_blends_art_and_keeps_outside():
    src = [[17] * 20 for _ in range(10)]
    for y in range(2, 8):
        for x in range(2, 18):
            src[y][x] = 31 if (x + y) % 5 else 20      # fill with some "text" pixels
    pal = {17: (255, 255, 255), 24: (127, 159, 191), 31: (0, 64, 128)}
    art = Image.new("RGBA", (12, 4), (255, 255, 255, 0))
    art.putpixel((0, 0), (255, 255, 255, 255))
    art.putpixel((1, 0), (255, 255, 255, 128))
    out = graphics.compose_box(src, art, box=(3, 3, 14, 6), fill=31, palette=pal)
    assert out[3][3] == 17 and out[3][4] == 24        # full white, half blend
    assert out[5][10] == 31                            # erased to fill
    assert out[2][2] == src[2][2] and out[0][0] == 17  # outside box untouched


def test_compose_box_rejects_art_larger_than_box():
    src = [[31] * 10 for _ in range(10)]
    with pytest.raises(GraphicsError, match="box"):
        graphics.compose_box(src, Image.new("RGBA", (9, 2)), box=(2, 2, 5, 5), fill=31, palette={31: (0, 0, 0)})


def test_text_box_trims_only_bordered_sides():
    # 20x10 piece: fill 31 everywhere, a border column of 17 on the left, text pixels (20) near right edge
    rows = [[31] * 20 for _ in range(10)]
    for y in range(10):
        rows[y][0] = 17
    rows[4][19] = 20
    box = graphics.text_box(rows, fill=31, inset=1)
    assert box[0] >= 2            # left border trimmed (+inset)
    assert box[2] == 19 and box[1] == 0 and box[3] == 9   # borderless sides keep full extent


@pytest.mark.skipif(not __import__("os").path.exists(NANUM_XB), reason="font missing")
def test_text_art_left_align_starts_at_margin():
    art = graphics.text_art(["가"], NANUM_XB, size=16, width=100, height=20, fill=(255, 255, 255),
                            outline=(0, 0, 0), outline_px=1, align="left", margin=3)
    xs = [x for x in range(100) for y in range(20) if art.getpixel((x, y))[3] > 0]
    assert 2 <= min(xs) <= 5 and max(xs) < 30


def test_compose_box_keeps_pixels_connected_to_border():
    # border column x=0 (outside erase box), rounded-corner pixels at (1,1),(1,2) connected to it, text at (10,5)
    src = [[31] * 20 for _ in range(10)]
    for y in range(10):
        src[y][0] = 17
    src[1][1] = src[2][1] = 17
    src[5][10] = 17
    pal = {17: (255, 255, 255), 31: (0, 64, 128)}
    out = graphics.compose_box(src, Image.new("RGBA", (1, 1), (0, 0, 0, 0)), box=(3, 1, 17, 8), fill=31,
                               palette=pal, erase=(1, 0, 19, 9))
    assert out[1][1] == 17 and out[2][1] == 17      # corner kept
    assert out[5][10] == 31                          # text erased


def test_compose_text_blends_against_background_color():
    src = [[0] * 4]
    pal = {1: (241, 241, 241), 8: (144, 173, 154), 15: (48, 106, 67)}
    art = Image.new("RGBA", (4, 1), (0, 0, 0, 0))
    art.putpixel((0, 0), (255, 255, 255, 255))
    art.putpixel((1, 0), (255, 255, 255, 110))
    art.putpixel((2, 0), (255, 255, 255, 10))
    out = graphics.compose_text(src, art, pal, transparent=0, alpha_cut=32, blend_bg=(48, 106, 67))
    assert out[0] == [1, 8, 0, 0]


def test_compose_accepts_checkerboard_background():
    bg = (26, 19)
    src = [[(26 if (x + y) % 2 == 0 else 19) for x in range(12)] for y in range(8)]
    src[4][6] = 7
    out = graphics.compose(src, Image.new("RGBA", (2, 2), (0, 0, 0, 0)), box=(3, 2, 9, 6), bg=bg,
                           palette={26: (1, 1, 1), 19: (2, 2, 2)}, alpha_cut=128)
    assert all(out[y][x] == (26 if (x + y) % 2 == 0 else 19) for y in range(8) for x in range(12))


def test_hblur_spreads_horizontally_only():
    im = Image.new("L", (21, 5), 255)
    im.putpixel((10, 2), 0)
    b = graphics.hblur(im, 3)
    assert b.getpixel((10, 2)) > 0 and b.getpixel((13, 2)) < 255 and b.getpixel((14, 2)) == 255
    assert b.getpixel((10, 1)) == 255 and b.getpixel((10, 3)) == 255
    assert graphics.hblur(im, 0).tobytes() == im.tobytes()


@pytest.mark.skipif(not __import__("os").path.exists(NANUM_XB), reason="font missing")
def test_card_art_places_indented_lines():
    im = graphics.card_art(["가나", "다라"], [0, 2], NANUM_XB, 16, 80, 40, margin=2)
    assert im.size == (80, 40) and im.mode == "L"
    first_ink_row2 = min(x for x in range(80) for y in range(22, 40) if im.getpixel((x, y)) < 128)
    first_ink_row1 = min(x for x in range(80) for y in range(0, 18) if im.getpixel((x, y)) < 128)
    assert first_ink_row2 > first_ink_row1 + 8


def test_inpaint_fills_mask_from_neighbours():
    rgb = [[(100, 0, 0)] * 5 for _ in range(5)]
    rgb[2][2] = (255, 255, 255)
    mask = {(2, 2)}
    out = graphics.inpaint(rgb, mask)
    assert out[2][2] == (100, 0, 0) and out[0][0] == (100, 0, 0)


def test_inpaint_handles_large_mask():
    rgb = [[(0, 0, 200)] * 10 for _ in range(10)]
    mask = {(x, y) for x in range(2, 8) for y in range(2, 8)}
    out = graphics.inpaint(rgb, mask)
    assert all(out[y][x] == (0, 0, 200) for x, y in mask)


def test_twotone_roles_and_compose():
    # bg 0 (transparent), stroke 3x3 block: interior 9, boundary 5
    rows = [[0] * 7 for _ in range(7)]
    for y in range(1, 6):
        for x in range(1, 6):
            rows[y][x] = 5 if x in (1, 5) or y in (1, 5) else 9
    bg, fill, edge = graphics.twotone_roles(rows)
    assert (bg, fill, edge) == (0, 9, 5)
    mask = Image.new("L", (7, 7), 0)
    for y in range(2, 5):
        for x in range(2, 5):
            mask.putpixel((x, y), 255)
    out = graphics.compose_twotone(rows, mask, bg, fill, edge)
    assert out[3][3] == 9 and out[2][2] == 5 and out[0][0] == 0 and out[1][1] == 0


def test_compose_twotone_outer_outline_mode():
    rows = [[0] * 7 for _ in range(7)]
    mask = Image.new("L", (7, 7), 0)
    mask.putpixel((3, 3), 255)
    out = graphics.compose_twotone(rows, mask, 0, 12, 15, outer=True)
    assert out[3][3] == 12 and out[2][2] == 15 and out[3][4] == 15 and out[0][0] == 0


def test_canvas_rejects_aliased_tile_ranges():
    from hgkairak.graphics import Canvas
    with pytest.raises(GraphicsError, match="tile"):
        Canvas(parts=((0, 2, 1, 0, 0), (1, 2, 1, 0, 16)))


def test_sheet_rejects_aliased_tile_ranges():
    with pytest.raises(GraphicsError, match="tile"):
        graphics.SpriteSheet(tiles=(0x10, 0x11), w=2, h=1)


def test_compose_box_rejects_uncovered_cells():
    src = [[31, 31, None], [31, 31, None]]
    with pytest.raises(GraphicsError, match="uncovered"):
        graphics.compose_box(src, Image.new("RGBA", (1, 1)), box=(0, 0, 2, 1), fill=31, palette={31: (0, 0, 0)})


def test_squeezed_text_fits_narrow_box_and_keeps_height():
    from hgkairak.graphics import squeezed_text_art
    font = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
    art = squeezed_text_art(["후지쿠라 마코토"], font, range(20, 9, -1), 67, 25, (255, 255, 255), min_ratio=0.55)
    assert art.size == (67, 25)
    box = art.getchannel("A").getbbox()
    assert box[3] - box[1] >= 12          # still full height, only narrowed
    with pytest.raises(GraphicsError):
        squeezed_text_art(["아주아주아주아주아주아주긴이름입니다"], font, range(20, 9, -1), 67, 25, (255, 255, 255), min_ratio=0.55)
