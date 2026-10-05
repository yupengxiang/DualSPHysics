#!/usr/bin/env python3
"""Build the F6 fresh074 source-only full241/state0 handoff.

The builder copies the immutable fresh072 owner/request templates, binds them
to the actual direct-root GenCase069 inputs and the actual Root137 initial QA
receipt/index/reports, and leaves all future solver/state0/typed outputs null.
It reads bounded JSON/XML metadata and opaque hashes only; it never decodes
BI4/H5/CSV/particle arrays and never launches a worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

F6WT = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE070 = F6WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_070_stage1_omega_internal_actual_native_qa_full241_v1"
SOURCE072 = F6WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_072_stage1_omega_internal_canonical_owner_qa_v1"
ROOT137 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_five_actual_canonical_initial_qa_137"
SCOPE = "root_followup_074_stage1_omega_internal_qa137_full241_final_v1"
FINAL = F6WT / f"lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/{SCOPE}"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
FLOATINGINFO = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
PYTHON = F6WT / "lagrangian-fluid-lab/.venv/bin/python"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
CASES = [
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025", "0p5", 0.50, "8586d081bd2d936c9ee8bb3e8830327cd465795c0ea911edadd29dd6bd88e534"),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025", "0p75", 0.75, "aa72e1895f0da00dcfc3cf1008261c3d41cc6f4f10e96684c1540aaeadf340e5"),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025", "1p25", 1.25, "c023e8728793929c773dbe3739c8f3f13061af6dfaba2e1f013180cf79d258b2"),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025", "1p5", 1.50, "669bf019915706bc3bea5d932453add414bcbd162c00775d5fb2d8392cdbaae3"),
    ("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025", "1p75", 1.75, "effcb0dd816abf3babdf29a80744705150f9b41af8bbe5cba2e7d9f88d5e2e0b"),
]
EXPECTED_COUNTS = {"dimension": 3, "fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}
EXPECTED_OMEGA = {
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S050_DP025": [0.04, 0.06, 0.03],
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S075_DP025": [0.06, 0.09, 0.045],
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S125_DP025": [0.10, 0.15, 0.075],
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S150_DP025": [0.12, 0.18, 0.09],
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S175_DP025": [0.14, 0.21, 0.105],
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} missing: {path}")


def case_row(case_id: str) -> tuple[str, str, float, str]:
    return next(row for row in CASES if row[0] == case_id)


def gencase_paths(case_id: str, token: str) -> dict[str, Path]:
    root = DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{token}-genuine-gencase-069"
    prefix = root / case_id
    return {
        "root": root,
        "prefix": prefix,
        "receipt": root / "execution-receipt.json",
        "xml": prefix.with_suffix(".xml"),
        "bi4": prefix.with_suffix(".bi4"),
    }


def qa_paths(case_id: str) -> dict[str, Path]:
    root = DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_OMEGA_INTERNAL/root-stage1-f6-first8-five-omega-actual-native-initial-qa-137"
    case_root = root / "initial-native-qa" / case_id
    return {
        "root": root,
        "request": ROOT137 / "request.json",
        "launch": ROOT137 / "launch.py",
        "receipt": root / "execution-receipt.json",
        "index": root / "initial-native-qa/initial-native-qa-index.json",
        "report": case_root / "initial-native-qa.json",
        "partvtk": case_root / "partvtk/partvtk-receipt.json",
    }


def audit_root137() -> dict[str, Any]:
    first = qa_paths(CASES[0][0])
    for key in ("request", "launch", "receipt", "index"):
        require_file(first[key], f"Root137 {key}")
    receipt_obj = load(first["receipt"])
    index_obj = load(first["index"])
    if receipt_obj.get("status") != "completed" or receipt_obj.get("returncode") != 0:
        raise RuntimeError("Root137 execution receipt is not completed/0")
    if index_obj.get("status") != "initial-native-integrity-pass" or index_obj.get("pass") is not True:
        raise RuntimeError("Root137 aggregate index is not an actual passing index")
    rows = []
    for case_id, token, scale, condition in CASES:
        paths = qa_paths(case_id)
        require_file(paths["report"], f"Root137 report {case_id}")
        require_file(paths["partvtk"], f"Root137 PartVTK receipt {case_id}")
        report = load(paths["report"])
        partvtk = load(paths["partvtk"])
        if report.get("pass") is not True or report.get("physical_condition_sha256") != condition:
            raise RuntimeError(f"Root137 report does not pass or condition differs: {case_id}")
        if partvtk.get("returncode") != 0 or partvtk.get("launch_allowed") is not False:
            raise RuntimeError(f"Root137 PartVTK receipt invalid: {case_id}")
        rows.append({
            "case_id": case_id,
            "scale": scale,
            "physical_condition_sha256": condition,
            "request": str(paths["request"]),
            "execution_receipt": str(paths["receipt"]),
            "execution_receipt_sha256": sha(paths["receipt"]),
            "aggregate_index": str(paths["index"]),
            "aggregate_index_sha256": sha(paths["index"]),
            "report": str(paths["report"]),
            "report_sha256": sha(paths["report"]),
            "report_pass": report["pass"],
            "partvtk_receipt": str(paths["partvtk"]),
            "partvtk_receipt_sha256": sha(paths["partvtk"]),
            "partvtk_returncode": partvtk["returncode"],
        })
    return {
        "schema": "ds02.f6.root137.actual-five-case-initial-native-qa-binding.v1",
        "scope_id": SCOPE,
        "root137_handoff": str(ROOT137),
        "request": str(first["request"]),
        "request_sha256": sha(first["request"]),
        "launch_source": str(first["launch"]),
        "launch_source_sha256": sha(first["launch"]),
        "execution_receipt": str(first["receipt"]),
        "execution_receipt_sha256": sha(first["receipt"]),
        "execution_status": receipt_obj["status"],
        "execution_returncode": receipt_obj["returncode"],
        "aggregate_index": str(first["index"]),
        "aggregate_index_sha256": sha(first["index"]),
        "aggregate_status": index_obj["status"],
        "aggregate_pass": index_obj["pass"],
        "cases": rows,
        "all_cases_passed": True,
        "precision_status": "not_accepted",
        "production_approval": "none",
        "q_n_status": "not_assessed",
        "read_policy": "Root137 JSON receipts/index/reports and opaque hashes only; no CSV/BI4/H5/particle arrays read.",
    }


def audit_gencase() -> list[dict[str, Any]]:
    rows = []
    for case_id, token, scale, condition in CASES:
        paths = gencase_paths(case_id, token)
        for key in ("receipt", "xml", "bi4"):
            require_file(paths[key], f"GenCase069 {case_id} {key}")
        receipt = load(paths["receipt"])
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise RuntimeError(f"GenCase069 receipt is not completed/0: {case_id}")
        actual = {"dimension": receipt.get("solver_dimension_from_gencase"), "fluid": receipt.get("fluid_particles"), "total": receipt.get("total_particles")}
        if actual != {"dimension": 3, "fluid": 327680, "total": 417505}:
            raise RuntimeError(f"GenCase069 count contract mismatch: {case_id}: {actual}")
        # Reuse the fresh072 recorded opaque BI4 hash; do not open or rehash BI4.
        template = load(SOURCE072 / "future/full241-requests" / f"{case_id}-full241-native-request.json")
        if template["gencase_bi4_sha256"] is None:
            raise RuntimeError(f"missing recorded BI4 hash: {case_id}")
        rows.append({
            "case_id": case_id,
            "scale": scale,
            "physical_condition_sha256": condition,
            "attempt_root": str(paths["root"]),
            "gencase_prefix": str(paths["prefix"]),
            "receipt": str(paths["receipt"]),
            "receipt_sha256": sha(paths["receipt"]),
            "receipt_status": receipt["status"],
            "receipt_returncode": receipt["returncode"],
            "runtime_counts": actual,
            "generated_xml": str(paths["xml"]),
            "generated_xml_sha256": template["gencase_xml_sha256"],
            "generated_bi4": str(paths["bi4"]),
            "generated_bi4_sha256": template["gencase_bi4_sha256"],
            "no_bi4_decode": True,
        })
    return rows


def state_binding(out: Path, qa: dict[str, Any], gencase: dict[str, dict[str, Any]], owners: dict[str, dict[str, Any]]) -> dict[str, Any]:
    template = load(SOURCE072 / "future/state0-binding.json")
    state_worker_src = SOURCE070 / "workers/run_f6_state0_omega_internal_v1.py"
    audit_worker_src = F6WT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_067_stage1_omega_full12_qualification_v1/workers/audit_f6_endpoint_floatinginfo_state0_v1.py"
    state_worker = out / "workers/run_f6_state0_omega_fresh074.py"
    audit_worker = out / "workers/audit_f6_endpoint_floatinginfo_state0_fresh074.py"
    state_worker.parent.mkdir(parents=True, exist_ok=True)
    audit_worker.write_text(audit_worker_src.read_text(encoding="utf-8"), encoding="utf-8")
    state_text = state_worker_src.read_text(encoding="utf-8")
    state_text = state_text.replace(str(audit_worker_src), str(audit_worker))
    state_worker.write_text(state_text, encoding="utf-8")
    state = {
        "schema": "ds02.f6.stage1-omega-internal-floatinginfo-state0-binding.v2",
        "scope_id": SCOPE,
        "family_id": "F6",
        "status": "source_only_disabled",
        "state0_gate_status": "waiting_root_full241_and_native_state0",
        "launch_allowed": False,
        "root_only": True,
        "floatinginfo_binary": str(FLOATINGINFO),
        "floatinginfo_binary_sha256": template.get("floatinginfo_binary_sha256"),
        "runner_worker": str(state_worker),
        "runner_worker_sha256": sha(state_worker),
        "audit_worker": str(audit_worker),
        "audit_worker_sha256": sha(audit_worker),
        "particle_v0_policy": "GenCase particle V0=0 is serialization evidence only and cannot prove zero rigid angular velocity.",
        "cases": [],
    }
    for case_id, token, scale, condition in CASES:
        omega = EXPECTED_OMEGA[case_id]
        full_root = DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{token}-full241-native-074"
        state_root = DATA / "families/F6/F6_TWO_ENDPOINT_STATE0_OMEGA_CORROBORATION/root-stage1-f6-omega-{token}-floatinginfo-state0-074"
        state["cases"].append({
            "case_id": case_id,
            "scale": scale,
            "declared_omega_rad_s": omega,
            "physical_condition_sha256": condition,
            "canonical_owner": str(owners[case_id]["path"]),
            "canonical_owner_sha256": owners[case_id]["sha256"],
            "endpoint_xml": gencase[case_id]["generated_xml"],
            "endpoint_xml_sha256": gencase[case_id]["generated_xml_sha256"],
            "native_data": str(full_root / "solver_output/data"),
            "solver_receipt": str(full_root / "execution-receipt.json"),
            "solver_receipt_sha256": None,
            "floating_info_csv": None,
            "observed_omega_rad_s": None,
            "state0_attempt_root": str(state_root),
            "state0_audit": str(state_root / "audit" / f"{case_id}.json"),
            "state0_audit_sha256": None,
            "status": "pending_root_full241_and_native_state0",
            "root137_initial_qa": next(row for row in qa["cases"] if row["case_id"] == case_id),
        })
    write(out / "floatinginfo/state0-binding.json", state)
    return state


def build_request(out: Path, case_id: str, token: str, scale: float, condition: str, qa: dict[str, Any], gencase: dict[str, Any], owner: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    template = load(SOURCE072 / "future/full241-requests" / f"{case_id}-full241-native-request.json")
    attempt_root = DATA / "families/F6" / case_id / f"root-stage1-f6-omega-{token}-full241-native-074"
    report = next(row for row in qa["cases"] if row["case_id"] == case_id)
    state_case = next(row for row in state["cases"] if row["case_id"] == case_id)
    d = template
    d["scope_id"] = SCOPE
    d["request_id"] = f"f6-{token}-full241-native-074"
    d["attempt_id"] = f"root-stage1-f6-omega-{token}-full241-native-074"
    d["attempt_root"] = str(attempt_root)
    d["canonical_owner"] = owner["path"]
    d["canonical_owner_sha256"] = owner["sha256"]
    d["physical_condition_sha256"] = condition
    d["gencase_prefix"] = gencase["gencase_prefix"]
    d["cwd"] = gencase["attempt_root"]
    d["gencase_receipt"] = gencase["receipt"]
    d["gencase_receipt_sha256"] = gencase["receipt_sha256"]
    d["gencase_xml"] = gencase["generated_xml"]
    d["gencase_xml_sha256"] = gencase["generated_xml_sha256"]
    d["gencase_bi4"] = gencase["generated_bi4"]
    d["gencase_bi4_sha256"] = gencase["generated_bi4_sha256"]
    d["source_definition"] = owner["source_definition"]
    d["source_definition_sha256"] = owner["source_definition_sha256"]
    d["actual_initial_qa"] = {
        "attempt_id": "root-stage1-f6-first8-five-omega-actual-native-initial-qa-137",
        "request_source": report["request"],
        "receipt": report["execution_receipt"],
        "execution_receipt": report["execution_receipt"],
        "receipt_sha256": report["execution_receipt_sha256"],
        "execution_receipt_sha256": report["execution_receipt_sha256"],
        "index": report["aggregate_index"],
        "index_sha256": report["aggregate_index_sha256"],
        "aggregate_index": report["aggregate_index"],
        "aggregate_index_sha256": report["aggregate_index_sha256"],
        "report": report["report"],
        "report_sha256": report["report_sha256"],
        "partvtk_receipt": report["partvtk_receipt"],
        "partvtk_receipt_sha256": report["partvtk_receipt_sha256"],
        "pass": True,
        "status": "completed_root137_actual_pass",
    }
    d["floatinginfo_state0"] = {"audit_sha256": None, "observed_omega_rad_s": None, "status": "pending_root_full241_and_native_state0"}
    d["typed_validation"] = {"receipt_sha256": None, "report_sha256": None, "status": "pending_root_full241_typed_validation"}
    d["future_outputs"] = {
        "solver_execution_receipt": str(attempt_root / "execution-receipt.json"),
        "solver_execution_receipt_sha256": None,
        "trajectory_h5": str(attempt_root / "solver_output/trajectory.h5"),
        "trajectory_h5_sha256": None,
        "conversion_report": str(attempt_root / "solver_output/conversion-report.json"),
        "conversion_report_sha256": None,
        "floatinginfo_state0_audit": state_case["state0_audit"],
        "floatinginfo_state0_audit_sha256": None,
        "typed_validation_receipt_sha256": None,
        "typed_validation_report_sha256": None,
    }
    d["launch"] = False
    d["launch_allowed"] = False
    d["execution_allowed"] = False
    d["status"] = "source_only_disabled"
    d["binding_status"] = "actual_root137_qa_bound_waiting_root_full241"
    d["claim_boundary"] = "Root137 initial native integrity pass is bound; full241 solver dynamics, typed validation, FloatingInfo state0, Q-N, precision, visual, and production remain future Root evidence."
    d["input_files"] = [
        owner["path"], owner["source_definition"], gencase["receipt"], gencase["generated_xml"], gencase["generated_bi4"],
        report["execution_receipt"], report["aggregate_index"], report["report"], report["partvtk_receipt"],
        str(SOURCE072 / "provenance/root073-canonical-seed-binding.json"), str(SOURCE070 / "qualification/requests" / f"{case_id}-full241-native-request.json"),
        str(STRICT), str(RUNTIME), str(GOAL), str(SOLVER),
    ]
    d["input_sha256"] = {
        owner["path"]: owner["sha256"],
        owner["source_definition"]: owner["source_definition_sha256"],
        gencase["receipt"]: gencase["receipt_sha256"],
        gencase["generated_xml"]: gencase["generated_xml_sha256"],
        gencase["generated_bi4"]: gencase["generated_bi4_sha256"],
        report["execution_receipt"]: report["execution_receipt_sha256"],
        report["aggregate_index"]: report["aggregate_index_sha256"],
        report["report"]: report["report_sha256"],
        report["partvtk_receipt"]: report["partvtk_receipt_sha256"],
        str(SOURCE072 / "provenance/root073-canonical-seed-binding.json"): sha(SOURCE072 / "provenance/root073-canonical-seed-binding.json"),
        str(SOURCE070 / "qualification/requests" / f"{case_id}-full241-native-request.json"): sha(SOURCE070 / "qualification/requests" / f"{case_id}-full241-native-request.json"),
        str(STRICT): sha(STRICT), str(RUNTIME): sha(RUNTIME), str(GOAL): sha(GOAL), str(SOLVER): sha(SOLVER),
    }
    path = out / "full241-requests" / f"{case_id}-full241-native-request.json"
    write(path, d)
    return d


def build_state_request(out: Path, state: dict[str, Any], qa: dict[str, Any]) -> dict[str, Any]:
    template = load(SOURCE072 / "future/state0-request.json")
    attempt_root = DATA / "families/F6/F6_TWO_ENDPOINT_STATE0_OMEGA_CORROBORATION/root-stage1-f6-first8-five-omega-floatinginfo-state0-074"
    request = {
        **template,
        "scope_id": SCOPE,
        "request_id": "f6-first8-five-omega-floatinginfo-state0-074",
        "attempt_id": "root-stage1-f6-first8-five-omega-floatinginfo-state0-074",
        "attempt_root": str(attempt_root),
        "status": "source_only_disabled",
        "binding_status": "waiting_root_full241_and_native_state0",
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "runner_worker": state["runner_worker"],
        "runner_worker_sha256": state["runner_worker_sha256"],
        "audit_worker": state["audit_worker"],
        "audit_worker_sha256": state["audit_worker_sha256"],
        "binding": str(out / "floatinginfo/state0-binding.json"),
        "binding_sha256": sha(out / "floatinginfo/state0-binding.json"),
        "cases": state["cases"],
        "command": [str(PYTHON), state["runner_worker"], "--binding", str(out / "floatinginfo/state0-binding.json"), "--output-dir", "{attempt_root}/audit", "--floating-info-exe", str(FLOATINGINFO)],
        "future_outputs": {"summary": str(attempt_root / "audit/five-endpoint-omega-summary.json"), "summary_sha256": None, "case_audit_sha256": {case_id: None for case_id, _, _, _ in CASES}},
        "particle_v0_policy": "V0=0 from GenCase is not an angular-state proof; each case must be corroborated from its own native FloatingInfo state0.",
        "input_files": [str(out / "floatinginfo/state0-binding.json"), state["runner_worker"], state["audit_worker"], str(FLOATINGINFO), str(PYTHON), str(STRICT), str(RUNTIME)] + [row["endpoint_xml"] for row in state["cases"]] + [row["canonical_owner"] for row in state["cases"]] + [row["solver_receipt"] for row in state["cases"]],
    }
    request["input_sha256"] = {path: sha(Path(path)) if Path(path).is_file() else None for path in request["input_files"]}
    request["input_sha256"][str(out / "floatinginfo/state0-binding.json")] = sha(out / "floatinginfo/state0-binding.json")
    request["input_sha256"][str(FLOATINGINFO)] = state["floatinginfo_binary_sha256"]
    request["input_sha256"][str(PYTHON)] = sha(PYTHON)
    request["input_sha256"][str(STRICT)] = sha(STRICT)
    request["input_sha256"][str(RUNTIME)] = sha(RUNTIME)
    for row in state["cases"]:
        request["input_sha256"][row["endpoint_xml"]] = next(x["generated_xml_sha256"] for x in qa["cases"] if x["case_id"] == row["case_id"]) if False else None
        request["input_sha256"][row["canonical_owner"]] = sha(Path(row["canonical_owner"]))
        request["input_sha256"][row["endpoint_xml"]] = next(item["generated_xml_sha256"] for item in GENCACHE_ROWS if item["case_id"] == row["case_id"])
    write(out / "floatinginfo/state0-request.json", request)
    return request


GENCACHE_ROWS: list[dict[str, Any]] = []


def test_text() -> str:
    return '''#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = %r
CONDITIONS = %r

def j(path):
    return json.loads(path.read_text())

def test_fresh074():
    qa = j(ROOT / "metadata/root137-initial-qa-binding.json")
    assert qa["execution_status"] == "completed" and qa["execution_returncode"] == 0
    assert qa["aggregate_pass"] is True and qa["all_cases_passed"] is True
    assert len(qa["cases"]) == 5
    for row in qa["cases"]:
        assert row["report_pass"] is True and row["physical_condition_sha256"] == CONDITIONS[row["case_id"]]
    owners = j(ROOT / "metadata/canonical-owner-binding.json")
    assert len(owners["cases"]) == 5
    for row in owners["cases"]:
        assert row["physical_condition_sha256"] == CONDITIONS[row["case_id"]]
        owner = j(Path(row["path"]))
        assert owner["physical_condition_sha256"] == row["physical_condition_sha256"]
    for case in CASES:
        req = j(ROOT / "full241-requests" / f"{case}-full241-native-request.json")
        assert req["launch"] is False and req["launch_allowed"] is False and req["execution_allowed"] is False
        assert req["physical_condition_sha256"] == CONDITIONS[case]
        assert "-genuine-gencase-069" in req["cwd"] and "prepared" not in req["cwd"]
        assert req["gencase_actual"] == {"dimension": 3, "fluid": 327680, "returncode": 0, "status": "completed", "total": 417505}
        assert req["actual_initial_qa"]["pass"] is True
        assert req["actual_initial_qa"]["report_sha256"] is not None
        assert req["future_outputs"]["solver_execution_receipt_sha256"] is None
        assert req["future_outputs"]["trajectory_h5_sha256"] is None
        assert req["future_outputs"]["floatinginfo_state0_audit_sha256"] is None
        assert req["future_outputs"]["typed_validation_receipt_sha256"] is None
        assert req["command"][-2:] == ["-tmax:12", "-tout:0.05"]
    state = j(ROOT / "floatinginfo/state0-binding.json")
    assert state["launch_allowed"] is False and len(state["cases"]) == 5
    assert all(row["solver_receipt_sha256"] is None and row["state0_audit_sha256"] is None for row in state["cases"])
    request = j(ROOT / "floatinginfo/state0-request.json")
    assert request["launch"] is False and request["execution_allowed"] is False
    assert request["future_outputs"]["summary_sha256"] is None

if __name__ == "__main__":
    test_fresh074()
    print("fresh074 contract: PASS")
''' % ([case_id for case_id, _, _, _ in CASES], {case_id: condition for case_id, _, _, condition in CASES})


def build(out: Path) -> None:
    global GENCACHE_ROWS
    if out.exists():
        raise RuntimeError(f"output already exists: {out}")
    out.mkdir(parents=True)
    qa = audit_root137()
    GENCACHE_ROWS = audit_gencase()
    gencase = {row["case_id"]: row for row in GENCACHE_ROWS}
    owners: dict[str, dict[str, Any]] = {}
    (out / "owners").mkdir(parents=True)
    (out / "source").mkdir(parents=True)
    for case_id, token, scale, condition in CASES:
        src_owner = SOURCE072 / "owners" / f"{case_id}.canonical-owner.json"
        owner_path = out / "owners" / src_owner.name
        shutil.copy2(src_owner, owner_path)
        owner = load(owner_path)
        if owner.get("physical_condition_sha256") != condition or owner.get("physical_case_id") != case_id:
            raise RuntimeError(f"canonical owner mismatch: {case_id}")
        source_definition = Path(owner["source_definition"])
        require_file(source_definition, f"canonical source definition {case_id}")
        copied_source = out / "source" / source_definition.name
        shutil.copy2(source_definition, copied_source)
        if sha(copied_source) != owner["source_definition_sha256"]:
            raise RuntimeError(f"source definition hash mismatch: {case_id}")
        owners[case_id] = {"case_id": case_id, "path": str(owner_path), "sha256": sha(owner_path), "source_definition": str(source_definition), "source_definition_sha256": owner["source_definition_sha256"], "physical_condition_sha256": condition, "scale": scale}
    write(out / "metadata/canonical-owner-binding.json", {"schema": "ds02.f6.fresh074.canonical-owner-binding.v1", "scope_id": SCOPE, "cases": list(owners.values()), "canonical_condition_hashes": {case_id: condition for case_id, _, _, condition in CASES}, "owner_provenance": str(SOURCE072 / "owners"), "read_policy": "Owner JSON/source XML metadata and hashes only; no arrays decoded."})
    write(out / "metadata/root137-initial-qa-binding.json", qa)
    write(out / "metadata/gen069-input-binding.json", {"schema": "ds02.f6.fresh074.direct-root-gen069-binding.v1", "scope_id": SCOPE, "cases": GENCACHE_ROWS, "counts": EXPECTED_COUNTS, "no_bi4_decode": True})
    state = state_binding(out, qa, gencase, owners)
    requests = []
    for case_id, token, scale, condition in CASES:
        requests.append(build_request(out, case_id, token, scale, condition, qa, gencase[case_id], owners[case_id], state))
    state_request = build_state_request(out, state, qa)
    final_binding = {
        "schema": "ds02.f6.fresh074.actual-qa137-full241-state0-final-binding.v1",
        "scope_id": SCOPE,
        "family_id": "F6",
        "status": "source_only_disabled_root137_qa_bound",
        "recipe": {"tmax_s": 12.0, "tout_s": 0.05, "native_frames": 241, "all_six_dof": True, "forcing": "none", "mdbc": "none", "solver_options": "exact mother recipe"},
        "cases": [{"case_id": case_id, "physical_condition_sha256": condition, "canonical_owner": owners[case_id], "gencase": gencase[case_id], "full241_request": str(out / "full241-requests" / f"{case_id}-full241-native-request.json"), "full241_request_sha256": sha(out / "full241-requests" / f"{case_id}-full241-native-request.json"), "root137_initial_qa": next(row for row in qa["cases"] if row["case_id"] == case_id), "future_solver_receipt_sha256": None, "future_trajectory_h5_sha256": None, "future_typed_receipt_sha256": None, "future_state0_audit_sha256": None} for case_id, token, scale, condition in CASES],
        "state0_request": str(out / "floatinginfo/state0-request.json"),
        "state0_request_sha256": sha(out / "floatinginfo/state0-request.json"),
        "state0_binding": str(out / "floatinginfo/state0-binding.json"),
        "state0_binding_sha256": sha(out / "floatinginfo/state0-binding.json"),
        "particle_v0_policy": "V0=0 cannot prove zero angular velocity; state0 FloatingInfo is required per endpoint.",
        "physical_mass_kg": 128.0,
        "native_support_mass_kg": 256.0,
        "masspart_kg": 0.015625,
        "mass_equality_required": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "no_arrays_read": True,
        "no_jobs_started": True,
        "no_shared_registry_write": True,
    }
    write(out / "metadata/final-binding.json", final_binding)
    manifest = {
        "schema": "ds02.f6.fresh074-manifest.v1",
        "handoff_id": SCOPE,
        "scope_id": SCOPE,
        "family_id": "F6",
        "source_fresh070": str(SOURCE070),
        "source_fresh072": str(SOURCE072),
        "root137_handoff": str(ROOT137),
        "status": "source_only_disabled_root137_qa_bound",
        "launch_allowed": False,
        "execution_allowed": False,
        "no_arrays_read": True,
        "no_jobs_started": True,
        "future_hashes_null": True,
        "canonical_condition_hashes": {case_id: condition for case_id, _, _, condition in CASES},
        "root137_execution_receipt_sha256": qa["execution_receipt_sha256"],
        "root137_aggregate_index_sha256": qa["aggregate_index_sha256"],
        "full241_request_count": 5,
        "next_step": "Root enables the five disabled full241 requests through the strict runner; after terminal native outputs Root runs the separate disabled FloatingInfo state0 request.",
    }
    write(out / "manifest.json", manifest)
    (out / "tests").mkdir(parents=True)
    (out / "tests/test_fresh074_contract.py").write_text(test_text(), encoding="utf-8")
    # Copy the exact source workers into the package; they remain disabled.
    builder_copy = out / "builders/build_f6_fresh074.py"
    builder_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), builder_copy)
    package_files = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "input-hash-binding.json":
            package_files.append({"path": str(path), "sha256": sha(path)})
    write(out / "input-hash-binding.json", {"schema": "ds02.f6.fresh074-input-hash-binding.v1", "scope_id": SCOPE, "status": "source_only_disabled", "package_file_count": len(package_files), "package_files": package_files, "external_bindings": {"root137": str(out / "metadata/root137-initial-qa-binding.json"), "gen069": str(out / "metadata/gen069-input-binding.json"), "canonical_owners": str(out / "metadata/canonical-owner-binding.json")}, "read_policy": "bounded JSON/XML metadata and recorded opaque hashes only; no BI4/H5/CSV/particle arrays"})
    readme = f"""# F6 fresh074 actual Root137 QA to full241/state0 source handoff

This package is source-only and disabled. It derives five full241 requests from
the fresh070 mother templates and fresh072 canonical owners, then binds each
case to the actual direct-root GenCase069 output and the actual Root137
completed/0 initial-native QA receipt, aggregate index, and per-case report.

The canonical physical condition hashes are preserved exactly: S050
`8586d081...e534`, S075 `aa72e189...f340e5`, S125 `c023e872...d258b2`,
S150 `669bf019...aae3`, and S175 `effcb0dd...e2e0b`. Each request uses the
actual GenCase069 directory as `cwd`; no fictional prepared directory is used.
The exact mother solver recipe remains `-tmax:12 -tout:0.05`, 241 native
frames, free six-DOF, no forcing, and no MDBC.

Physical mass 128 kg, native support mass 256 kg, and masspart 0.015625 kg
remain distinct with no normalization. Root137 QA is initial native integrity
evidence only; Q-N, precision, visual, and production approval remain unset.
All full241 solver, typed validation, and FloatingInfo state0 hashes are null.
The separate FloatingInfo state0 request derives expected omega from each
endpoint's own XML/owner. Particle V0=0 is explicitly not treated as proof of
zero angular velocity.

No arrays were decoded, no jobs were launched, and no shared state was written.
"""
    (out / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
