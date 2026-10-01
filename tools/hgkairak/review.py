"""Review records for graphics defined in code (build.GRAPHICS and the title strip).

translation/graphics_review.json holds one entry per code-defined graphic: kind, a text summary for the
reviewer, a fingerprint (spec + asset bytes) and the review state. The build fails when the table and the
code disagree (missing/extra ids, stale fingerprint), so a reviewed graphic cannot change silently; release
builds also require every entry to be distribution_eligible. `khpatch.py sync-review` refreshes the table and
resets changed entries to needs_review.
"""
import hashlib
import json
import pathlib

SCHEMA = "hgkairak-graphics-review/1"
STATES = ("untranslated", "in_progress", "needs_review", "needs_human_review", "distribution_eligible")
PROTECTED = ("id", "kind", "summary", "fingerprint")
FIELDS = set(PROTECTED) | {"state", "note"}
TITLE_ID = "title_logo"


class ReviewError(ValueError):
    pass


def _summary(spec) -> str:
    if "items" in spec:
        return " / ".join("\n".join(i["lines"]) for i in spec["items"])
    return "\n".join(spec.get("lines", []))


def _digest(obj, files=()) -> str:
    h = hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=repr).encode("utf-8"))
    for f in files:
        h.update(pathlib.Path(f).read_bytes())
    return h.hexdigest()


def catalog(specs, title_layers, title_params, assets_dir) -> dict[str, dict]:
    """id -> {kind, summary, fingerprint} for every code-defined graphic (title included when layers are given)."""
    out = {}
    for spec in specs:
        if spec["id"] in out:
            raise ReviewError(f"duplicate graphics id {spec['id']!r}")
        files = [pathlib.Path(assets_dir) / spec["image"]] if "image" in spec else []
        out[spec["id"]] = {"kind": spec["type"], "summary": _summary(spec), "fingerprint": _digest(spec, files)}
    if title_layers:
        files = [pathlib.Path(assets_dir) / p for _, p in sorted(title_layers.items())]
        out[TITLE_ID] = {"kind": "title", "summary": "타이틀 로고 오프닝 (" + ", ".join(sorted(title_layers.values())) + ")",
                         "fingerprint": _digest([sorted(title_layers.items()), title_params], files)}
    return out


def read(path) -> list[dict]:
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise ReviewError(f"unknown review schema {doc.get('schema')!r}")
    ids = [e.get("id") for e in doc["entries"]]
    if len(ids) != len(set(ids)):
        raise ReviewError("duplicate review ids")
    for e in doc["entries"]:
        if set(e) != FIELDS or not all(isinstance(e[k], str) for k in FIELDS):
            raise ReviewError(f"{e.get('id')}: bad field set or non-string field")
        if e["state"] not in STATES:
            raise ReviewError(f"{e['id']}: unknown state {e['state']!r}")
    return doc["entries"]


def check(entries, cat, policy) -> dict:
    have = {e["id"]: e for e in entries}
    missing, extra = sorted(set(cat) - set(have)), sorted(set(have) - set(cat))
    if missing or extra:
        raise ReviewError(f"graphics review table out of sync: missing {missing}, extra {extra} (run sync-review)")
    stale = sorted(i for i, c in cat.items() if any(have[i][k] != c[k] for k in ("kind", "summary", "fingerprint")))
    if stale:
        raise ReviewError(f"graphics review entries stale (spec or asset changed): {stale} (run sync-review)")
    if policy == "release":
        bad = sorted(i for i, e in have.items() if e["state"] != "distribution_eligible")
        if bad:
            raise ReviewError(f"release policy: graphics review not all distribution_eligible: {bad}")
    return {s: sum(e["state"] == s for e in entries) for s in STATES}


def sync(path, cat) -> dict:
    path = pathlib.Path(path)
    old = {e["id"]: e for e in read(path)} if path.exists() else {}
    entries, added, reset = [], [], []
    for i in sorted(cat):
        c = cat[i]
        e = old.get(i)
        if e is None:
            added.append(i)
            e = {"id": i, **c, "state": "needs_review", "note": ""}
        elif any(e[k] != c[k] for k in ("kind", "summary", "fingerprint")):
            reset.append(i)
            e = {"id": i, **c, "state": "needs_review", "note": (e["note"] + "; " if e["note"] else "") + "사양 변경으로 재검수"}
        entries.append({k: e[k] for k in ("id", "kind", "summary", "fingerprint", "state", "note")})
    removed = sorted(set(old) - set(cat))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA, "entries": entries}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"added": added, "reset": reset, "removed": removed}
