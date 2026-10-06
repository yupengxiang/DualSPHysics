#!/usr/bin/env python3
"""Metadata-only validation for F3 fresh145; never opens scientific payloads."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[0].parent
REPORT = PACKAGE / "metadata/f3-registered-render-wait-audit.json"
PROBE = PACKAGE / "metadata/current-pid-tick-probe.json"
FORBIDDEN = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtp", ".pvtu", ".pvd"}

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    report=json.loads(REPORT.read_text())
    probe=json.loads(PROBE.read_text())
    assert report["schema"].endswith("registered-render-wait-audit.v1")
    assert report["eligible_terminal_completed0_count"] == 0
    assert report["case_credit_granted"] is False
    assert report["review_limits"]["scientific_payload_read_or_hashed"] is False
    assert report["review_limits"]["jobs_started"] is False
    assert report["review_limits"]["shared_state_modified"] is False
    assert len(report["candidates"]) == report["waiting_candidate_count"]
    assert len(probe["controllers"]) == len(report["candidates"])
    for c in report["candidates"]:
        assert c["render_status"].startswith("registered_")
        assert c["terminal_receipt_path"] is None
        assert c["controller_result_path"] is None
        assert c["published"] is False
        assert c["case_credit_granted"] is False
        for item in (c["request_json"], c["wrapper_json"], c["launch_json"]):
            p=Path(item["path"])
            assert p.exists(), p
            assert digest(p) == item["sha256"], p
            assert p.suffix.lower() not in FORBIDDEN, p
        ident=c["controller_identity"]
        assert ident["present"] is True
        assert ident["ticks_match"] is True
    assert report["preserved_original154_role"]["original_conversion_receipt_status"] == "running"
    assert report["preserved_original154_role"]["original_conversion_receipt_returncode_field_present"] is False
    print(f"fresh145 metadata validation PASS: {len(report['candidates'])} registered waits; 0 eligible")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
