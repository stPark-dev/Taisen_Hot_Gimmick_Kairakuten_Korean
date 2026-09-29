#!/usr/bin/env python3
"""Derive the title-animation layers from the provided Korean logo (asset preparation, not the product build).

  derive_title_layers.py [--src assets/gfx/title_ko.png] [--out assets/gfx]

Writes title_layer_{oval,hot,kwae}.png (768x512 RGBA, same canvas):
- the logo is cut out of its dark vignette by flood-filling from the borders up to the white rim;
- 핫기믹 / 쾌락천 = warm text fills (split by height band) grown over their black backing;
- oval = everything else (with the 대전 tab), its hidden parts rebuilt: fitted ellipse, rim, harmonic green fill.
Recompositing oval+hot+kwae reproduces the source inside the visible logo (checked below).
"""
import argparse
import collections
import pathlib

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage as ndi

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANDS = (250, 610)   # source-pixel y: 대전 above, 핫기믹 between, 쾌락천 below


def cut_logo(im: Image.Image, thr=150, dil=2) -> np.ndarray:
    W, H = im.size
    px = im.load()
    bar = Image.new("L", (W, H), 0)
    bp = bar.load()
    for y in range(H):
        for x in range(W):
            if min(px[x, y][:3]) >= thr:
                bp[x, y] = 255
    bar = bar.filter(ImageFilter.MaxFilter(2 * dil + 1))
    wall = np.asarray(bar) > 0
    seen = np.zeros((H, W), bool)
    dq = collections.deque([(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)])
    while dq:
        x, y = dq.popleft()
        if seen[y, x] or wall[y, x]:
            continue
        seen[y, x] = True
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < W and 0 <= ny < H and not seen[ny, nx]:
                dq.append((nx, ny))
    logo = ~seen
    rgb = np.asarray(im.convert("RGB")).astype(int)
    inner = ndi.binary_erosion(logo, iterations=dil)
    logo &= inner | (rgb.min(-1) >= thr)          # give the dilated band back to the background
    lum = rgb.mean(-1)
    return logo | (ndi.binary_dilation(logo, iterations=6) & ~logo & (lum < 70))   # outer black line


def derive(src: pathlib.Path):
    im = Image.open(src).convert("RGBA")
    orig = np.asarray(im).astype(float)
    r, g, b = orig[..., 0], orig[..., 1], orig[..., 2]
    L = cut_logo(im)
    H, W = L.shape
    greenish = (g > r + 40) & (g > b + 20) & (g < 200)
    lab, n = ndi.label(greenish & L)
    thick = np.zeros_like(L)
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() > 1000 and ndi.binary_erosion(m, iterations=4).sum() / m.sum() > 0.5:
            thick |= m
    warm = L & (r > 180) & (b < 150) & (r >= g - 10)
    wl, wn = ndi.label(warm)
    centers = ndi.center_of_mass(warm, wl, range(1, wn + 1))
    sizes = ndi.sum(warm, wl, range(1, wn + 1))
    dae, hot, kwae = (np.zeros_like(L) for _ in range(3))
    for k, (cy, _) in enumerate(centers):
        if sizes[k] >= 30:
            (dae if cy < BANDS[0] else hot if cy < BANDS[1] else kwae)[wl == k + 1] = True
    allowed = L & ~thick & ~dae

    def grow(seed, other):
        s = ndi.binary_dilation(ndi.binary_fill_holes(seed), iterations=45, mask=allowed & ~other)
        holes = ndi.binary_fill_holes(s) & ~s
        return (s | (holes & ~thick)) & L

    Hm = grow(hot, kwae)
    Km = grow(kwae, Hm) & ~Hm
    T = Hm | Km
    vis = L & ~T
    # ellipse fitted to the logo outline on the oval's left/right sides
    edge = L & ~ndi.binary_erosion(L)
    ys, xs = np.nonzero(edge)
    sel = ((xs < W * 0.215) | (xs > W * 0.79)) & (ys > H * 0.29) & (ys < H * 0.88)
    x, y = xs[sel].astype(float), ys[sel].astype(float)
    (A, B, C, D), *_ = np.linalg.lstsq(np.stack([x * x, y * y, x, y], 1), np.ones_like(x), rcond=None)
    cx, cy = -C / (2 * A), -D / (2 * B)
    F = 1 + A * cx * cx + B * cy * cy
    yy, xx = np.mgrid[0:H, 0:W]
    E = ((xx - cx) ** 2) * A / F + ((yy - cy) ** 2) * B / F <= 1
    above = vis & ~E & (yy < cy)
    al, an = ndi.label(above)
    tab = ndi.binary_fill_holes(al == (np.argmax(ndi.sum(above, al, range(1, an + 1))) + 1))
    Fill = ndi.binary_fill_holes(E | tab)
    dT = ndi.distance_transform_edt(~T)
    d = ndi.distance_transform_edt(Fill)
    daem = ndi.binary_dilation(ndi.binary_fill_holes(dae), iterations=3)
    keep = Fill & vis & ((greenish & (dT > 6)) | tab | (d <= 13) | daem)
    S = 4
    h4, w4 = H // S, W // S
    known = (keep & greenish & ~daem & (d > 14))[:h4 * S, :w4 * S].reshape(h4, S, w4, S).all(axis=(1, 3))
    inside = Fill[:h4 * S, :w4 * S].reshape(h4, S, w4, S).any(axis=(1, 3))
    col = orig[:h4 * S, :w4 * S, :3].reshape(h4, S, w4, S, 3).mean(axis=(1, 3))
    u = np.where(known[..., None], col, col[known].mean(0))
    for _ in range(3000):
        nb = (np.roll(u, 1, 0) + np.roll(u, -1, 0) + np.roll(u, 1, 1) + np.roll(u, -1, 1)) / 4
        u = np.where((inside & ~known)[..., None], nb, u)
    pred = np.zeros((H, W, 3))
    pred[:h4 * S, :w4 * S] = np.repeat(np.repeat(u, S, 0), S, 1)
    pred = np.stack([ndi.gaussian_filter(pred[..., c], 3) for c in range(3)], -1)
    oval = np.zeros((H, W, 4))
    oval[..., :3] = np.where(keep[..., None], orig[..., :3], pred)
    ring = Fill & ~keep
    oval[ring & (d <= 3), :3] = (5, 5, 5)
    oval[ring & (d > 3) & (d <= 12), :3] = (250, 250, 250)
    oval[..., 3] = np.where(Fill, 255, 0)

    def layer(mask):
        out = orig.copy()
        out[..., 3] = np.where(mask, 255, 0)
        return out

    layers = {"oval": oval, "hot": layer(Hm), "kwae": layer(Km)}
    comp = Image.fromarray(oval.astype(np.uint8))
    for k in ("hot", "kwae"):
        comp.alpha_composite(Image.fromarray(layers[k].astype(np.uint8)))
    diff = np.abs(np.asarray(comp).astype(int)[..., :3] - orig[..., :3]).max(-1)
    return layers, float((diff[L] > 30).mean())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=ROOT / "assets" / "gfx" / "title_ko.png")
    ap.add_argument("--out", default=ROOT / "assets" / "gfx")
    a = ap.parse_args(argv)
    layers, mismatch = derive(pathlib.Path(a.src))
    for name, arr in layers.items():
        Image.fromarray(arr.astype(np.uint8)).resize((768, 512), Image.LANCZOS).save(
            pathlib.Path(a.out) / f"title_layer_{name}.png", optimize=True)
    print(f"layers written; recomposite mismatch {mismatch:.3%} of logo pixels (rebuilt oval under text)")


if __name__ == "__main__":
    main()
