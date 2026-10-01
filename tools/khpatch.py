#!/usr/bin/env python3
"""Taisen Hot Gimmick Kairakuten Korean patch — primary entry point.

  khpatch.py extract --source hgkairak.zip [--table translation/dialogue.json]
  khpatch.py build   --source hgkairak.zip [--table ...] [--out out] [--font F.ttf] [--policy development|release]
  khpatch.py sync-review    refresh translation/graphics_review.json from the code-defined graphics
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hgkairak import build, review  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEW_TABLE = ROOT / "translation" / "graphics_review.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("extract", "build"):
        p = sub.add_parser(name)
        p.add_argument("--source", required=True, help="hgkairak.zip or directory with the MAME set")
        p.add_argument("--table", default=ROOT / "translation" / "dialogue.json")
        if name == "build":
            p.add_argument("--out", default=ROOT / "out")
            p.add_argument("--font", default="/usr/share/fonts/truetype/nanum/NanumGothic.ttf")
            p.add_argument("--font-size", type=int, default=15)
            p.add_argument("--policy", choices=("development", "release"), default="development")
    sub.add_parser("sync-review")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "sync-review":
            rep = review.sync(REVIEW_TABLE, build.review_catalog(ROOT / "assets"))
            print(json.dumps(rep, ensure_ascii=False))
        elif a.cmd == "extract":
            doc = build.extract(a.source, a.table)
            print(f"extracted {len(doc['entries'])} entries -> {a.table}")
        else:
            m = build.build(a.source, a.table, a.out, a.font, a.font_size, a.policy, assets_dir=ROOT / "assets",
                              gfx_table=ROOT / "translation" / "graphics_text.json",
                              version=(ROOT / "VERSION").read_text().strip(), review_table=REVIEW_TABLE)
            print(json.dumps({k: m[k] for k in ("patch_version", "policy", "distribution", "entries", "glyphs_written", "writes", "graphics_review")}, ensure_ascii=False)); print("graphics items:", len(m["graphics"]), "tiles:", sum(v["tiles_written"] for v in m["graphics"].values()))
    except Exception as err:  # machine-detectable failure with scope in the message
        print(f"FAILED: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
