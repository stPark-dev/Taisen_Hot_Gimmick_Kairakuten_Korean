"""Title logo animation rebuild (docs/initial-survey.md §10.2).

Established: the attract-mode logo is a strip of 19 frames × 20 columns × 14 rows of 1×1 sprites
(header at main 0xC0F88 = tile base 0x20000, 14 rows, 380 columns; referenced from 0xB73B8; column-major
16-bit words = tile - base). All 19 frames use only the contiguous tile pool 0x2BA5F-0x2C08E, which
nothing else references, so the Korean frames are re-tiled into that pool and the strip is rewritten.
Choreography (piece boxes, zoom, fades) measured from the source frames.
"""
import hashlib
import pathlib
import struct
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .graphics import GraphicsError, rom_palette


@dataclass(frozen=True)
class StripGeometry:
    pointer: int
    header: int
    frames: int
    cols: int
    rows: int
    base: int


GEOMETRY = StripGeometry(pointer=0xB73B8, header=0xC0F88, frames=19, cols=20, rows=14, base=0x20000)
POOL = (0x2BA5F, 0x2C08F)          # half-open tile range
PALETTE_ROM = 0x6A590
BG_INDEX, BG_RGB = 12, (240, 240, 240)
SCREEN = (320, 224)
FINAL_BOX = (30, 14, 289, 178)      # Korean logo fits here (source logo: 36,20-283,176; coin text below)
HOT_INTRO_BOX = (21, 60, 299, 148)  # source frame 4 extent
KWAE_INTRO_BOX = (56, 62, 263, 140)  # source frame 9 extent
LAYERS = {"oval": "gfx/title_layer_oval.png", "hot": "gfx/title_layer_hot.png", "kwae": "gfx/title_layer_kwae.png"}

# One entry per source frame: ("blank",) | ("intro", piece, zoom) | ("oval", alpha) | ("slide", dy_hot, dy_kwae)
# | ("final", white)
CHOREOGRAPHY = (
    ("blank",),
    ("intro", "hot", 0.15), ("intro", "hot", 0.10), ("intro", "hot", 0.04), ("intro", "hot", 0.0),
    ("blank",),
    ("intro", "kwae", 0.15), ("intro", "kwae", 0.09), ("intro", "kwae", 0.03), ("intro", "kwae", 0.0),
    ("blank",),
    ("oval", 0.3), ("oval", 0.6), ("oval", 1.0),
    ("slide", -61, 75), ("slide", -44, 39),
    ("final", 0.6), ("final", 0.3), ("final", 0.0),
)


def read_strip(image: bytes, geo: StripGeometry = GEOMETRY) -> list[list[int]]:
    """Per-frame column-major tile numbers; fails unless pointer and header match the geometry."""
    if struct.unpack_from(">I", image, geo.pointer)[0] != geo.header:
        raise GraphicsError(f"title strip pointer at {geo.pointer:#x} does not reference {geo.header:#x}")
    if struct.unpack_from(">IHH", image, geo.header) != (geo.base, geo.rows, geo.cols * geo.frames):
        raise GraphicsError(f"title strip header at {geo.header:#x} does not match the expected geometry")
    n = geo.cols * geo.rows
    words = struct.unpack_from(">%dH" % (n * geo.frames), image, geo.header + 8)
    return [[geo.base + w for w in words[k * n:(k + 1) * n]] for k in range(geo.frames)]


def _paste(canvas: Image.Image, layer: Image.Image, crop, scale: float, center, alpha: float = 1.0) -> None:
    piece = layer.crop(crop)
    size = (max(1, round(piece.width * scale)), max(1, round(piece.height * scale)))
    piece = piece.resize(size, Image.LANCZOS)
    if alpha < 1.0:
        piece.putalpha(piece.getchannel("A").point(lambda a: round(a * alpha)))
    canvas.alpha_composite(piece, (round(center[0] - size[0] / 2), round(center[1] - size[1] / 2)))


def _flat_green(layer: Image.Image) -> Image.Image:
    """Oval green replaced by its median colour: the source oval is flat until the logo assembles (frames 11-15)."""
    arr = np.array(layer)
    r, g, b = (arr[..., i].astype(int) for i in range(3))
    green = (g > r + 40) & (g > b + 20) & (arr[..., 3] >= 128)
    if green.any():
        arr[green, :3] = np.median(arr[green, :3], axis=0).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _fit(bbox, box) -> tuple[float, tuple[float, float]]:
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x0, y0, x1, y1 = box
    scale = min((x1 - x0 + 1) / bw, (y1 - y0 + 1) / bh)
    return scale, ((x0 + x1 + 1) / 2, (y0 + y1 + 1) / 2)


def compose_frames(layers: dict[str, Image.Image]) -> list[Image.Image]:
    """RGB screen images for every source frame, drawn from the Korean logo layers."""
    layers = {k: v.convert("RGBA") for k, v in layers.items()}
    if len({v.size for v in layers.values()}) != 1:
        raise GraphicsError("title layers must share one canvas size")
    boxes = {k: v.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox() for k, v in layers.items()}
    if None in boxes.values():
        raise GraphicsError("empty title layer")
    union = (min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values()),
             max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values()))
    scale, center = _fit(union, FINAL_BOX)

    flat_oval = _flat_green(layers["oval"])

    def arranged(canvas, name, dy=0.0, alpha=1.0, flat=False):
        # same transform for every layer: crop the union box so relative positions are kept
        src = flat_oval if name == "oval" and flat else layers[name]
        _paste(canvas, src, union, scale, (center[0], center[1] + dy), alpha)

    frames = []
    for step in CHOREOGRAPHY:
        canvas = Image.new("RGBA", SCREEN, BG_RGB + (255,))
        kind = step[0]
        if kind == "intro":
            _, name, zoom = step
            box = HOT_INTRO_BOX if name == "hot" else KWAE_INTRO_BOX
            s, c = _fit(boxes[name], box)
            if zoom:
                acc = np.zeros(SCREEN[::-1] + (4,))
                n = 8
                for i in range(n):
                    layer = Image.new("RGBA", SCREEN, (0, 0, 0, 0))
                    _paste(layer, layers[name], boxes[name], s * (1 + zoom * i / (n - 1)), c)
                    arr = np.asarray(layer, dtype=float)
                    acc[..., :3] += arr[..., :3] * arr[..., 3:] / 255
                    acc[..., 3] += arr[..., 3]
                a = acc[..., 3:] / n
                rgb = np.where(a > 0, acc[..., :3] / np.maximum(acc[..., 3:], 1e-9) * 255, 0)
                blur = np.concatenate([rgb, a], -1).clip(0, 255).astype(np.uint8)
                canvas.alpha_composite(Image.fromarray(blur, "RGBA"))
            else:
                _paste(canvas, layers[name], boxes[name], s, c)
        elif kind == "oval":
            arranged(canvas, "oval", alpha=step[1], flat=True)
        elif kind == "slide":
            arranged(canvas, "oval", flat=True)
            arranged(canvas, "hot", dy=step[1])
            arranged(canvas, "kwae", dy=step[2])
        elif kind == "final":
            for name in ("oval", "hot", "kwae"):
                arranged(canvas, name)
            white = step[1]
            if white:
                canvas = Image.blend(canvas, Image.new("RGBA", SCREEN, (255, 255, 255, 255)), white)
        elif kind != "blank":
            raise GraphicsError(f"unknown choreography step {step}")
        frames.append(canvas.convert("RGB"))
    return frames


def quantize(im: Image.Image, palette: dict[int, tuple[int, int, int]]) -> list[list[int]]:
    """Nearest palette index per pixel (ties -> lowest index)."""
    idx = np.array(sorted(palette))
    pal = np.array([palette[i] for i in idx], dtype=float)
    px = np.asarray(im.convert("RGB"), dtype=float).reshape(-1, 3)
    colors, inverse = np.unique(px, axis=0, return_inverse=True)
    best = np.empty(len(colors), dtype=int)
    for s in range(0, len(colors), 4096):
        d = ((colors[s:s + 4096, None, :] - pal[None, :, :]) ** 2).sum(-1)
        best[s:s + 4096] = d.argmin(1)
    out = idx[best[inverse.ravel()]].reshape(im.height, im.width)
    return out.tolist()


def allocate(frames, pool, cols: int, rows: int):
    """Cut frames into column-major 16×16 tiles, dedupe, and number them from the pool start."""
    lo, hi = pool
    tiles: dict[int, bytes] = {}
    index: dict[bytes, int] = {}
    maps = []
    for rows_px in frames:
        arr = np.asarray(rows_px, dtype=np.uint8)
        if arr.shape != (rows * 16, cols * 16):
            raise GraphicsError(f"frame size {arr.shape} != {(rows * 16, cols * 16)}")
        m = []
        for x in range(cols):
            for y in range(rows):
                t = arr[y * 16:(y + 1) * 16, x * 16:(x + 1) * 16].tobytes()
                if t not in index:
                    tn = lo + len(index)
                    if tn >= hi:
                        raise GraphicsError(f"title tiles exceed the pool {lo:#x}-{hi:#x}")
                    index[t] = tn
                    tiles[tn] = t
                m.append(index[t])
        maps.append(m)
    return tiles, maps


def title_writes(plan, files, image, assets_dir, add_mapped, region_read, main_map, gfx_map) -> dict:
    geo = GEOMETRY
    src_maps = read_strip(image, geo)
    used_tiles = {t for m in src_maps for t in m}
    if not all(POOL[0] <= t < POOL[1] for t in used_tiles):
        raise GraphicsError("source title strip uses tiles outside the pool")
    indices = sorted({v for t in used_tiles for v in region_read(files, t * 256, 256)} - {0})
    palette = rom_palette(image, PALETTE_ROM, indices)
    if palette.get(BG_INDEX) != BG_RGB:
        raise GraphicsError("title palette background entry changed")
    paths = {k: pathlib.Path(assets_dir) / v for k, v in LAYERS.items()}
    layers = {}
    for k, p in paths.items():
        with Image.open(p) as im:
            layers[k] = im.copy()
    frames = [quantize(f, palette) for f in compose_frames(layers)]
    tiles, maps = allocate(frames, POOL, geo.cols, geo.rows)
    for tn, t in tiles.items():
        add_mapped(plan, f"title:tile:{tn:05X}", gfx_map, tn * 256, region_read(files, tn * 256, 256), t)
    n = geo.cols * geo.rows
    for k, m in enumerate(maps):
        addr = geo.header + 8 + k * n * 2
        final = struct.pack(">%dH" % n, *(t - geo.base for t in m))
        add_mapped(plan, f"title:map:{k:02d}", main_map, addr, image[addr:addr + len(final)], final)
    return {"title_logo": {"layer_sha1": {k: hashlib.sha1(p.read_bytes()).hexdigest() for k, p in paths.items()},
                           "tiles_written": len(tiles), "pool_free": POOL[1] - POOL[0] - len(tiles),
                           "maps_written": len(maps), "_tiles": tiles, "_maps": maps}}
