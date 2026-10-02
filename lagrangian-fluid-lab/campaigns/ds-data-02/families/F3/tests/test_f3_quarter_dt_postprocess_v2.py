"""Tests for the terminal-bound F3 quarter labels/comparison handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HANDOFF = Path(__file__).resolve().parents[1] / "handoff_20261003/quarter_dt_postprocess_v2"
DATA = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT_NVME_POSTPROCESS_V2/"
    "quarter-dt-nvme-labels-comparison-20261003-004"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_request_binds_terminal_conversion_and_keeps_nvme_h5_out_of_runtime_hash_pass():
    request_path = HANDOFF / "quarter_dt_nvme_postprocess_request_v3.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["attempt_id"] == "quarter-dt-nvme-labels-comparison-20261003-004"
    assert request["runnable"] is True
    assert request["gpu_launch"]["allowed"] is False
    assert request["q_n_status"] == "not_assessed"
    assert request["terminal_hdf5_binding"]["bytes"] == 6579413360
    assert request["terminal_hdf5_binding"]["sha256"] == "3bf79fbf1ab0859c9dac7c0a52142c3e8048c5036322fdc542b23c66d04c9619"
    assert request["terminal_hdf5_binding"]["path"] not in request["input_files"]
    assert request["terminal_conversion_report_sha256"] == "7aad92ac3952b0f7f48045c1a8072e92a0e116d560efa990ab0f891568f23e62"
    assert request["terminal_conversion_receipt_sha256"] == "d2cc0d8495378258cfda7d6eb595ea91bfc71f036c1d16e874c9fdab5c382c6f"


def test_actual_postprocess_receipt_and_outputs_are_complete_but_unqualified():
    receipt = json.loads((DATA / "execution-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["returncode"] == 0
    assert receipt["gpu_seconds"] == 0.0
    result = json.loads((DATA / "nvme-postprocess.json").read_text(encoding="utf-8"))
    assert result["copy_verified_before_scientific_read"] is True
    assert result["original_stat_unchanged"] is True
    assert result["private_scratch_removed"] is True
    assert result["source_hdf5_sha256"] == "3bf79fbf1ab0859c9dac7c0a52142c3e8048c5036322fdc542b23c66d04c9619"
    assert result["labels"]["producer_result"]["frames"] == 4001
    assert result["labels"]["producer_result"]["identities"] == 108000
    assert result["labels"]["producer_result"]["q_n_status"] == "not_assessed"
    assert result["q_n_status"] == "not_assessed"


def test_final_evidence_preserves_real_half_comparison_and_censoring():
    evidence = json.loads((HANDOFF / "quarter_dt_nvme_postprocess_final_evidence_v1.json").read_text(encoding="utf-8"))
    comparison = json.loads((DATA / "quarter-vs-half-transport-comparison.json").read_text(encoding="utf-8"))
    variant = next(iter(comparison["variants"].values()))
    assert evidence["q_n_status"] == "not_assessed"
    assert evidence["comparison_summary"]["frames_base"] == 4001
    assert evidence["comparison_summary"]["frames_variant"] == 4001
    assert evidence["comparison_summary"]["qualification_status"] == "not_assessed"
    assert any(row["censored_mass_kg"]["variant"] > 0 for row in variant["event_brackets"])
    assert evidence["labels"]["sha256"] == sha256(DATA / "typed-transport-labels.h5")
    assert evidence["comparison"]["sha256"] == sha256(DATA / "quarter-vs-half-transport-comparison.json")
