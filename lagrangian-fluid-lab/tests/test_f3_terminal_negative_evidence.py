from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "campaigns/core-v1/material/evidence/f3-adapter-rows29-31-terminal-negative-evidence-20260920.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_terminal_material_rows_are_hash_bound_negative_evidence() -> None:
    report = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert report["schema"] == "core.material.f3.native_volume_mls.terminal_negative_evidence.v1"
    assert report["T2_macro"] is False
    assert report["registered_unknown_fraction_threshold"] == 0.01
    assert report["central_ledger_mutation"] is False
    assert report["gpu_started"] is False
    assert [row["row"] for row in report["rows"]] == [29, 31]

    comparison = ROOT / report["comparison"]
    assert _sha256(comparison) == report["comparison_sha256"]
    for row in report["rows"]:
        assert row["status"] == "completed"
        assert row["mass_closed"] is True
        assert row["unknown_fraction_max"] > report["registered_unknown_fraction_threshold"]
        for key in ("summary", "trace", "execution_receipt"):
            binding = row[key]
            path = ROOT / binding["path"]
            assert path.is_file()
            assert path.stat().st_size == binding["bytes"]
            assert _sha256(path) == binding["sha256"]
