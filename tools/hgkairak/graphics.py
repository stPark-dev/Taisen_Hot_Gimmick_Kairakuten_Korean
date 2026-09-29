"""Graphics-text replacement on 8bpp sprite sheets.

Established (docs/initial-survey.md §10): a sprite of w×h 16px tiles uses tiles tnum + ty*w + tx
(row-major), 256 bytes per tile, pixel value = palette index offset within the sprite's bank.
"""
import struct
from dataclasses import dataclass

from PIL import Image


class GraphicsError(ValueError):
    pass


def _check_ranges(ranges):
    """Reject sprites whose tile ranges [tnum, tnum + w*h) overlap (would alias pixels)."""
    spans = sorted(ranges)
    for (a, n), (b, _) in zip(spans, spans[1:]):
        if b < a + n:
            raise GraphicsError(f"tile ranges overlap: {a:#x}+{n} and {b:#x}")


@dataclass(frozen=True)
class SpriteSheet:
    tiles: tuple[int, ...]     # first tnum of each horizontally adjacent sprite
    w: int                     # tiles per sprite, horizontally
    h: int                     # tiles per sprite, vertically

    def __post_init__(self):
        _check_ranges([(t, self.w * self.h) for t in self.tiles])

    @property
    def width(self) -> int:
        return self.w * 16 * len(self.tiles)

    @property
    def height(self) -> int:
        return self.h * 16

    def tile_of(self, x: int, y: int) -> tuple[int, int]:
        s, lx = divmod(x, self.w * 16)
        return self.tiles[s] + (y // 16) * self.w + lx // 16, (y % 16) * 16 + lx % 16

    def read(self, reader) -> list[list[int]]:
        cache: dict[int, bytes] = {}
        rows = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                tn, off = self.tile_of(x, y)
                if tn not in cache:
                    cache[tn] = reader(tn * 256, 256)
                row.append(cache[tn][off])
            rows.append(row)
        return rows

    def encode(self, rows) -> dict[int, bytes]:
        out: dict[int, bytearray] = {}
        for y in range(self.height):
            for x in range(self.width):
                tn, off = self.tile_of(x, y)
                out.setdefault(tn, bytearray(256))[off] = rows[y][x]
        return {tn: bytes(b) for tn, b in out.items()}


def rom_palette(image: bytes, addr: int, indices) -> dict[int, tuple[int, int, int]]:
    """Palette entries stored as big-endian RGBx dwords."""
    pal = {}
    for i in indices:
        v = struct.unpack_from(">I", image, addr + i * 4)[0]
        pal[i] = ((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255)
    return pal


def nearest(palette: dict[int, tuple[int, int, int]], rgb) -> int:
    return min(palette, key=lambda i: (sum((a - b) ** 2 for a, b in zip(palette[i], rgb)), i))


def compose(src_rows, art: Image.Image, box, bg: int, palette, alpha_cut: int):
    """Erase box to bg, draw art scaled to fit box (centered), keep everything outside box."""
    x0, y0, x1, y1 = box
    bg_at = (lambda x, y: bg[(x + y) % 2]) if isinstance(bg, tuple) else (lambda x, y: bg)
    for y, row in enumerate(src_rows):
        for x, v in enumerate(row):
            if not (x0 <= x <= x1 and y0 <= y <= y1) and v != bg_at(x, y):
                raise GraphicsError(f"source has non-background pixel outside editable box at ({x},{y})")
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    art = art.convert("RGBA")
    bbox = art.getchannel("A").point(lambda a: 255 if a >= alpha_cut else 0).getbbox()
    if bbox is None:
        art_fit = None
    else:
        art = art.crop(bbox)
        scale = min(bw / art.width, bh / art.height)
        size = (max(1, round(art.width * scale)), max(1, round(art.height * scale)))
        art_fit = art.resize(size, Image.LANCZOS)
    out = [list(r) for r in src_rows]
    cache: dict[tuple, int] = {}
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            out[y][x] = bg_at(x, y)
    if art_fit is not None:
        ox = x0 + (bw - art_fit.width) // 2
        oy = y0 + (bh - art_fit.height) // 2
        for y in range(art_fit.height):
            for x in range(art_fit.width):
                r, g, b, a = art_fit.getpixel((x, y))
                if a >= alpha_cut:
                    key = (r, g, b)
                    if key not in cache:
                        cache[key] = nearest(palette, key)
                    out[oy + y][ox + x] = cache[key]
    return out


@dataclass(frozen=True)
class Canvas:
    """Several sprites composing one picture: parts = ((tnum, w, h, ox, oy), ...) in pixels."""
    parts: tuple[tuple[int, int, int, int, int], ...]

    def __post_init__(self):
        if any(w < 1 or h < 1 for _, w, h, _, _ in self.parts):
            raise GraphicsError("part size must be at least 1x1 tiles")
        _check_ranges([(t, w * h) for t, w, h, _, _ in self.parts])

    @property
    def width(self) -> int:
        return max(ox + w * 16 for _, w, _, ox, _ in self.parts)

    @property
    def height(self) -> int:
        return max(oy + h * 16 for _, _, h, _, oy in self.parts)

    def tile_of(self, x: int, y: int):
        hit = None
        for tn, w, h, ox, oy in self.parts:
            if ox <= x < ox + w * 16 and oy <= y < oy + h * 16:
                lx, ly = x - ox, y - oy
                if hit is not None:
                    raise GraphicsError(f"parts overlap at ({x},{y})")
                hit = (tn + (ly // 16) * w + lx // 16, (ly % 16) * 16 + lx % 16)
        return hit

    def read(self, reader) -> list[list]:
        cache: dict[int, bytes] = {}
        rows = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                t = self.tile_of(x, y)
                if t is None:
                    row.append(None)
                    continue
                if t[0] not in cache:
                    cache[t[0]] = reader(t[0] * 256, 256)
                row.append(cache[t[0]][t[1]])
            rows.append(row)
        return rows

    def encode(self, rows) -> dict[int, bytes]:
        out: dict[int, bytearray] = {}
        for y in range(self.height):
            for x in range(self.width):
                t = self.tile_of(x, y)
                if t is not None:
                    out.setdefault(t[0], bytearray(256))[t[1]] = rows[y][x]
        return {tn: bytes(b) for tn, b in out.items()}


def compose_text(src_rows, art: Image.Image, palette, transparent: int, alpha_cut: int, blend_bg=None):
    """Replace every covered pixel: art (canvas-sized RGBA) → nearest palette index, else transparent."""
    art = art.convert("RGBA")
    if art.size != (len(src_rows[0]), len(src_rows)):
        raise GraphicsError(f"art size {art.size} != canvas size")
    out, cache = [], {}
    for y, row in enumerate(src_rows):
        new = []
        for x, v in enumerate(row):
            r, g, b, a = art.getpixel((x, y))
            if v is None:
                if a >= alpha_cut:
                    raise GraphicsError(f"art pixel outside drawable parts at ({x},{y})")
                new.append(None)
            elif a >= alpha_cut:
                if blend_bg is not None:
                    r, g, b = (c * a / 255 + f * (255 - a) / 255 for c, f in zip((r, g, b), blend_bg))
                if (r, g, b) not in cache:
                    cache[(r, g, b)] = nearest(palette, (r, g, b))
                new.append(cache[(r, g, b)])
            else:
                new.append(transparent)
        out.append(new)
    return out


def text_art(lines, font_path, size, width, height, fill, outline, outline_px=1, line_gap=0, offsets=None, antialias=False,
             align="center", margin=0):
    """Centered outlined text on a transparent canvas; fails when it does not fit."""
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype(str(font_path), size)
    boxes = [font.getbbox(t, stroke_width=outline_px) for t in lines]
    heights = [b[3] - b[1] for b in boxes]
    total = sum(heights) + line_gap * (len(lines) - 1)
    widest = max(b[2] - b[0] for b in boxes)
    if widest + 2 * margin > width or total > height:
        raise GraphicsError(f"text does not fit: {widest}x{total} > {width}x{height}")
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.fontmode = "L" if antialias else "1"
    y = (height - total) // 2
    for i, (t, b, h) in enumerate(zip(lines, boxes, heights)):
        x = (margin - b[0]) if align == "left" else (width - (b[2] - b[0])) // 2 - b[0]
        dx, dy = offsets[i] if offsets else (0, 0)
        d.text((x + dx, y - b[1] + dy), t, font=font, fill=fill + (255,),
               stroke_width=outline_px, stroke_fill=(outline + (255,)) if outline else None)
        y += h + line_gap
    return im


def compose_box(src_rows, art: Image.Image, box, fill: int, palette, erase=None):
    """Erase `erase` (default: box) to fill, alpha-blend art centered in box over the fill color, keep outside."""
    x0, y0, x1, y1 = box
    ex0, ey0, ex1, ey1 = erase or box
    if not (ex0 <= x0 and ey0 <= y0 and x1 <= ex1 and y1 <= ey1):
        raise GraphicsError("draw box must lie inside erase box")
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    art = art.convert("RGBA")
    if art.width > bw or art.height > bh:
        raise GraphicsError(f"art {art.size} larger than box {bw}x{bh}")
    base = palette[fill]
    if any(src_rows[y][x] is None for y in range(ey0, ey1 + 1) for x in range(ex0, ex1 + 1)):
        raise GraphicsError("box covers uncovered canvas cells")
    out = [list(r) for r in src_rows]
    H, W = len(src_rows), len(src_rows[0])
    inside = lambda x, y: ex0 <= x <= ex1 and ey0 <= y <= ey1
    keep, stack = set(), []
    for y in range(ey0, ey1 + 1):          # seeds: non-fill pixels in the box touching an opaque pixel outside it
        for x in range(ex0, ex1 + 1):
            if src_rows[y][x] == fill:
                continue
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < W and 0 <= ny < H and not inside(nx, ny) and src_rows[ny][nx] not in (0, None, fill):
                    stack.append((x, y))
                    break
    while stack:
        x, y = stack.pop()
        if (x, y) in keep:
            continue
        keep.add((x, y))
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if inside(nx, ny) and src_rows[ny][nx] != fill and (nx, ny) not in keep:
                stack.append((nx, ny))
    for y in range(ey0, ey1 + 1):
        for x in range(ex0, ex1 + 1):
            if (x, y) not in keep:
                out[y][x] = fill
    ox, oy = x0 + (bw - art.width) // 2, y0 + (bh - art.height) // 2
    cache: dict[tuple, int] = {}
    for y in range(art.height):
        for x in range(art.width):
            r, g, b, a = art.getpixel((x, y))
            if a == 0:
                continue
            k = tuple((c * a + f * (255 - a)) / 255 for c, f in zip((r, g, b), base))
            if k not in cache:
                cache[k] = nearest(palette, k)
            out[oy + y][ox + x] = cache[k]
    return out


def text_box(rows, fill: int, inset: int = 1, border_frac: float = 0.6):
    """Opaque-area bbox, trimmed on each side only where a border line runs along it (then inset)."""
    if not any(v == fill for r in rows for v in r):
        raise GraphicsError("no fill area")
    pts = [(x, y) for y, r in enumerate(rows) for x, v in enumerate(r) if v]
    b = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

    def line(side):
        x0, y0, x1, y1 = b
        if side == 0: return [rows[y][x0] for y in range(y0, y1 + 1)]
        if side == 2: return [rows[y][x1] for y in range(y0, y1 + 1)]
        if side == 1: return [rows[y0][x] for x in range(x0, x1 + 1)]
        return [rows[y1][x] for x in range(x0, x1 + 1)]

    step = {0: (0, 1), 1: (1, 1), 2: (2, -1), 3: (3, -1)}
    for side, (i, d) in step.items():
        trimmed = False
        while b[2] - b[0] > 2 and b[3] - b[1] > 2:
            ln = line(side)
            if sum(v != fill for v in ln) / len(ln) < border_frac:
                break
            b[i] += d
            trimmed = True
        if trimmed:
            b[i] += d * inset
    return tuple(b)


def hblur(im: Image.Image, radius: int) -> Image.Image:
    """Horizontal box blur (grayscale), edges clamped."""
    if radius <= 0:
        return im.copy()
    w, h = im.size
    src = im.load()
    out = Image.new("L", (w, h))
    dst = out.load()
    for y in range(h):
        row = [src[x, y] for x in range(w)]
        for x in range(w):
            seg = [row[min(w - 1, max(0, x + k))] for k in range(-radius, radius + 1)]
            dst[x, y] = round(sum(seg) / len(seg))
    return out


def card_art(lines, indents, font_path, size, width, height, margin=4, line_gap=2):
    """Black text on white, left aligned with per-line indent (in em units of `size`/2)."""
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype(str(font_path), size)
    im = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(im)
    line_h = size + line_gap
    if margin + line_h * len(lines) > height:
        raise GraphicsError("card text does not fit vertically")
    for i, (t, ind) in enumerate(zip(lines, indents)):
        x = margin + ind * size // 2
        if x + font.getlength(t) > width - margin:
            raise GraphicsError(f"card line too wide: {t}")
        d.text((x, margin + i * line_h), t, font=font, fill=0)
    return im


def inpaint(rgb_rows, mask):
    """Fill masked pixels by repeatedly averaging already-known 8-neighbours (outside-in)."""
    h, w = len(rgb_rows), len(rgb_rows[0])
    out = [list(r) for r in rgb_rows]
    todo = set(mask)
    while todo:
        ready = {}
        for x, y in todo:
            nb = [out[ny][nx] for nx in range(x - 1, x + 2) for ny in range(y - 1, y + 2)
                  if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in todo]
            if nb:
                ready[(x, y)] = tuple(round(sum(c[i] for c in nb) / len(nb)) for i in range(3))
        if not ready:
            raise GraphicsError("inpaint mask has no known neighbours")
        for (x, y), c in ready.items():
            out[y][x] = c
        todo -= set(ready)
    return out


def twotone_roles(rows):
    """(background, stroke-interior, stroke-edge) palette indices of flat text art, from the source pixels."""
    from collections import Counter
    h, w = len(rows), len(rows[0])
    bg = Counter(v for r in rows for v in r if v is not None).most_common(1)[0][0]
    inner, edge = Counter(), Counter()
    for y in range(h):
        for x in range(w):
            v = rows[y][x]
            if v == bg or v is None:
                continue
            nb = [rows[ny][nx] for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)) if 0 <= nx < w and 0 <= ny < h]
            (edge if any(n == bg for n in nb) or len(nb) < 4 else inner)[v] += 1
    if not inner and not edge:
        raise GraphicsError("no text pixels")
    fill = (inner or edge).most_common(1)[0][0]
    return bg, fill, (edge or inner).most_common(1)[0][0]


def compose_twotone(rows, mask: Image.Image, bg: int, fill: int, edge: int, cut: int = 128, outer: bool = False):
    """Replace every pixel: mask → fill (edge index on the mask boundary), else background.
    outer=True: mask → fill, 8-neighbours outside the mask → edge (outlined text)."""
    h, w = len(rows), len(rows[0])
    if mask.size != (w, h):
        raise GraphicsError("mask size != sheet size")
    on = [[mask.getpixel((x, y)) >= cut for x in range(w)] for y in range(h)]
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            if rows[y][x] is None:
                if on[y][x]:
                    raise GraphicsError(f"text outside drawable parts at ({x},{y})")
                row.append(None)
                continue
            if outer:
                if on[y][x]:
                    row.append(fill)
                else:
                    near = any(0 <= nx < w and 0 <= ny < h and on[ny][nx]
                               for nx in range(x - 1, x + 2) for ny in range(y - 1, y + 2))
                    row.append(edge if near else bg)
                continue
            if not on[y][x]:
                row.append(bg)
                continue
            border = any(not (0 <= nx < w and 0 <= ny < h) or not on[ny][nx]
                         for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
            row.append(edge if border else fill)
        out.append(row)
    return out
