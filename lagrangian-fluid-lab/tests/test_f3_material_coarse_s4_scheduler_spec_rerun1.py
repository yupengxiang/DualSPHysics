"""Minimal identity/schema checks for the additive F3 coarse s4 RERUN1 spec."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from scripts import core_runtime


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s4-rerun1.json"
HISTORICAL_SPEC = ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s4.json"
S2_RERUN_SPEC = ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s2-rerun1.json"
LAB = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab"
SOURCE = f"{LAB}/campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5"


def _spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_s4_rerun1_is_additive_and_schema_valid() -> None:
    value = _spec()
    checked = core_runtime.validate_spec(deepcopy(value))

    assert checked["schema"] == "core.material.job.v1"
    assert checked["job_id"] == "core-f3-material-coarse-s4-rerun1"
    assert checked["logical_id"] == "CORE-F3-MATERIAL-COARSE-s4-RERUN1"
    assert checked["attempt_role"] == "rerun1"
    assert checked["lineage"]["historical_spec_reuse_forbidden"] is True
    assert checked["lineage"]["historical_spec_path"] == (
        "campaigns/core-v1/material/jobs/core-f3-material-coarse-s4.json"
    )
    assert checked["lineage"]["historical_spec_sha256"] == (
        "89a376b36c3d8c31c8b050b6bbd5a3aa6014d1877c7d7d918ed7cb4eeb889c1b"
    )
    assert SPEC_PATH != HISTORICAL_SPEC
    assert SPEC_PATH.read_bytes() != HISTORICAL_SPEC.read_bytes()


def test_s4_rerun1_binds_current_s4_command_inputs_resources_and_fresh_namespace() -> None:
    value = _spec()

    assert value["cwd"] == LAB
    assert value["argv"] == [
        f"{LAB}/.venv/bin/python",
        "-m",
        "scripts.core_material",
        "--source",
        SOURCE,
        "--output",
        "{attempt_dir}/material.h5",
        "--seeds",
        "512",
        "--substeps",
        "4",
        "--neighbour-variant",
        "baseline24",
    ]
    assert value["resources"] == {
        "cpu_cores": 2,
        "gpu_peak_mib": 0,
        "io_weight": 0.1,
        "ram_mib": 4096,
    }

    inputs = {item["path"]: item for item in value["input_files"]}
    assert len(inputs) == len(value["input_files"])
    assert inputs[SOURCE]["sha256"] == "3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575"
    assert inputs[f"{LAB}/scripts/core_material.py"]["sha256"] == "9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e"
    assert inputs[f"{LAB}/scripts/core_runtime.py"]["sha256"] == "a4c6e03a13cb1ff80c0da7f7f9bd442e5e2de4d64e23551bf92a0220c6afa8c4"
    assert inputs[str(HISTORICAL_SPEC)]["sha256"] == value["lineage"]["historical_spec_sha256"]

    namespace = value["namespace"]
    assert namespace["attempt_root"].endswith("/attempts/core-f3-material-coarse-s4-rerun1")
    assert namespace["template"].endswith("/core-f3-material-coarse-s4-rerun1/<fresh-attempt-id>")
    assert namespace["attempt_id_source"] == "scheduler_generated"
    assert namespace["fresh_required"] is True
    assert namespace["historical_reuse_forbidden"] is True
    assert namespace["same_attempt_resume_only"] is True
    assert namespace["path_is_metadata_only"] is True
    assert not (ROOT / namespace["attempt_root"]).exists()


def test_s4_rerun1_is_not_s2_intake_and_preserves_diagnostic_gates() -> None:
    value = _spec()
    s2 = json.loads(S2_RERUN_SPEC.read_text(encoding="utf-8"))

    assert value["job_id"] != s2["job_id"]
    assert value["namespace"]["attempt_root"] != s2["namespace"]["attempt_root"]
    assert value["lineage"]["historical_spec_path"] != s2["lineage"]["historical_spec_path"]
    assert value["qualification_claim"] == "none; diagnostic matrix only"
    assert value["execution_policy"] == {
        "mode": "diagnostic_only",
        "submit_is_non_authorizing": True,
        "unknown_gate": {
            "per_source_unknown_fraction_max": 0.01,
            "evaluated_only_from_terminal_material_receipt": True,
            "submit_does_not_evaluate": True,
            "unknown_or_right_censored_is_zero_credit": True,
        },
    }
    assert value["external_admission"] == {
        "fresh_root_receipt_required": True,
        "scheduler_host_io_receipt_required": True,
        "cross_bind_current_source_and_inputs": True,
        "one_shot_namespace_required": True,
        "launch_authority_minted_by_this_spec": False,
    }
