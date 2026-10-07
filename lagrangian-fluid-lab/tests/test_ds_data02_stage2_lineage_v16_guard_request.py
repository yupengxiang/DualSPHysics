from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ds_data02_stage2_lineage_v16_guard_request as request_builder  # noqa: E402


REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/v16-provisional/"
    "CURRENT336-effective-lineage-audit-v16-provisional-guard-request-001.json"
)


def _canonical(value: dict) -> str:
    body = dict(value)
    body.pop("sha256", None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def test_v16_guard_request_binds_actual_cards_and_keeps_raw_plan_planned() -> None:
    value = json.loads(REQUEST.read_text())
    assert value["schema"] == "ds02.request.v1"
    assert value["status"] == "READY_FOR_PARENT_GUARD"
    assert value["lineage_scope"]["case_count"] == 336
    assert value["lineage_scope"]["split_safe"] is False
    assert value["execution_contract"]["hdf5_or_bi4_read"] is False
    assert value["sha256"] == _canonical(value)
    assert len(value["actual_source_worker_outputs"]["cards"]) == 7
    assert value["planned_followups"][0]["status"].startswith("PLANNED_ONLY")
    assert value["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_v16_guard_request_input_hashes_are_exact_and_present() -> None:
    value = json.loads(REQUEST.read_text())
    assert set(value["input_files"]) == set(value["input_hashes"])
    for path_text in value["input_files"]:
        path = Path(path_text)
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == value["input_hashes"][path_text]


def test_v16_builder_rejects_promoting_planned_raw_output(tmp_path: Path) -> None:
    report = ROOT / "campaigns/ds-data-02/stage2/lineage/v16-provisional/CURRENT336-effective-lineage-audit-v16-provisional.json"
    planned = json.loads(report.read_text())
    # The builder must continue to bind the immutable report, rather than
    # accepting a report that claims the raw route already executed.
    planned["audit_scope"]["hdf5_or_bi4_read"] = True
    bad = tmp_path / "bad-report.json"
    bad.write_text(json.dumps(planned))
    try:
        request_builder.build(bad, tmp_path / "request.json")
    except request_builder.V16GuardRequestError as error:
        assert "metadata-only" in str(error)
    else:
        raise AssertionError("raw/BI4 promotion must be rejected")
