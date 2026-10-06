#!/usr/bin/env python3
"""Metadata-only validator for fresh150; does not read external science payloads."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = json.loads((ROOT / "audit.json").read_text())
assert AUDIT["schema"] == "ds02.f3.fresh150.cross-family-first8-first24-final48-membership-audit.v1"
assert AUDIT["claim_boundary"]["lexical_sorting_used"] is False
for key, value in AUDIT["payload_guards"].items():
    if key in {"scientific_arrays_read", "scientific_payloads_hashed", "PNG_or_render_payloads_read", "scientific_jobs_started", "shared_registry_or_ledger_written"}:
        assert value is False, (key, value)
assert AUDIT["families"]["F1"]["subset_checks"]["first8_subset_first24_by_case_id"] is True
assert AUDIT["families"]["F1"]["subset_checks"]["first24_subset_checkpoint_accepted_by_case_id"] is True
assert AUDIT["families"]["F4"]["subset_checks"]["first8_subset_first24"] == "undetermined_gap"
assert AUDIT["families"]["F4"]["subset_checks"]["first24_subset_checkpoint_accepted_by_physical_case_id"] is True
assert AUDIT["families"]["F7"]["subset_checks"]["first8_subset_first24_by_physical_case_id"] is True
assert AUDIT["families"]["F7"]["subset_checks"]["first24_subset_checkpoint_accepted_by_physical_case_id"] is True
for family in ("F1", "F4", "F7"):
    assert AUDIT["families"][family]["accepted_final48"]["count"] == 48
    assert AUDIT["families"][family]["accepted_final48"]["checkpoint_family_count"] == 48
print("fresh150 metadata contract: PASS")
