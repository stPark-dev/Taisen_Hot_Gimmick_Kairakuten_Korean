"""Review records for graphics defined in code (title, credits, plates, cards, labels): drift and release gate."""
import json

import pytest

from hgkairak import review

SPECS = [
    {"id": "plate_a", "type": "photo_label", "sheet": (0x100, 5, 9), "lines": ["가나"]},
    {"id": "credit_x", "type": "credit_page", "sheet": {"tiles": (1, 2), "w": 10, "h": 14},
     "items": [{"box": (0, 0, 9, 9), "lines": ["제작"]}, {"box": (0, 10, 9, 19), "lines": ["홍길동"]}]},
]


def _assets(tmp_path, data=b"layer"):
    d = tmp_path / "assets"
    (d / "gfx").mkdir(parents=True)
    for name in ("a.png", "b.png"):
        (d / "gfx" / name).write_bytes(data)
    return d


def test_catalog_lists_specs_and_title_with_summaries(tmp_path):
    cat = review.catalog(SPECS, title_layers={"x": "gfx/a.png", "y": "gfx/b.png"}, title_params=(1, 2),
                         assets_dir=_assets(tmp_path))
    assert set(cat) == {"plate_a", "credit_x", "title_logo"}
    assert cat["plate_a"]["summary"] == "가나"
    assert cat["credit_x"]["summary"] == "제작 / 홍길동"
    assert cat["title_logo"]["kind"] == "title"


def test_fingerprint_changes_with_spec_and_asset_bytes(tmp_path):
    a = review.catalog(SPECS, {"x": "gfx/a.png"}, (1,), _assets(tmp_path))
    b = review.catalog([dict(SPECS[0], lines=["다라"]), SPECS[1]], {"x": "gfx/a.png"}, (1,), _assets(tmp_path / "2"))
    c = review.catalog(SPECS, {"x": "gfx/a.png"}, (1,), _assets(tmp_path / "3", b"other"))
    assert a["plate_a"]["fingerprint"] != b["plate_a"]["fingerprint"]
    assert a["credit_x"]["fingerprint"] == b["credit_x"]["fingerprint"]
    assert a["title_logo"]["fingerprint"] != c["title_logo"]["fingerprint"]


def test_sync_creates_then_resets_changed_entries(tmp_path):
    path = tmp_path / "r.json"
    cat = review.catalog(SPECS, None, None, None)
    rep = review.sync(path, cat)
    assert rep == {"added": ["credit_x", "plate_a"], "reset": [], "removed": []}
    doc = json.loads(path.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        e["state"] = "distribution_eligible"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    cat2 = review.catalog([dict(SPECS[0], lines=["다라"]), SPECS[1]], None, None, None)
    rep = review.sync(path, cat2)
    assert rep["reset"] == ["plate_a"]
    states = {e["id"]: e["state"] for e in json.loads(path.read_text(encoding="utf-8"))["entries"]}
    assert states == {"plate_a": "needs_review", "credit_x": "distribution_eligible"}
    rep = review.sync(path, review.catalog(SPECS[:1], None, None, None))
    assert rep["removed"] == ["credit_x"]


def test_check_rejects_missing_extra_and_stale_entries(tmp_path):
    path = tmp_path / "r.json"
    cat = review.catalog(SPECS, None, None, None)
    review.sync(path, cat)
    entries = review.read(path)
    review.check(entries, cat, "development")
    with pytest.raises(review.ReviewError, match="missing"):
        review.check(entries[:1], cat, "development")
    with pytest.raises(review.ReviewError, match="stale"):
        review.check(entries, review.catalog([dict(SPECS[0], lines=["다라"]), SPECS[1]], None, None, None), "development")


def test_release_requires_every_entry_eligible(tmp_path):
    path = tmp_path / "r.json"
    cat = review.catalog(SPECS, None, None, None)
    review.sync(path, cat)
    with pytest.raises(review.ReviewError, match="release"):
        review.check(review.read(path), cat, "release")
    doc = json.loads(path.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        e["state"] = "distribution_eligible"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    review.check(review.read(path), cat, "release")


@pytest.mark.parametrize("bad", [{"state": "done"}, {"extra": 1}, {"fingerprint": 3}])
def test_read_rejects_malformed_entries(tmp_path, bad):
    path = tmp_path / "r.json"
    review.sync(path, review.catalog(SPECS, None, None, None))
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["entries"][0].update(bad)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(review.ReviewError):
        review.read(path)
