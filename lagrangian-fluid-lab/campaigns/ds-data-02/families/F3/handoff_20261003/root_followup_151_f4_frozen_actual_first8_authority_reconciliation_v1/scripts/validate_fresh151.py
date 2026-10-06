#!/usr/bin/env python3
"""Metadata-only validator for fresh151; no scientific payload or image I/O."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = json.loads((ROOT / "metadata/f4-first8-authority-reconciliation.json").read_text())
assert META["schema"] == "ds02.f3.fresh151.f4-frozen-actual-first8-authority-reconciliation.v1"
assert META["fresh_id"] == "fresh151"
assert META["claim_boundary"]["ordering"].startswith("source row order")
assert META["claim_boundary"]["global_count_or_ledger_write"] is False
for key in ("scientific_arrays_read", "scientific_payloads_hashed", "PNG_or_render_payloads_read", "scientific_jobs_started", "shared_registry_or_ledger_written"):
    assert META["payload_guards"][key] is False, (key, META["payload_guards"][key])

# Verify only the JSON metadata sources named by this package.  No source path may
# point at a scientific payload or an image.
for source in META["source_references"]:
    path = Path(source["path"])
    assert path.suffix == ".json", path
    assert path.exists(), path
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == source["sha256"], (path, source["sha256"], actual)

frozen_rows = META["frozen_root1093"]["rows_source_order"]
historical_rows = META["historical_candidate_first8"]["rows_source_order"]
exact_rows = META["current_exact24"]["rows_source_order"]
accepted_rows = META["current_accepted48"]["rows_source_order"]

def ids(rows):
    return [row.get("physical_case_id") or row.get("membership_key") for row in rows]

frozen = ids(frozen_rows)
historical = ids(historical_rows)
exact = ids(exact_rows)
accepted = ids(accepted_rows)
assert len(frozen) == len(set(frozen)) == 8
assert len(historical) == len(set(historical)) == 8
assert len(exact) == len(set(exact)) == 24
assert len(accepted) == len(set(accepted)) == 48
assert all(x for x in frozen + historical + exact + accepted)
assert set(frozen) <= set(accepted)
assert set(exact) <= set(accepted)
assert len(set(frozen) & set(historical)) == 2
assert len(set(frozen) & set(exact)) == 5
assert len(set(frozen) - set(exact)) == 3
assert len(set(historical) & set(exact)) == 0

checks = META["set_comparisons"]
assert checks["frozen_actual_first8_vs_historical_candidate_first8"]["intersection_count"] == 2
assert checks["frozen_actual_first8_vs_current_exact24"]["intersection_count"] == 5
assert checks["frozen_actual_first8_vs_current_exact24"]["left_subset_right"] is False
assert checks["frozen_actual_first8_vs_current_accepted48"]["intersection_count"] == 8
assert checks["frozen_actual_first8_vs_current_accepted48"]["left_subset_right"] is True
assert checks["historical_candidate_first8_vs_current_exact24"]["intersection_count"] == 0
assert checks["current_exact24_vs_current_accepted48"]["intersection_count"] == 24
assert checks["current_exact24_vs_current_accepted48"]["left_subset_right"] is True
assert META["f3_visual_priority"]["new_unaccepted_eligible_case_found"] is False
print("fresh151 metadata contract: PASS")
