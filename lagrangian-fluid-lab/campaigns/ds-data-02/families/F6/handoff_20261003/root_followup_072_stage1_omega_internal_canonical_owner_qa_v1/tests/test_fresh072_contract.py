#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL_PACKAGE = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_072_stage1_omega_internal_canonical_owner_qa_v1")
def resolve(path: Path) -> Path:
    raw = str(path)
    prefix = str(FINAL_PACKAGE)
    if raw == prefix or raw.startswith(prefix + "/"):
        return ROOT / raw[len(prefix):].lstrip("/")
    return path

F6WT_PREFIX = "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
CASES = [
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025",
]
EXPECTED = {"dimension": 3, "fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path: Path):
    return json.loads(path.read_text())

def close(a, b):
    return len(a) == len(b) and all(abs(float(x) - float(y)) <= 1e-12 for x, y in zip(a, b))

def vec(node):
    return [float(node.get(axis)) for axis in "xyz"]

def test_fresh072_contract():
    binding = load(ROOT / "qa/qa-binding.json")
    assert binding["schema"] == "ds02.f6.stage1-omega-initial-native-qa-binding.v3"
    assert binding["status"] == "source_only_disabled"
    assert binding["launch_allowed"] is False and binding["root_only"] is True
    assert len(binding["historical_evidence"]) == 2
    assert len(binding["endpoints"]) == 5
    for endpoint in binding["endpoints"]:
        case = endpoint["case_id"]
        assert case in CASES
        owner_path = resolve(Path(endpoint["canonical_owner"]))
        assert owner_path.is_file() and str(owner_path).startswith(str(ROOT))
        assert digest(owner_path) == endpoint["canonical_owner_sha256"]
        owner = load(owner_path)
        assert owner["schema"] == "ds02.root.f6.prospective-endpoint-canonical-owner.v1"
        assert owner["case_id"] == case and owner["physical_case_id"] == case
        physical = owner["physical_binding"]
        condition = hashlib.sha256(json.dumps(physical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert condition == owner["physical_condition_sha256"] == endpoint["physical_condition_sha256"]
        assert owner["source_plan_condition_sha256"] is None and endpoint["source_plan_condition_sha256"] is None
        assert endpoint["expected_counts"] == EXPECTED
        source = Path(endpoint["source_definition"])
        assert str(source).startswith(F6WT_PREFIX) and source.is_file()
        assert digest(source) == endpoint["source_definition_sha256"]
        xml = Path(endpoint["generated_xml"])
        root = ET.parse(xml).getroot()
        particles = root.find(".//particles")
        assert particles is not None
        np = int(particles.get("np")); nb = int(particles.get("nb")); nbf = int(particles.get("nbf"))
        assert {"dimension": 3, "fixed": nbf, "moving": 0, "floating": nb - nbf, "fluid": np - nb, "total": np} == EXPECTED
        assert close(vec(root.find(".//angularvelini")), endpoint["omega_rad_s"])
        assert close(vec(root.find(".//center")), [2.4, 1.2, 1.08])
        assert float(root.find(".//massbody").get("value")) == 128.0
        assert float(root.find(".//masspart").get("value")) == 0.015625
        assert root.find(".//data2d").get("value").lower() == "false"
        sizes = [vec(node) for node in root.findall(".//geometry//size")]
        assert any(close(size, [4.8, 2.4, 2.4]) for size in sizes)
    request = load(ROOT / "qa/initial-native-qa-request.json")
    assert request["launch"] is False and request["launch_allowed"] is False
    assert str(FINAL_PACKAGE / "workers/run_f6_initial_native_qa_fresh072_v1.py") == request["command"][1]
    assert str(request["command"][1]).startswith(F6WT_PREFIX)
    worker_text = resolve(Path(request["command"][1])).read_text()
    assert ".//geometry//size" in worker_text
    assert request["expected_outputs"]["index_sha256"] is None
    assert all(value is None for value in request["expected_outputs"]["report_sha256"].values())
    future = load(ROOT / "future/derived-receipt-binding.json")
    assert future["launch_allowed"] is False and future["no_future_hash_fabrication"] is True
    assert future["initial_native_qa"]["receipt_sha256"] is None
    assert future["initial_native_qa"]["index_sha256"] is None
    assert future["state0_request"]["receipt_sha256"] is None and future["state0_request"]["summary_sha256"] is None
    for item in future["full241_requests"]:
        assert item["solver_receipt_sha256"] is None
        assert item["trajectory_h5_sha256"] is None and item["conversion_report_sha256"] is None

if __name__ == "__main__":
    test_fresh072_contract()
    print("fresh072 contract: PASS")
