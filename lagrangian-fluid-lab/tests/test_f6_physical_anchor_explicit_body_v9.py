"""Evidence tests for the F6 explicit-body v9 support-volume preflight."""

from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v9-20260921"
OUTPUT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-cpu-native-preflight-v9-20260921"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v9_root_registers_continuous_volume_and_support_drawbox() -> None:
    contract = load(ROOT / "definition-contract.json")
    receipt = load(ROOT / "preflight.json")
    definition = next(ROOT.glob("*_Def.xml"))
    root = ET.parse(definition).getroot()
    drawbox = root.find("./casedef/geometry/commands/mainlist/drawbox")
    assert drawbox is not None
    size = drawbox.find("size")
    assert size is not None
    assert all(
        math.isclose(float(size.get(axis)), expected, rel_tol=0.0, abs_tol=1.0e-12)
        for axis, expected in zip("xyz", [1.12, 0.42, 0.22])
    )
    assert contract["fluid"]["size_m"] == [1.14, 0.44, 0.24]
    sampling = contract["fluid"]["sampling_contract"]
    assert sampling["mode"] == "endpoint_safe_support_centres"
    assert sampling["drawbox_size_m"] == [1.1199999999999999, 0.42, 0.22]
    assert sampling["continuous_volume_mass_gate"] is True
    assert receipt["status"] == "cpu_physical_anchor_preflight_pass"
    assert receipt["gate_passed"] is True
    assert receipt["checks"]["fluid_drawbox_binding"]["passed"] is True
    assert receipt["solver_canary_authorized_in_this_receipt"] is False
    assert receipt["qualification_credit"] == 0


def test_v9_native_preflight_passes_exactly_once_without_science_credit() -> None:
    receipt = load(OUTPUT / "preflight.json")
    assert receipt["status"] == "cpu_native_preflight_pass_exact_one"
    assert receipt["preflight_pass"] is True
    assert receipt["generated_groups"]["fluid"][0]["count"] == 15048
    assert receipt["generated_groups"]["fixed"][1]["kind"] == "floating"
    assert receipt["generated_groups"]["fixed"][1]["count"] == 693
    native = receipt["native"]
    assert native["fluid_particles"] == 15048
    assert abs(native["mass_error_relative"]) < 1.0e-12
    assert receipt["generated_body"]["massbody_kg"] == 2.9952
    assert receipt["generated_body"]["center_max_abs_error_m"] == 0.0
    assert receipt["generated_body"]["inertia_max_relative_error"] < 1.0e-5
    assert all(receipt["checks"].values())
    controls = receipt["execution_controls"]
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["job_created"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert receipt["same_input_retry"] is False
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
