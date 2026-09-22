from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f8_static_review_bundle_v2 import OUTPUT, build_bundle


ROOT = Path(__file__).resolve().parents[1]


def test_v2_bundle_records_startup_and_parser_extensions_without_admission() -> None:
    bundle = build_bundle()
    assert bundle["schema"] == "core.cfd.f8.static_review_bundle.v2"
    assert bundle["status"] == "static_review_bundle_v2_pending_root_decision"
    assert bundle["qualification_credit"] == 0
    assert bundle["parser_contract"]["status"] == "implemented_static_parser_no_source_present"
    assert bundle["transient_boundary"]["startup_oracle_available"] is True
    assert bundle["transient_boundary"]["cfd_weakly_compressible_startup_evidence_required"] is True
    assert bundle["execution_controls"]["definition_written"] is False
    assert bundle["execution_controls"]["solver_invoked"] is False
    assert bundle["execution_controls"]["registry_mutation"] == 0
    assert len(bundle["bindings"]) == 13


def test_committed_v2_bundle_closes_every_extension_hash() -> None:
    assert OUTPUT.is_file()
    bundle = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert bundle["schema"] == "core.cfd.f8.static_review_bundle.v2"
    for row in bundle["bindings"]:
        path = ROOT / row["path"]
        assert path.is_file(), row["path"]
        assert path.stat().st_size == row["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
