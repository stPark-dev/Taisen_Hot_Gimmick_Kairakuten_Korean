"""Build helpers: mapped writes, glyph rasterizing, source profile checks, translation merge."""
import hashlib
import io
import zipfile

import pytest

from hgkairak import build, layout, source
from hgkairak.textblock import Entry
from hgkairak.writeplan import WritePlan

NANUM = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"


def test_add_mapped_writes_land_on_cpu_view():
    u22, u23 = bytes(16), bytes(16)
    plan = WritePlan({"1.u22": u22, "2.u23": u23})
    build.add_mapped(plan, "t", layout.main_addr_to_chip, 4, bytes(6), b"\x12\x34\x56\x78\x9a\xbc")
    out = plan.apply()
    img = layout.cpu_image(bytes(out["1.u22"]), bytes(out["2.u23"]))
    assert img[4:10] == b"\x12\x34\x56\x78\x9a\xbc"
    assert img[:4] == bytes(4) and img[10:] == bytes(len(img) - 10)


def test_add_mapped_coalesces_contiguous_file_runs():
    plan = WritePlan({"0l.u2": bytes(8), "0h.u11": bytes(8)})
    build.add_mapped(plan, "g", layout.gfx_offset_to_file, 0, bytes(8), bytes(range(1, 9)))
    assert len(plan.writes) == 4  # l,h,l,h runs of 2 bytes


@pytest.mark.skipif(not __import__("os").path.exists(NANUM), reason="font not installed")
def test_rasterize_glyph_uses_only_ink_and_background():
    tile = build.rasterize("가", NANUM, size=15, ink=1, bg=15)
    assert len(tile) == 256
    assert set(tile) == {1, 15}


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_source_rejects_hash_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(source, "PROFILE", {"a.bin": (4, hashlib.sha1(b"abcd").hexdigest())})
    p = tmp_path / "s.zip"
    p.write_bytes(_zip({"a.bin": b"abcx"}))
    with pytest.raises(source.SourceError, match="a.bin"):
        source.load(p)
    p.write_bytes(_zip({"a.bin": b"abcd"}))
    assert source.load(p) == {"a.bin": b"abcd"}


def test_source_rejects_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(source, "PROFILE", {"a.bin": (4, "0" * 40), "b.bin": (1, "0" * 40)})
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a.bin").write_bytes(b"abcd")
    with pytest.raises(source.SourceError, match="b.bin"):
        source.load(d)


def _entry():
    return Entry(addr=0x100, codes=[0x75, 0x76], capacity=4, refs=[0x10])


def test_merge_keeps_authored_fields_and_checks_protected():
    base = build.extraction_record(_entry())
    old = dict(base, ko="가", state="in_progress", note="n")
    merged = build.merge_record(base, old)
    assert (merged["ko"], merged["state"], merged["note"]) == ("가", "in_progress", "n")
    with pytest.raises(build.TranslationError, match="protected"):
        build.merge_record(base, dict(old, source_codes="0000"))


def test_record_rejects_unknown_state_and_fields():
    rec = dict(build.extraction_record(_entry()), state="done")
    with pytest.raises(build.TranslationError, match="state"):
        build.validate_record(rec)
    rec = dict(build.extraction_record(_entry()), extra=1)
    with pytest.raises(build.TranslationError, match="field"):
        build.validate_record(rec)
