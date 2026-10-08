from __future__ import annotations

import json
from pathlib import Path


MANIFEST = (
    Path(__file__).parents[1]
    / "campaigns/ds-data-02/stage2/requests/f2-s1-fine-domain-expanded-xyz-forward-control-v1.json"
)


def test_forward_control_is_source_bound_and_does_not_duplicate_primary002() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.stage2.f2-s1-fine-domain-control.v2"
    assert manifest["launch_allowed"] is False
    assert manifest["prior_actual"]["attempt_id"] == "f2-s1-fine-domain-expanded-xyz-v2-primary-001"
    assert manifest["control_closure"]["numeric_domain_only"] is True
    assert manifest["control_closure"]["invariants"]["initial_bi4_reused_without_rescale"] is True
    assert manifest["control_closure"]["invariants"]["wetted_wall_or_physical_geometry_changed"] is False
    assert manifest["mass_policy"]["denominator_is_frozen"] is True
    assert manifest["mass_policy"]["does_not_grant_QN_or_QE"] is True
    assert manifest["qualification"]["physical_fate"] == "UNKNOWN"
    assert manifest["qualification"]["dynamical_impact"] == "UNKNOWN"

