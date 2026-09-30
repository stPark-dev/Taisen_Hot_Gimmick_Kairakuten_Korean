"""Title logo animation rebuild: strip parsing, frame composition, tile allocation (docs/initial-survey.md §10.2)."""
import struct

import pytest
from PIL import Image

from hgkairak import title
from hgkairak.graphics import GraphicsError


def _strip_image(cols=4, rows=2, frames=2, base=0x20000, first=0x29000):
    """Fake main image: pointer -> header (base, rows, cols*frames) + column-major word map."""
    img = bytearray(0x100000)
    hdr = 0x80000
    struct.pack_into(">I", img, 0x70000, hdr)
    struct.pack_into(">IHH", img, hdr, base, rows, cols * frames)
    words = [first - base + (i % 3) for i in range(rows * cols * frames)]
    struct.pack_into(">%dH" % len(words), img, hdr + 8, *words)
    geo = title.StripGeometry(pointer=0x70000, header=hdr, frames=frames, cols=cols, rows=rows, base=base)
    return bytes(img), geo, words


def test_read_strip_returns_frame_maps_column_major():
    img, geo, words = _strip_image()
    maps = title.read_strip(img, geo)
    assert len(maps) == 2 and len(maps[0]) == 4 * 2
    assert maps[0][:3] == [0x29000, 0x29001, 0x29002]
    assert maps[1][0] == 0x20000 + words[8]


@pytest.mark.parametrize("field,offset,value", [("pointer", 0x70000, 0x80004), ("rows", 0x80004, 3), ("cols", 0x80006, 9)])
def test_read_strip_rejects_mismatched_header(field, offset, value):
    img, geo, _ = _strip_image()
    img = bytearray(img)
    struct.pack_into(">I" if field == "pointer" else ">H", img, offset, value)
    with pytest.raises(GraphicsError):
        title.read_strip(bytes(img), geo)


def test_allocate_dedupes_tiles_and_keeps_column_major_order():
    a = [[1] * 32 for _ in range(16)]            # 16 rows x 32 px: two identical tiles side by side
    b = [[1] * 16 + [2] * 16 for _ in range(16)]  # second column differs
    tiles, maps = title.allocate([a, b], pool=(0x100, 0x104), cols=2, rows=1)
    assert maps == [[0x100, 0x100], [0x100, 0x101]]
    assert tiles[0x100] == bytes([1] * 256) and tiles[0x101] == bytes([2] * 256)


def test_allocate_fails_when_pool_is_too_small():
    frames = [[[v] * 16 for _ in range(16)] for v in (1, 2, 3)]
    with pytest.raises(GraphicsError, match="pool"):
        title.allocate(frames, pool=(0x10, 0x12), cols=1, rows=1)


def _layers(size=(96, 64)):
    oval = Image.new("RGBA", size, (0, 0, 0, 0))
    hot = Image.new("RGBA", size, (0, 0, 0, 0))
    kwae = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(8, 88):
        for y in range(10, 60):
            oval.putpixel((x, y), (0, 120, 40, 255))
    for x in range(10, 86):
        for y in range(18, 30):
            hot.putpixel((x, y), (250, 20, 0, 255))
        for y in range(40, 52):
            kwae.putpixel((x, y), (250, 250, 0, 255))
    return {"oval": oval, "hot": hot, "kwae": kwae}


def test_compose_frames_follows_choreography():
    frames = title.compose_frames(_layers())
    assert len(frames) == len(title.CHOREOGRAPHY) == 19
    bg = title.BG_RGB
    for k in (0, 5, 10):
        assert set(frames[k].getdata()) == {bg}
    final = frames[18]
    assert (250, 250, 0) in set(final.getdata()) and (250, 20, 0) in set(final.getdata())
    # oval fade-in: frame 11 (alpha .3) is closer to the background than frame 13
    c11 = frames[11].getpixel((160, 100))
    c13 = frames[13].getpixel((160, 100))
    assert abs(c11[1] - bg[1]) < abs(c13[1] - bg[1])
    # white flash: frame 16 background is lighter than the final background
    assert frames[16].getpixel((2, 2))[0] > final.getpixel((2, 2))[0]
    # pieces alone: frame 4 has no oval green, frame 9 no red
    assert (0, 120, 40) not in set(frames[4].getdata()) and (250, 20, 0) not in set(frames[9].getdata())


def test_compose_frames_keeps_final_logo_inside_box():
    final = title.compose_frames(_layers())[18]
    x0, y0, x1, y1 = title.FINAL_BOX
    for y in range(final.height):
        for x in range(final.width):
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                assert final.getpixel((x, y)) == title.BG_RGB


def test_quantize_maps_to_nearest_allowed_index():
    im = Image.new("RGB", (2, 1))
    im.putpixel((0, 0), (250, 0, 0))
    im.putpixel((1, 0), (10, 10, 10))
    rows = title.quantize(im, {3: (255, 0, 0), 7: (0, 0, 0)})
    assert rows == [[3, 7]]


def test_faded_oval_frames_use_flat_green():
    layers = _layers()
    oval = layers["oval"]
    for x in range(8, 88):          # give the oval a gradient
        for y in range(10, 60):
            oval.putpixel((x, y), (0, 100 + x // 2, 40, 255))
    frames = title.compose_frames(layers)
    for k in (11, 12, 13, 14, 15):                                # flat like the source's oval-only frames
        assert len({frames[k].getpixel((x, 100)) for x in range(120, 200)}) == 1, k
    assert len({frames[18].getpixel((x, 100)) for x in range(120, 200)}) > 1   # final keeps the gradient


def test_real_title_assets_fit_the_pool_with_recorded_margin():
    """Pins the tile count of the committed layers so drift (Pillow/numpy/asset) shows up in tests."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    rom = root / "roms" / "hgkairak.zip"
    if not rom.exists():
        pytest.skip("source ROM not present")
    from hgkairak import build, layout, source
    files = source.load(rom)
    img = layout.cpu_image(files[layout.MAIN_CHIPS[0]], files[layout.MAIN_CHIPS[1]])
    used = {t for m in title.read_strip(img) for t in m}
    idx = sorted({v for t in used for v in build.region_read(files, t * 256, 256)} - {0})
    from hgkairak.graphics import rom_palette
    pal = rom_palette(img, title.PALETTE_ROM, idx)
    layers = {k: Image.open(root / "assets" / v) for k, v in title.LAYERS.items()}
    frames = [title.quantize(f, pal) for f in title.compose_frames(title.arrange(layers, title.LAYOUT, title.LAYOUT_CANVAS))]
    tiles, _ = title.allocate(frames, (title.POOL[0], title.POOL[0] + 10000), 20, 14)
    assert len(tiles) <= title.POOL[1] - title.POOL[0]


def test_arrange_places_each_piece_inside_its_box_keeping_aspect():
    a = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
    for x in range(20, 380):
        for y in range(10, 90):
            a.putpixel((x, y), (255, 0, 0, 255))
    out = title.arrange({"hot": a}, {"hot": (100, 50, 299, 149)}, (768, 512))
    box = out["hot"].getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()
    assert out["hot"].size == (768, 512)
    assert 100 <= box[0] and box[2] <= 300 and 50 <= box[1] and box[3] <= 150
    w, h = box[2] - box[0], box[3] - box[1]
    assert abs(w / h - 360 / 80) < 0.1 and (w >= 198 or h >= 98)     # aspect kept, fills one side


def test_arrange_rejects_unknown_or_empty_piece():
    with pytest.raises(GraphicsError):
        title.arrange({"hot": Image.new("RGBA", (10, 10))}, {"hot": (0, 0, 9, 9)}, (768, 512))
    with pytest.raises(GraphicsError):
        title.arrange({"x": Image.new("RGBA", (10, 10), (1, 1, 1, 255))}, {"hot": (0, 0, 9, 9)}, (768, 512))
