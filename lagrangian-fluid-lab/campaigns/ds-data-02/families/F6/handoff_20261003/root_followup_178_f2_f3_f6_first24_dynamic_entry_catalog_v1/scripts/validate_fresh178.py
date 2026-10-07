#!/usr/bin/env python3
"""Read-only validator for fresh178's metadata-only dynamic entry catalog."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys


PACKAGE = pathlib.Path(__file__).resolve().parents[1]
CATALOG = PACKAGE / "metadata/dynamic-entry-catalog.json"
ALLOWED = {".json", ".xml", ".xmf", ".png"}
FORBIDDEN = {".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvsm", ".gif"}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"fresh178 validation failed: {message}")


def main() -> int:
    if not CATALOG.exists():
        fail(f"missing catalog {CATALOG}")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if catalog.get("schema") != "ds02.f6.fresh178.first24-dynamic-entry-catalog.v1":
        fail("schema")
    rows = catalog.get("rows")
    if not isinstance(rows, list) or len(rows) != 72:
        fail(f"expected 72 rows, got {len(rows) if isinstance(rows, list) else type(rows)}")
    counts = {family: sum(row.get("family_id") == family for row in rows) for family in ("F2", "F3", "F6")}
    if counts != {"F2": 24, "F3": 24, "F6": 24}:
        fail(f"family row counts {counts}")
    expected_frames = {"F2": 401, "F3": 836, "F6": 241}
    seen = set()
    for row in rows:
        family = row.get("family_id")
        physical = row.get("physical_case_id")
        if (family, physical) in seen:
            fail(f"duplicate row {family}/{physical}")
        seen.add((family, physical))
        if row.get("first24_member") is not True:
            fail(f"row outside first24 {family}/{physical}")
        if row.get("evidence_scope", {}).get("new_visual_review") is not False:
            fail(f"new visual review flag {family}/{physical}")
        if row.get("evidence_scope", {}).get("scientific_payload_read_or_hashed") is not False:
            fail(f"scientific payload flag {family}/{physical}")
        if row.get("evidence_scope", {}).get("case_credit") != 0:
            fail(f"case credit {family}/{physical}")
        report = row.get("actual_render_report", {}).get("metadata", {})
        if report.get("frames") != expected_frames[family]:
            fail(f"frame count {family}/{physical}: {report.get('frames')}")
        if report.get("all_frames_rendered") is not True:
            fail(f"all_frames_rendered {family}/{physical}")
        for key in ("actual_render_report", "actual_xmf_manifest", "actual_xmf_xml"):
            if not row.get(key, {}).get("ref", row.get(key, {})).get("path"):
                fail(f"missing {key} {family}/{physical}")
        if not row.get("contact_png_refs") or not row.get("key_png_refs"):
            fail(f"missing contact/key refs {family}/{physical}")
        refs = list(row.get("all_allowed_refs", [])) + list(row.get("native_request_role_snapshot", {}).get("allowed_evidence_refs", []))
        for ref in refs:
            path = pathlib.Path(ref["path"])
            if path.suffix.lower() in FORBIDDEN or path.suffix.lower() not in ALLOWED:
                fail(f"forbidden ref {path}")
            if not path.exists():
                fail(f"missing ref {path}")
            actual = sha256(path)
            if actual != ref.get("sha256"):
                fail(f"SHA mismatch {path}")
            if path.stat().st_size != ref.get("bytes"):
                fail(f"size mismatch {path}")
    membership = catalog.get("membership", {})
    if membership.get("F2", {}).get("first8_count") != 8 or membership.get("F2", {}).get("first24_count") != 24:
        fail("F2 membership counts")
    if membership.get("F3", {}).get("first8_count") != 8 or membership.get("F3", {}).get("first24_count") != 24:
        fail("F3 membership counts")
    if membership.get("F6", {}).get("first8_count") != 8 or membership.get("F6", {}).get("first24_count") != 24:
        fail("F6 membership counts")
    if catalog.get("policy", {}).get("new_case_credit") != 0:
        fail("policy credit")
    if catalog.get("policy", {}).get("scientific_payload_read_or_hashed") is not False:
        fail("policy payload")
    print(json.dumps({"valid": True, "rows": len(rows), "families": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
