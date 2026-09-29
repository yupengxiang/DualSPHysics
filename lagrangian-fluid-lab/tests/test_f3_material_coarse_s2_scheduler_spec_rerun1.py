"""Minimal schema and identity checks for the additive F3 coarse RERUN1 spec."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from scripts import core_runtime


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s2-rerun1.json"
HISTORICAL_SPEC = ROOT / "campaigns/core-v1/material/jobs/core-f3-material-coarse-s2.json"
LAB = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab"
SOURCE = f"{LAB}/campaigns/l1-resume/data/continuation/R0081818-NOMINAL.h5"


def _spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_rerun1_spec_is_additive_and_core_runtime_validates_it() -> None:
    value = _spec()
    checked = core_runtime.validate_spec(deepcopy(value))

    assert checked["schema"] == "core.material.job.v1"
    assert checked["job_id"] == "core-f3-material-coarse-s2-rerun1"
    assert checked["logical_id"] == "CORE-F3-MATERIAL-COARSE-s2-RERUN1"
    assert checked["attempt_role"] == "rerun1"
    assert checked["job_id"] != "core-f3-material-coarse-s2"
    assert checked["lineage"]["historical_spec_reuse_forbidden"] is True
    assert checked["lineage"]["historical_spec_sha256"] == "1f1080e497feab414863e3e02dd31dbec91c0d09e4ef9ac855e0cdbbda070628"
    assert SPEC_PATH != HISTORICAL_SPEC
    assert SPEC_PATH.read_bytes() != HISTORICAL_SPEC.read_bytes()


def test_rerun1_binds_current_argv_cwd_inputs_resources_and_namespace() -> None:
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
        "2",
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

    namespace = value["namespace"]
    assert namespace["attempt_root"].endswith("/attempts/core-f3-material-coarse-s2-rerun1")
    assert namespace["template"].endswith("/core-f3-material-coarse-s2-rerun1/<fresh-attempt-id>")
    assert namespace["attempt_id_source"] == "scheduler_generated"
    assert namespace["fresh_required"] is True
    assert namespace["historical_reuse_forbidden"] is True
    assert namespace["same_attempt_resume_only"] is True
    assert namespace["path_is_metadata_only"] is True
    assert not (ROOT / namespace["attempt_root"]).exists()


def test_rerun1_external_admission_remains_required_and_non_authorizing() -> None:
    value = _spec()
    admission = value["external_admission"]

    assert admission == {
        "fresh_root_receipt_required": True,
        "scheduler_host_io_receipt_required": True,
        "cross_bind_current_source_and_inputs": True,
        "one_shot_namespace_required": True,
        "launch_authority_minted_by_this_spec": False,
    }
    assert value["qualification_claim"] == "none; diagnostic matrix only"
