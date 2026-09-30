"""Extraction to the translation table and the primary product build."""
import hashlib
import struct
import io
import json
import os
import pathlib
import tempfile
import zipfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import charmap, graphics, layout, source, textblock, title
from .writeplan import WritePlan

SCHEMA = "hgkairak-dialogue/1"
STATES = ("untranslated", "in_progress", "needs_review", "needs_human_review", "distribution_eligible")
PROTECTED = ("id", "addr", "refs", "capacity", "line_cells", "source_codes", "source")
EDITABLE = ("ko", "state", "note")
GLYPH_INK, GLYPH_BG = 1, 15   # pixel values of source font glyphs (checked against source at build)


# Graphics-text assets (docs/initial-survey.md §10). Coordinates are sprite-sheet pixels.
# Re-derived for this revision; the first game's addresses do not apply.
TEXT_FONT = "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf"
MYEONGJO_XB = "/usr/share/fonts/truetype/nanum/NanumMyeongjoExtraBold.ttf"
MODE_LABEL = {"type": "photo_label", "palette_rom": 0x6A190, "detect": "dark_halo", "halo_px": 4,
              "fill": (0, 0, 0), "outline": (255, 255, 255), "outline_px": 3}   # mode select photos, bank 8
# Ending credits (option A, user decision 2026-09-30): Japanese names -> Hangul readings (card romaji where present,
# otherwise common readings — PROVISIONAL), Latin names kept, role titles translated.
PLATE_LABEL = {"type": "photo_label", "palette_rom": 0x69D90, "detect": "solid", "bg": (0, 0, 0),
               "fill": (255, 255, 255), "outline": None, "outline_px": 0, "squeeze": True}   # opponent select name plates, bank 8
GRAPHICS: list[dict] = [
    {"id": "credit_direction", "type": "credit_page", "sheet": {"tiles": (0x00737, 0x007C3), "w": 10, "h": 14}, "palette_rom": 0x68D90,
     "items": [
        {"box": (146, 10, 252, 36), "lines": ["제작/감독"], "align": "left", "size": 22},
        {"box": (204, 37, 306, 59), "lines": ["나카무라 신스케"], "align": "left", "size": 22},
        {"box": (146, 61, 252, 86), "lines": ["기획/각본"], "align": "left", "size": 22},
        {"box": (204, 87, 306, 109), "lines": ["야마다 케이시"], "align": "left", "size": 22},
        {"box": (146, 110, 262, 136), "lines": ["프로그램"], "align": "left", "size": 22},
        {"box": (204, 137, 306, 160), "lines": ["사이토 시오리"], "align": "left", "size": 22},
        {"box": (146, 161, 262, 186), "lines": ["디자인/연출"], "align": "left", "size": 22},
        {"box": (204, 187, 306, 210), "lines": ["오가와 효에"], "align": "left", "size": 22}]},
    {"id": "credit_design", "type": "credit_page", "sheet": {"tiles": (0x0084F, 0x008DB), "w": 10, "h": 14}, "palette_rom": 0x68D90,
     "items": [
        {"box": (103, 9, 192, 35), "lines": ["디자인"], "align": "left", "size": 22},
        {"box": (13, 35, 104, 58), "lines": ["츠카코시 요코"], "align": "left", "size": 22},
        {"box": (13, 62, 104, 86), "lines": ["타니구치 에미"], "align": "left", "size": 22},
        {"box": (13, 90, 104, 114), "lines": ["후지타 케이조"], "align": "left", "size": 22},
        {"box": (13, 118, 104, 142), "lines": ["이와부치 요스케"], "align": "left", "size": 22},
        {"box": (106, 73, 193, 97), "lines": ["카지카와 마사시"], "align": "left", "size": 22},
        {"box": (106, 101, 193, 125), "lines": ["마에다 야스츠구"], "align": "left", "size": 22},
        {"box": (106, 129, 193, 153), "lines": ["사카모토 사치코"], "align": "left", "size": 22},
        {"box": (106, 157, 193, 181), "lines": ["노하라 신지"], "align": "left", "size": 22},
        {"box": (106, 185, 193, 209), "lines": ["코타니 토모유키"], "align": "left", "size": 22}]},
    {"id": "credit_chardesign", "type": "credit_page", "sheet": {"tiles": (0x00967, 0x009F3), "w": 10, "h": 14}, "palette_rom": 0x68D90,
     "items": [
        {"box": (54, 6, 260, 31), "lines": ["캐릭터 디자인"], "align": "center", "size": 22},
        {"box": (15, 44, 142, 67), "lines": ["이노우에 타쿠야"], "align": "right", "size": 22},
        {"box": (15, 96, 142, 119), "lines": ["쿠가야마 리카코"], "align": "right", "size": 22},
        {"box": (15, 122, 142, 145), "lines": ["카토 레이지로"], "align": "right", "size": 22},
        {"box": (15, 148, 142, 171), "lines": ["카루마 타츠로"], "align": "right", "size": 22},
        {"box": (15, 173, 142, 197), "lines": ["코토부키 카즈키"], "align": "right", "size": 22},
        {"box": (198, 70, 306, 93), "lines": ["도만 세이만"], "align": "left", "size": 22},
        {"box": (198, 96, 306, 119), "lines": ["토키사카 무기"], "align": "left", "size": 22},
        {"box": (198, 122, 306, 145), "lines": ["후미즈키 코우"], "align": "left", "size": 22},
        {"box": (198, 148, 306, 171), "lines": ["모리나가 밀크"], "align": "left", "size": 22},
        {"box": (198, 174, 306, 197), "lines": ["요키히"], "align": "left", "size": 22}]},
    {"id": "credit_guest", "type": "credit_page", "sheet": {"tiles": (0x00A7F, 0x00B0B), "w": 10, "h": 14}, "palette_rom": 0x68D90,
     "items": [
        {"box": (3, 9, 148, 38), "lines": ["게스트 캐릭터 디자인"], "align": "left", "size": 20},
        {"box": (200, 14, 300, 39), "lines": ["촬영 협력"], "align": "left", "size": 22},
        {"box": (40, 83, 131, 106), "lines": ["츠카사 준"], "align": "right", "size": 22},
        {"box": (20, 111, 131, 135), "lines": ["나카무라 히로후미"], "align": "right", "size": 22},
        {"box": (15, 139, 125, 163), "lines": ["무라타 렌지"], "align": "right", "size": 22},
        {"box": (200, 55, 300, 78), "lines": ["유사 신이치"], "align": "left", "size": 22},
        {"box": (196, 99, 310, 119), "lines": ["이가라시 노리유키"], "align": "left", "size": 20},
        {"box": (196, 120, 310, 134), "lines": ["(작 아메리카)"], "align": "right", "size": 13},
        {"box": (196, 149, 310, 169), "lines": ["코타니 토모유키"], "align": "left", "size": 20},
        {"box": (196, 170, 310, 185), "lines": ["(작 재팬)"], "align": "right", "size": 13}]},
    {"id": "credit_voice", "type": "credit_page", "sheet": {"tiles": (0x00B97, 0x00C23), "w": 10, "h": 14}, "palette_rom": 0x68D90,
     "items": [
        {"box": (112, 18, 202, 43), "lines": ["목소리 출연"], "align": "center", "size": 22},
        {"box": (13, 56, 126, 81), "lines": ["아사미 준코"], "align": "right", "size": 22},
        {"box": (13, 84, 126, 108), "lines": ["이마하시 카츠요"], "align": "right", "size": 22},
        {"box": (13, 112, 126, 136), "lines": ["오오타니 이쿠에"], "align": "right", "size": 22},
        {"box": (13, 139, 126, 164), "lines": ["오리카사 아이"], "align": "right", "size": 22},
        {"box": (13, 168, 126, 193), "lines": ["카츠키 마사코"], "align": "right", "size": 22},
        {"box": (188, 56, 306, 81), "lines": ["코오로기 사토미"], "align": "left", "size": 22},
        {"box": (188, 84, 306, 108), "lines": ["타카다 유미"], "align": "left", "size": 22},
        {"box": (188, 112, 306, 136), "lines": ["타나카 아츠코"], "align": "left", "size": 22},
        {"box": (188, 139, 306, 164), "lines": ["야지마 아키코"], "align": "left", "size": 22},
        {"box": (188, 168, 306, 193), "lines": ["와카모토 노리오"], "align": "left", "size": 22}]},
    {"id": "credit_final", "type": "credit_page", "sheet": {"tiles": (0x00CAF, 0x00D3B), "w": 10, "h": 14}, "palette_rom": 0x68D90,
     "items": [
        {"box": (158, 44, 300, 69), "lines": ["협력"], "align": "left", "size": 22},
        {"box": (158, 73, 306, 99), "lines": ["와니 매거진사"], "align": "left", "size": 22},
        {"box": (158, 114, 300, 139), "lines": ["제작/저작"], "align": "left", "size": 22},
        {"box": (158, 144, 300, 169), "lines": ["1998 사이쿄"], "align": "left", "size": 22}]},
    {"id": "namecard_00", "type": "name_card", "template": "074A7C+074A84+074A8C", "palette_rom": 0x6AD90, "cut": 43, "lines": ["후미즈키 코우"]},
    {"id": "namecard_01", "type": "name_card", "template": "074A94+074A9C+074AA4", "palette_rom": 0x6AD90, "cut": 43, "lines": ["토키사카 무기"]},
    {"id": "namecard_02", "type": "name_card", "template": "074AAC+074AB4+074ABC", "palette_rom": 0x6AD90, "cut": 43, "lines": ["카루마 타츠로"]},
    {"id": "namecard_03", "type": "name_card", "template": "074AC4+074ACC+074AD4", "palette_rom": 0x6AD90, "cut": 43, "lines": ["모리나가 밀크"]},
    {"id": "namecard_04", "type": "name_card", "template": "074ADC+074AE4+074AEC", "palette_rom": 0x6AD90, "cut": 43, "lines": ["이노우에 타쿠야"]},
    {"id": "namecard_05", "type": "name_card", "template": "074AF4+074AFC+074B04", "palette_rom": 0x6AD90, "cut": 43, "lines": ["쿠가야마 리카코"]},
    {"id": "namecard_07", "type": "name_card", "template": "074B24+074B2C+074B34", "palette_rom": 0x6AD90, "cut": 43, "lines": ["도만 세이만"]},
    {"id": "namecard_08", "type": "name_card", "template": "074B3C+074B44+074B4C", "palette_rom": 0x6AD90, "cut": 43, "lines": ["카토 레이지로"]},
    {"id": "namecard_09", "type": "name_card", "template": "074B54+074B5C+074B64", "palette_rom": 0x6AD90, "cut": 43, "lines": ["코토부키 카즈키"]},
    {"id": "namecard_11", "type": "name_card", "template": "074B84+074B8C+074B94", "palette_rom": 0x6AD90, "cut": 43, "lines": ["요키히"]},
    {"id": "mode_versus", "sheet": (0x148B0, 8, 9), "band": (4, 106, 123, 143), "lines": ["통신 대전"], **MODE_LABEL},
    {"id": "mode_versus_lit", "sheet": (0x14820, 8, 9), "band": (4, 106, 123, 143), "lines": ["통신 대전"], **MODE_LABEL},
    {"id": "mode_versus_f3", "sheet": (0x14868, 8, 9), "band": (4, 106, 123, 143), "lines": ["통신 대전"], **MODE_LABEL},
    {"id": "plate_makoto", "sheet": (0x1457D, 5, 9), "band": (13, 119, 79, 143), "lines": ["후지쿠라 마코토"], **PLATE_LABEL},
    {"id": "plate_noromi", "sheet": (0x145AA, 5, 9), "band": (13, 119, 79, 143), "lines": ["노로타 노로미"], **PLATE_LABEL},
    {"id": "plate_yaeko", "sheet": (0x145D7, 5, 9), "band": (13, 119, 79, 143), "lines": ["타카기 야에코"], **PLATE_LABEL},
    {"id": "plate_mea", "sheet": (0x1463A, 5, 9), "band": (13, 119, 79, 143), "lines": ["메아"], **PLATE_LABEL},
    {"id": "plate_miki", "sheet": (0x14667, 5, 9), "band": (13, 119, 79, 143), "lines": ["쿠로다 미키"], **PLATE_LABEL},
    {"id": "plate_mayu", "sheet": (0x14694, 5, 9), "band": (13, 119, 79, 143), "lines": ["코이누바라 마유"], **PLATE_LABEL},
    {"id": "plate_meruru", "sheet": (0x146F7, 5, 9), "band": (13, 119, 79, 143), "lines": ["메루루"], **PLATE_LABEL},
    {"id": "plate_m1", "sheet": (0x14724, 5, 9), "band": (13, 119, 79, 143), "lines": ["M-1호"], **PLATE_LABEL},
    {"id": "plate_osuzu", "sheet": (0x14751, 5, 9), "band": (13, 119, 79, 143), "lines": ["오스즈"], **PLATE_LABEL},
    {"id": "plate_yurika", "sheet": (0x147A2, 7, 9), "band": (13, 119, 111, 143), "lines": ["산노 유리카"], **PLATE_LABEL},
    {"id": "plate_penguin", "sheet": (0x147E1, 7, 9), "band": (13, 119, 111, 143), "lines": ["펭귄 학대녀"], **PLATE_LABEL},
    {"id": "mode_single", "sheet": (0x14920, 8, 4), "band": (4, 18, 123, 62), "lines": ["1인 플레이"], **MODE_LABEL},
]
# Styles for translated graphics text (translation/graphics_text.json). Palettes are ROM copies of the scene palette bank
# (bank 6 = main 0x68BD0, identical to palette RAM in every observed scene).
BANK6 = 0x68BD0
TEXT_STYLES: dict[str, dict] = {
    "bubble": {"kind": "box", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(17, 32)), "fill": 31, "inset": 2,
               "font": MYEONGJO_XB, "sizes": (30, 28, 26, 24, 22, 20, 18, 16, 14), "color": (255, 255, 255), "line_gap": 1},
    "outline": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(1, 16)), "transparent": 0,
                "font": TEXT_FONT, "sizes": tuple(range(24, 11, -1)), "color": (244, 244, 244),
                "outline": (16, 16, 16), "outline_px": 2, "line_gap": 0, "align": "center", "margin": 2},
    "outline_left": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(1, 16)), "transparent": 0,
                     "font": TEXT_FONT, "sizes": tuple(range(24, 11, -1)), "color": (244, 244, 244),
                     "outline": (16, 16, 16), "outline_px": 2, "line_gap": 0, "align": "left", "margin": 2},
    "outline_thin": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(1, 16)), "transparent": 0,
                     "font": TEXT_FONT, "sizes": tuple(range(16, 9, -1)), "color": (244, 244, 244),
                     "outline": (16, 16, 16), "outline_px": 1, "line_gap": 0, "align": "center", "margin": 1},
    "grade_serif": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(33, 48)), "transparent": 0,
                    "font": MYEONGJO_XB, "sizes": tuple(range(32, 9, -1)), "color": (255, 255, 255), "outline": None,
                    "outline_px": 0, "line_gap": 0, "align": "center", "margin": 1, "antialias": True,
                    "blend_bg": (8, 93, 121), "alpha_cut": 40},   # white over the table teal (indices 33-47 = white..teal)
    "grade_gothic": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(33, 48)), "transparent": 0,
                     "font": TEXT_FONT, "sizes": tuple(range(32, 9, -1)), "color": (255, 255, 255), "outline": None,
                     "outline_px": 0, "line_gap": 0, "align": "center", "margin": 1, "antialias": True,
                     "blend_bg": (8, 93, 121), "alpha_cut": 40},
    "glyph01": {"kind": "twotone", "col": 0x06, "font": "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                "sizes": (15, 14, 13, 12, 11, 10), "align": "center", "margin": 0, "roles": (0, 1, 1)},   # 1-bit score font
    "wind_serif": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(17, 32)), "transparent": 0,
                   "font": MYEONGJO_XB, "sizes": tuple(range(16, 9, -1)), "color": (255, 255, 255), "outline": None,
                   "outline_px": 0, "line_gap": 0, "align": "center", "margin": 0, "antialias": True,
                   "blend_bg": (8, 93, 121), "alpha_cut": 40},   # 東場 marker, one glyph per 16px tile
    "tile_label": {"kind": "box", "col": 0x20, "palette_rom": 0x67D90, "indices": "used", "fill": 78, "inset": 0,
                   "font": "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "sizes": (14, 13, 12, 11),
                   "color": (247, 247, 243), "line_gap": 2, "antialias": True},
    "mono_white": {"kind": "outline", "col": 0x00, "fixed_palette": {65: (255, 255, 255)}, "indices": (65,), "transparent": 0,
                   "font": TEXT_FONT, "sizes": tuple(range(16, 9, -1)), "color": (255, 255, 255), "outline": None,
                   "outline_px": 0, "line_gap": 1, "align": "center", "margin": 1},
    "wind_small": {"kind": "twotone", "col": 0x00, "font": "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
                   "sizes": (14, 13, 12, 11), "align": "center", "margin": 1, "roles": (0, 12, 15), "outer": True},
    "outline_coin": {"kind": "outline", "col": 0x06, "palette_rom": BANK6, "indices": tuple(range(1, 16)) + (50,),
                     "transparent": 0, "font": TEXT_FONT, "sizes": tuple(range(24, 11, -1)), "color": (244, 244, 244),
                     "outline": (16, 16, 16), "outline_px": 2, "line_gap": 0, "align": "center", "margin": 2},
}
GFX_SCHEMA = "hgkairak-graphics-text/1"
TITLE_STRIP = True   # rebuild the attract title logo animation from assets (title.py)


class TranslationError(ValueError):
    pass


# ---------------------------------------------------------------- translation records

def extraction_record(e: textblock.Entry) -> dict:
    return {
        "id": e.id, "addr": f"{e.addr:06X}", "refs": [f"{r:06X}" for r in e.refs],
        "capacity": e.capacity, "line_cells": e.line_cells,
        "source_codes": " ".join(f"{c:04X}" for c in e.codes), "source": charmap.decode(e.codes),
        "ko": "", "state": "untranslated", "note": "",
    }


def validate_record(rec: dict) -> None:
    unknown = set(rec) - set(PROTECTED) - set(EDITABLE)
    missing = (set(PROTECTED) | set(EDITABLE)) - set(rec)
    if unknown or missing:
        raise TranslationError(f"{rec.get('id')}: bad field set unknown={sorted(unknown)} missing={sorted(missing)}")
    if rec["state"] not in STATES:
        raise TranslationError(f"{rec['id']}: unknown state {rec['state']!r}")
    if rec["state"] != "untranslated" and not rec["ko"]:
        raise TranslationError(f"{rec['id']}: state {rec['state']} without ko text")
    if rec["state"] == "untranslated" and rec["ko"]:
        raise TranslationError(f"{rec['id']}: ko text present but state is untranslated")


def merge_record(base: dict, old: dict) -> dict:
    validate_record(old)
    diff = [k for k in PROTECTED if base[k] != old[k]]
    if diff:
        raise TranslationError(f"{base['id']}: protected fields differ from extraction: {diff}")
    return dict(base, **{k: old[k] for k in EDITABLE})


def read_table(path) -> dict:
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise TranslationError(f"unknown schema {doc.get('schema')!r}")
    ids = [r["id"] for r in doc["entries"]]
    if len(ids) != len(set(ids)):
        raise TranslationError("duplicate entry ids")
    for r in doc["entries"]:
        validate_record(r)
    return doc


def extract(source_path, table_path) -> dict:
    files = source.load(source_path)
    image = layout.cpu_image(files[layout.MAIN_CHIPS[0]], files[layout.MAIN_CHIPS[1]])
    entries = textblock.load_entries(image)
    for e in entries:   # unchanged round trip: parse -> tokens/text -> serialize == source bytes
        raw = image[e.addr:e.addr + e.capacity * 2]
        if textblock.serialize(e, e.codes) != raw or charmap.encode_source(charmap.decode(e.codes)) != e.codes:
            raise TranslationError(f"{e.id}: round trip failed")
    records = [extraction_record(e) for e in entries]
    table_path = pathlib.Path(table_path)
    if table_path.exists():
        old = {r["id"]: r for r in read_table(table_path)["entries"]}
        stale = set(old) - {r["id"] for r in records}
        if stale:
            raise TranslationError(f"entries missing from new extraction: {sorted(stale)}")
        records = [merge_record(r, old[r["id"]]) if r["id"] in old else r for r in records]
    doc = {"schema": SCHEMA,
           "source": {**{c: source.PROFILE[c][1] for c in layout.MAIN_CHIPS},
                      "block": [f"{textblock.BLOCK_START:06X}", f"{textblock.BLOCK_END:06X}"]},
           "entries": records}
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- write helpers

def add_mapped(plan: WritePlan, writer: str, mapper, base: int, expected: bytes, final: bytes) -> None:
    """Register a write given in a logical view (CPU / gfx region), coalesced into file runs."""
    run = None
    for i in range(len(final)):
        f, off = mapper(base + i)
        if run and run[0] == f and run[1] + len(run[2]) == off:
            run[2].append(expected[i]); run[3].append(final[i])
        else:
            if run:
                plan.add(writer, run[0], run[1], bytes(run[2]), bytes(run[3]))
            run = [f, off, bytearray([expected[i]]), bytearray([final[i]])]
    if run:
        plan.add(writer, run[0], run[1], bytes(run[2]), bytes(run[3]))


def rasterize(ch: str, font_path, size: int, ink: int = GLYPH_INK, bg: int = GLYPH_BG) -> bytes:
    font = ImageFont.truetype(str(font_path), size)
    top = font.getbbox("한")[1]
    im = Image.new("L", (16, 16), 0)
    x = (16 - font.getlength(ch)) / 2
    y = (16 - (font.getbbox("한")[3] - top)) / 2 - top
    if font.getlength(ch) > 16:
        raise ValueError(f"glyph {ch!r} wider than 16px at size {size}")
    draw = ImageDraw.Draw(im)
    draw.fontmode = "1"   # hinted monochrome: keeps final ㅁ/ㅇ distinct at 15px
    draw.text((x, y), ch, font=font, fill=255)
    return bytes(ink if im.getpixel((px, py)) >= 128 else bg for py in range(16) for px in range(16))


def region_read(files: dict[str, bytes], off: int, n: int) -> bytes:
    return bytes(files[f][o] for f, o in (layout.gfx_offset_to_file(off + i) for i in range(n)))


# ---------------------------------------------------------------- product build

def template(image: bytes, addr: int) -> tuple[int, int, int, int]:
    """Sprite template: dword0 = h-1|y|w-1|x, dword1 = col|flags|tnum (as in the first game)."""
    geo, attr = struct.unpack_from(">II", image, addr)
    return attr & 0x7FFFF, ((geo >> 12) & 0xF) + 1, ((geo >> 28) & 0xF) + 1, (attr >> 24) & 0x3F


def fit_text(lines, font, sizes, width, height, color, line_gap, outline=None, outline_px=0, antialias=True,
             align="center", margin=0, check=None):
    for size in sizes:
        try:
            art = graphics.text_art(lines, font, size, width, height, color, outline, outline_px, line_gap,
                                    antialias=antialias, align=align, margin=margin)
            if check:
                check(art)
            return art
        except graphics.GraphicsError:
            continue
    raise graphics.GraphicsError(f"text does not fit {width}x{height} at any size: {lines}")


TEMPLATE_AREA = (0x67000, 0x77000)   # sprite template tables in the main ROM (docs/initial-survey.md 10.3)
GFX_TILES = layout.GFX_SIZE // 256


def template_canvas(image: bytes, spec: str):
    parts = []
    if spec.startswith("S:"):          # direct sprite without a template: S:<tnum>:<w>x<h>:<col>
        try:
            _, t, wh, c = spec.split(":")
            w, h = (int(v) for v in wh.split("x"))
            tnum, col = int(t, 16), int(c, 16)
        except ValueError as err:
            raise TranslationError(f"bad direct sprite spec {spec!r}") from err
        if not (1 <= w <= 16 and 1 <= h <= 16 and 0 <= tnum and tnum + w * h <= GFX_TILES and 0 <= col < 0x40):
            raise TranslationError(f"direct sprite spec out of range: {spec!r}")
        return graphics.Canvas(((tnum, w, h, 0, 0),)), {col}
    for a in spec.split("+"):
        try:
            addr = int(a, 16)
        except ValueError as err:
            raise TranslationError(f"bad template address {a!r}") from err
        if addr % 8 != 4 or not TEMPLATE_AREA[0] <= addr <= TEMPLATE_AREA[1] - 8:   # 8-byte records at 4 mod 8
            raise TranslationError(f"template address {addr:#x} outside the template tables")
        geo, attr = struct.unpack_from(">II", image, addr)
        if attr & 0x00C00000:   # flipped parts would be drawn mirrored; not supported
            raise TranslationError(f"template {addr:#x} uses flip bits")
        tnum, w, h, col = template(image, addr)
        x, y = geo & 0x3FF, (geo >> 16) & 0x3FF
        if tnum + w * h > GFX_TILES:
            raise TranslationError(f"template {addr:#x} tiles out of range")
        parts.append((tnum, w, h, x - 0x400 if x & 0x200 else x, y - 0x400 if y & 0x200 else y, col))
    mx, my = min(p[3] for p in parts), min(p[4] for p in parts)
    return graphics.Canvas(tuple((t, w, h, x - mx, y - my) for t, w, h, x, y, _ in parts)), {p[5] for p in parts}


def render_graphics_text(files, image, entry):
    style = TEXT_STYLES[entry["style"]]
    sheet, cols = template_canvas(image, entry["template"])
    if cols != {style["col"]}:
        raise RuntimeError(f"{entry['id']}: template palette {sorted(cols)} != style palette {style['col']:#x}")
    rows = sheet.read(lambda off, n: region_read(files, off, n))
    if style["kind"] == "glyph":
        return sheet, rows, glyph_rows(sheet, rows, entry)
    if style["kind"] == "twotone":
        bg, fill, edge = style.get("roles") or graphics.twotone_roles(rows)
        present = {v for r in rows for v in r if v is not None}
        if not {bg, fill, edge} <= present | {0}:
            raise RuntimeError(f"{entry['id']}: two-tone roles {bg, fill, edge} not all used by the source")
        lines = entry["ko"].split("\n")

        def mask(art):
            m = art.getchannel("A")
            return m.filter(ImageFilter.MaxFilter(3)) if style.get("bold") else m

        def check(art):
            graphics.compose_twotone(rows, mask(art), bg, fill, edge, outer=style.get("outer", False))
        art = fit_text(lines, style["font"], style["sizes"], sheet.width, sheet.height, (255, 255, 255),
                       style.get("line_gap", 0), None, 0, False, style["align"], style["margin"], check)
        return sheet, rows, graphics.compose_twotone(rows, mask(art), bg, fill, edge, outer=style.get("outer", False))
    if style.get("indices") == "used":
        style = dict(style, indices=tuple(sorted({v for r in rows for v in r if v})))
    stray = {v for r in rows for v in r if v is not None} - set(style["indices"]) - {0}
    if stray:
        raise RuntimeError(f"{entry['id']}: unexpected palette indices {sorted(stray)}")
    pal = style.get("fixed_palette") or graphics.rom_palette(image, style["palette_rom"], style["indices"])
    lines = entry["ko"].split("\n")
    if style["kind"] == "outline":
        cut, bg = style.get("alpha_cut", 128), style.get("blend_bg")

        def check(art):
            graphics.compose_text(rows, art, pal, style["transparent"], cut, bg)
        art = fit_text(lines, style["font"], style["sizes"], sheet.width, sheet.height, style["color"], style["line_gap"],
                       style["outline"], style["outline_px"], style.get("antialias", False), style["align"],
                       style["margin"], check)
        return sheet, rows, graphics.compose_text(rows, art, pal, style["transparent"], cut, bg)
    erase = graphics.text_box(rows, style["fill"], 0)
    i = style["inset"]
    box = (erase[0] + i, erase[1] + i, erase[2] - i, erase[3] - i)
    art = fit_text(lines, style["font"], style["sizes"], box[2] - box[0] + 1, box[3] - box[1] + 1,
                   style["color"], style["line_gap"], antialias=style.get("antialias", True))
    return sheet, rows, graphics.compose_box(rows, art, box, style["fill"], pal, erase)


GLYPH_FONT = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"


def _graphics_fonts() -> set[str]:
    return {TEXT_FONT, MYEONGJO_XB, GLYPH_FONT} | {st["font"] for st in TEXT_STYLES.values() if "font" in st}


def glyph_rows(sheet, rows, entry):
    """One score-font glyph per 16x16 cell (ink 1 / bg 15, like the dialogue font)."""
    if {v for r in rows for v in r if v is not None} - {GLYPH_INK, GLYPH_BG}:
        raise RuntimeError(f"{entry['id']}: not a font-glyph tile")
    chars = entry["ko"]
    if any(v is None for r in rows for v in r):
        raise RuntimeError(f"{entry['id']}: glyph entries must be a single full sprite")
    cells = [(x, y) for y in range(0, sheet.height, 16) for x in range(0, sheet.width, 16)]
    if len(chars) != len(cells):
        raise RuntimeError(f"{entry['id']}: {len(chars)} chars for {len(cells)} cells")
    out = [list(r) for r in rows]
    for ch, (cx, cy) in zip(chars, cells):
        t = rasterize(ch, GLYPH_FONT, 15)
        for i, v in enumerate(t):
            out[cy + i // 16][cx + i % 16] = v
    return out


def read_gfx_table(path) -> list[dict]:
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != GFX_SCHEMA:
        raise TranslationError(f"unknown graphics schema {doc.get('schema')!r}")
    ids = [e["id"] for e in doc["entries"]]
    if len(ids) != len(set(ids)):
        raise TranslationError("duplicate graphics entry ids")
    for e in doc["entries"]:
        if set(e) != {"id", "template", "style", "source", "ko", "state", "note"}:
            raise TranslationError(f"{e.get('id')}: bad field set")
        if not all(isinstance(e[k], str) for k in e):
            raise TranslationError(f"{e.get('id')}: all fields must be strings")
        if e["state"] not in STATES or e["style"] not in TEXT_STYLES:
            raise TranslationError(f"{e['id']}: unknown state/style")
        if (e["state"] == "untranslated") == bool(e["ko"]):
            raise TranslationError(f"{e['id']}: ko/state mismatch")
    return doc["entries"]


def graphics_text_writes(plan, files, image, entries) -> dict:
    report = {}
    for e in entries:
        if e["state"] == "untranslated":
            continue
        sheet, old, new = render_graphics_text(files, image, e)
        old_t, new_t = sheet.encode(old), sheet.encode(new)
        changed = {tn: t for tn, t in new_t.items() if t != old_t[tn]}
        for tn, t in changed.items():
            add_mapped(plan, f"gtext:{e['id']}:{tn:05X}", layout.gfx_offset_to_file, tn * 256, old_t[tn], t)
        report[e["id"]] = {"tiles_written": len(changed), "_tiles": changed}
    return report


def photo_label_writes(plan, files, image, spec) -> dict:
    """Text over a photo: detect old text pixels in the band, inpaint them, draw outlined Korean text."""
    tnum, w, h = spec["sheet"]
    sheet = graphics.SpriteSheet((tnum,), w, h)
    rows = sheet.read(lambda off, n: region_read(files, off, n))
    used = sorted({v for r in rows for v in r})
    pal = graphics.rom_palette(image, spec["palette_rom"], used)
    rgb = [[pal[v] for v in r] for r in rows]
    x0, y0, x1, y1 = spec["band"]
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    bright = lambda c: lum(c) > 200 and max(c) - min(c) < 40
    band = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    if spec.get("detect") == "dark_halo":   # dark text + the bright halo within halo_px of it (keeps other white areas)
        dark = {(x, y) for x, y in band if lum(rgb[y][x]) < 45}
        r = spec.get("halo_px", 3)
        near = {(x + dx, y + dy) for x, y in dark for dx in range(-r, r + 1) for dy in range(-r, r + 1)}
        core = dark | {(x, y) for x, y in band if (x, y) in near and bright(rgb[y][x])}
    elif spec.get("detect") == "solid":   # flat text band (e.g. name plates): repaint the whole band
        core = set(band)
    else:
        core = {(x, y) for x, y in band if bright(rgb[y][x]) or lum(rgb[y][x]) < 45}
    mask = {(x + dx, y + dy) for x, y in core for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if x0 <= x + dx <= x1 and y0 <= y + dy <= y1}
    if spec.get("detect") == "solid":
        rgb = [[spec["bg"] if (x, y) in mask else c for x, c in enumerate(r)] for y, r in enumerate(rgb)]
    else:
        rgb = graphics.inpaint(rgb, mask)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if spec.get("squeeze"):
        art = graphics.squeezed_text_art(spec["lines"], spec.get("font", TEXT_FONT), range(30, 11, -1), bw, bh,
                                         spec.get("fill", (255, 255, 255)), spec.get("outline"), spec.get("outline_px", 0))
    else:
        art = fit_text(spec["lines"], spec.get("font", TEXT_FONT), tuple(range(30, 11, -1)), bw, bh,
                       spec.get("fill", (255, 255, 255)), 0, spec.get("outline", (0, 0, 0)), spec.get("outline_px", 2),
                       spec.get("antialias", False))
    new = [list(r) for r in rows]
    cache: dict[tuple, int] = {}
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            r, g, b, a = art.getpixel((x - x0, y - y0))
            c = (r, g, b) if a >= 128 else rgb[y][x]
            if (x, y) in mask or a >= 128:
                new[y][x] = cache.setdefault(c, graphics.nearest(pal, c))
    old_t, new_t = sheet.encode(rows), sheet.encode(new)
    written = {}
    for tn, t in new_t.items():
        if t != old_t[tn]:
            add_mapped(plan, f"photo:{spec['id']}:{tn:05X}", layout.gfx_offset_to_file, tn * 256, old_t[tn], t)
            written[tn] = t
    return {spec["id"]: {"tiles_written": len(written), "_tiles": written}}



def _tile_changes(plan, sheet, rows, new, writer) -> dict:
    old_t, new_t = sheet.encode(rows), sheet.encode(new)
    written = {}
    for tn, t in new_t.items():
        if t != old_t[tn]:
            add_mapped(plan, f"{writer}:{tn:05X}", layout.gfx_offset_to_file, tn * 256, old_t[tn], t)
            written[tn] = t
    return written


def name_card_writes(plan, files, image, spec) -> dict:
    """Attract name card: redraw the big name above `cut`, keep the romaji rows below it untouched."""
    sheet, _ = template_canvas(image, spec["template"])
    rows = sheet.read(lambda off, n: region_read(files, off, n))
    cut = spec["cut"]
    if any(rows[y][x] is None for y in range(cut) for x in range(sheet.width)):
        raise RuntimeError(f"{spec['id']}: name area not fully covered by the card parts")
    used = sorted({v for r in rows for v in r if v})
    pal = graphics.rom_palette(image, spec["palette_rom"], used)
    art = None
    for size in range(40, 13, -1):
        try:
            art = graphics.text_art(spec["lines"], TEXT_FONT, size, sheet.width, cut, (255, 255, 255), (0, 0, 0), 2,
                                    antialias=True)
            break
        except graphics.GraphicsError:
            continue
    if art is None:
        raise graphics.GraphicsError(f"{spec['id']}: name does not fit")
    new = [list(r) for r in rows]
    cache: dict[tuple, int] = {}
    for y in range(cut):
        for x in range(sheet.width):
            r, g, b, a = art.getpixel((x, y))
            new[y][x] = cache.setdefault((r, g, b), graphics.nearest(pal, (r, g, b))) if a >= 128 else 0
    w = _tile_changes(plan, sheet, rows, new, f"namecard:{spec['id']}")
    return {spec["id"]: {"tiles_written": len(w), "_tiles": w}}


def credit_page_writes(plan, files, image, spec) -> dict:
    """Full-screen credit page: each item box must hold only achromatic text on black; it is cleared and redrawn."""
    sheet = graphics.SpriteSheet(**spec["sheet"])
    rows = sheet.read(lambda off, n: region_read(files, off, n))
    used = sorted({v for r in rows for v in r})
    pal = graphics.rom_palette(image, spec["palette_rom"], used)
    black = min(used, key=lambda i: sum(pal[i]))
    new = [list(r) for r in rows]
    cache: dict[tuple, int] = {}
    for item in spec["items"]:
        x0, y0, x1, y1 = item["box"]
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                c = pal[rows[y][x]]
                if max(c) - min(c) > 40:
                    raise RuntimeError(f"{spec['id']}: non-text pixel in box {item['box']} at ({x},{y})")
                new[y][x] = black
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        art = graphics.squeezed_text_art(item["lines"], item.get("font", TEXT_FONT), range(item.get("size", 24), 7, -1),
                                         bw, bh, (255, 255, 255), antialias=True, min_ratio=0.6)
        box = art.getchannel("A").getbbox()
        if box and item.get("align", "center") != "center":   # squeezed art is centred; shift to the requested edge
            dx = -box[0] if item["align"] == "left" else bw - box[2]
            moved = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            moved.paste(art, (dx, 0))
            art = moved
        for y in range(bh):
            for x in range(bw):
                r, g, b, a = art.getpixel((x, y))
                if a:
                    k = tuple(round(c * a / 255 + f * (255 - a) / 255) for c, f in zip((r, g, b), pal[black]))
                    new[y0 + y][x0 + x] = cache.setdefault(k, graphics.nearest(pal, k))
    w = _tile_changes(plan, sheet, rows, new, f"credit:{spec['id']}")
    return {spec["id"]: {"tiles_written": len(w), "_tiles": w}}


def card_writes(plan, files, image, spec) -> dict:
    """Name card: sharp Korean card drawn at the last frame's size, blurred for the earlier frames."""
    reader = lambda off, n: region_read(files, off, n)
    sw, sh = spec["frames"][-1][1] * 16, spec["frames"][-1][2] * 16
    sharp = None
    for size in range(22, 11, -1):
        try:
            sharp = graphics.card_art(spec["lines"], spec["indents"], TEXT_FONT, size, sw, sh, margin=6)
            break
        except graphics.GraphicsError:
            continue
    if sharp is None:
        raise graphics.GraphicsError(f"{spec['id']}: card text does not fit")
    written: dict[int, bytes] = {}
    if len(spec["frames"]) != len(spec["blur"]):
        raise RuntimeError(f"{spec['id']}: frames/blur length mismatch")
    for (tnum, w, h), radius in zip(spec["frames"], spec["blur"]):
        sheet = graphics.SpriteSheet((tnum,), w, h)
        rows = sheet.read(reader)
        used = sorted({v for r in rows for v in r})
        if 0 in used:
            raise RuntimeError(f"{spec['id']}: card frame {tnum:#x} has transparent pixels")
        pal = graphics.rom_palette(image, spec["palette_rom"], used)
        canvas = Image.new("L", (w * 16, h * 16), 255)
        canvas.paste(sharp.crop((0, 0, min(sw, w * 16), min(sh, h * 16))), (0, 0))
        art = graphics.hblur(canvas, radius)
        cache: dict[int, int] = {}
        new = [[cache.setdefault(art.getpixel((x, y)), graphics.nearest(pal, (art.getpixel((x, y)),) * 3))
                for x in range(w * 16)] for y in range(h * 16)]
        old_t, new_t = sheet.encode(rows), sheet.encode(new)
        for tn, t in new_t.items():
            if t != old_t[tn]:
                add_mapped(plan, f"card:{spec['id']}:{tn:05X}", layout.gfx_offset_to_file, tn * 256, old_t[tn], t)
                written[tn] = t
    return {spec["id"]: {"tiles_written": len(written), "_tiles": written}}


def graphics_writes(plan, files, image, assets_dir) -> dict:
    report = {}
    reader = lambda off, n: region_read(files, off, n)
    for spec in GRAPHICS:
        if spec["type"] == "card":
            report.update(card_writes(plan, files, image, spec))
            continue
        if spec["type"] == "name_card":
            report.update(name_card_writes(plan, files, image, spec))
            continue
        if spec["type"] == "credit_page":
            report.update(credit_page_writes(plan, files, image, spec))
            continue
        if spec["type"] == "photo_label":
            report.update(photo_label_writes(plan, files, image, spec))
            continue
        if spec["type"] == "image":
            path = pathlib.Path(assets_dir) / spec["image"]
            data = path.read_bytes()
            art = Image.open(io.BytesIO(data))
            sheet = graphics.SpriteSheet(**spec["sheet"])
            rows = sheet.read(reader)
            pal = graphics.rom_palette(image, spec["palette_rom"], sorted({v for r in rows for v in r}))
            new = graphics.compose(rows, art, spec["box"], spec["bg"], pal, spec["alpha_cut"])
        else:
            data = "\n".join(spec["lines"]).encode("utf-8") + pathlib.Path(TEXT_FONT).read_bytes()
            sheet = graphics.Canvas(spec["parts"])
            rows = sheet.read(reader)
            allowed = set(spec["indices"]) | {spec["transparent"]}
            stray = {v for r in rows for v in r if v is not None} - allowed
            if stray:
                raise RuntimeError(f"{spec['id']}: source uses palette indices outside the declared set: {sorted(stray)}")
            art = graphics.text_art(spec["lines"], TEXT_FONT, spec["size"], sheet.width, sheet.height,
                                    spec["fill"], spec["outline"], spec["outline_px"], spec["line_gap"])
            pal = graphics.rom_palette(image, spec["palette_rom"], spec["indices"])
            new = graphics.compose_text(rows, art, pal, spec["transparent"], 128)
        old_t, new_t = sheet.encode(rows), sheet.encode(new)
        changed = {tn: t for tn, t in new_t.items() if t != old_t[tn]}
        for tn, t in changed.items():
            add_mapped(plan, f"gfx:{spec['id']}:{tn:05X}", layout.gfx_offset_to_file, tn * 256, old_t[tn], t)
        report[spec["id"]] = {"image_sha1": hashlib.sha1(data).hexdigest(), "tiles_written": len(changed), "_tiles": changed}
    return report


def build(source_path, table_path, out_dir, font_path, font_size=15, policy="development", assets_dir=None,
          gfx_table=None, version=None) -> dict:
    if policy not in ("development", "release"):
        raise ValueError(f"unknown policy {policy}")
    font_path = pathlib.Path(font_path)
    font_sha1 = hashlib.sha1(font_path.read_bytes()).hexdigest()
    table_sha1 = hashlib.sha1(pathlib.Path(table_path).read_bytes()).hexdigest()
    files = source.load(source_path)
    image = layout.cpu_image(files[layout.MAIN_CHIPS[0]], files[layout.MAIN_CHIPS[1]])
    entries = {e.id: e for e in textblock.load_entries(image)}
    table = read_table(table_path)
    recs = table["entries"]
    if {r["id"] for r in recs} != set(entries):
        raise TranslationError("translation table ids do not match current extraction")
    for r in recs:
        base = extraction_record(entries[r["id"]])
        diff = [k for k in PROTECTED if base[k] != r[k]]
        if diff:
            raise TranslationError(f"{r['id']}: protected fields differ from source: {diff}")
    if policy == "release":
        bad = [r["id"] for r in recs if r["state"] != "distribution_eligible"]
        if bad:
            raise TranslationError(f"release policy: {len(bad)} entries not distribution_eligible (e.g. {bad[:5]})")
    selected = [r for r in recs if r["state"] != "untranslated"]

    used = {c for e in entries.values() for c in e.codes if c < charmap.FONT_GLYPHS}
    slots = charmap.hangul_slots(used)

    plan = WritePlan(files)
    encoded, errors = {}, []
    for r in selected:
        e = entries[r["id"]]
        try:
            codes = textblock.encode_ko(e, r["ko"], slots)
        except textblock.LayoutError as err:
            errors.append(f"{r['id']}: {err}")
            continue
        encoded[r["id"]] = codes
        final = textblock.serialize(e, codes)
        if not textblock.BLOCK_START <= e.addr < e.addr + len(final) <= textblock.BLOCK_END:
            raise RuntimeError(f"{r['id']}: text write outside dialogue block")
        add_mapped(plan, f"text:{r['id']}", layout.main_addr_to_chip, e.addr,
                   image[e.addr:e.addr + len(final)], final)
    if errors:
        raise TranslationError("layout/encoding failures:\n  " + "\n  ".join(errors))

    needed = sorted({ch for r in selected for ch in r["ko"] if ch in slots}, key=slots.get)
    glyphs = {}
    for ch in needed:
        if not charmap.KANJI_START <= slots[ch] < charmap.FONT_GLYPHS:
            raise RuntimeError(f"glyph slot {slots[ch]:#x} outside font kanji area")
        off = (charmap.FONT_TILE_BASE + slots[ch]) * 256
        old = region_read(files, off, 256)
        if not set(old) <= {GLYPH_INK, GLYPH_BG}:
            raise RuntimeError(f"slot {slots[ch]:#x} is not a source font glyph tile")
        glyphs[ch] = rasterize(ch, font_path, font_size)
        add_mapped(plan, f"font:{slots[ch]:03X}", layout.gfx_offset_to_file, off, old, glyphs[ch])

    gfx = graphics_writes(plan, files, image, assets_dir) if assets_dir is not None else {}
    if assets_dir is not None and TITLE_STRIP:
        gfx.update(title.title_writes(plan, files, image, assets_dir, add_mapped, region_read,
                                      layout.main_addr_to_chip, layout.gfx_offset_to_file))
    if gfx_table is not None:
        gentries = read_gfx_table(gfx_table)
        if policy == "release" and any(e["state"] != "distribution_eligible" for e in gentries):
            raise TranslationError("release policy: graphics text not all distribution_eligible")
        gfx.update(graphics_text_writes(plan, files, image, gentries))

    out = plan.apply()

    # artifact verification: re-read output through the same views
    out_img = layout.cpu_image(bytes(out[layout.MAIN_CHIPS[0]]), bytes(out[layout.MAIN_CHIPS[1]]))
    for rid, codes in encoded.items():
        e = entries[rid]
        if out_img[e.addr:e.addr + e.capacity * 2] != textblock.serialize(e, codes):
            raise RuntimeError(f"{rid}: output verification failed")
    for rep_ in gfx.values():
        for tn, tile in rep_.pop("_tiles").items():
            if region_read(out, tn * 256, 256) != tile:
                raise RuntimeError(f"graphics tile {tn:#x}: output verification failed")
        if "_maps" in rep_ and title.read_strip(out_img, title.GEOMETRY) != rep_.pop("_maps"):
            raise RuntimeError("title strip: output verification failed")
    for ch, tile in glyphs.items():
        if region_read(out, (charmap.FONT_TILE_BASE + slots[ch]) * 256, 256) != tile:
            raise RuntimeError(f"glyph {ch}: output verification failed")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in source.PROFILE:
            z.writestr(name, bytes(out[name]))
    manifest = {
        "patch_version": version, "policy": policy, "distribution": policy == "release",
        "source_profile": {n: s for n, (_, s) in source.PROFILE.items()},
        "translation_table_sha1": table_sha1,
        "font": {"path": font_path.name, "sha1": font_sha1, "size": font_size},
        "graphics_fonts": {pathlib.Path(f).name: hashlib.sha1(pathlib.Path(f).read_bytes()).hexdigest()
                           for f in sorted(_graphics_fonts()) if pathlib.Path(f).exists()},
        "numpy": __import__("numpy").__version__,
        "pillow": Image.__version__ if hasattr(Image, "__version__") else __import__("PIL").__version__,
        "entries": {"total": len(recs), "applied": len(encoded), "by_state": {s: sum(r["state"] == s for r in recs) for s in STATES}},
        "glyphs_written": len(glyphs), "writes": len(plan.writes), "graphics": gfx,
        "output_sha1": {n: hashlib.sha1(bytes(out[n])).hexdigest() for n in source.PROFILE},
    }
    _publish(pathlib.Path(out_dir), {
        "hgkairak.zip": buf.getvalue(),
        "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8"),
    })
    return manifest


def _publish(out_dir: pathlib.Path, outputs: dict[str, bytes]) -> None:
    """Write all outputs to temp files first, then move them into place; stale outputs are removed first."""
    out_dir.mkdir(parents=True, exist_ok=True)
    temps = {}
    try:
        for name, data in outputs.items():
            fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=f".{name}.")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            temps[name] = tmp
        for name in outputs:
            (out_dir / name).unlink(missing_ok=True)
        for name, tmp in temps.items():
            os.replace(tmp, out_dir / name)
    finally:
        for tmp in temps.values():
            if os.path.exists(tmp):
                os.unlink(tmp)
