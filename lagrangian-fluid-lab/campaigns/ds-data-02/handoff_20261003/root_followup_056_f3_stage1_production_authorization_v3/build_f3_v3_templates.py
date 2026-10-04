#!/usr/bin/env python3
"""Create v3 request templates and an actual-evidence authorize preflight.

The preflight index is deliberately named and marked as a fixture.  It is
not the integration approval index, has ``execution_allowed: false``, and is
never installed into the runtime.  ``production.authorize`` is nevertheless
run against the real Root decisions, real visual reports, and real strict012
input/QA metadata so the package does not rely only on synthetic fixtures.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
V2_DIR = HERE.parent / "root_followup_055_stage1_production_adapter_v2"
INTEGRATION_LAB = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab"
)
V2_SOURCE = V2_DIR / "ds_data02_stage1_production_v2.py"
V2_DISPATCH = V2_DIR / "ds_data02_stage1_dispatch_v2.py"
STRICT = INTEGRATION_LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
MANIFEST_PATH = HERE / "F3_FIRST8_V3_CASE_MANIFEST.json"
DOMAIN_PATH = HERE / "F3_FIRST8_V3_PHYSICAL_DOMAIN.json"
PROVENANCE_054 = HERE.parent / "root_followup_054_f3_stage1_first8_manifest_v1" / "F3_FIRST8_CASE_PROVENANCE.v1.json"
GOAL = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
)
ROOT_DOMAIN_DECISION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json"
)
SCOPE_ID = "F3_STAGE1_FIRST8_AY0250_AY0750_VISUAL_V1"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
SOLVER_CWD = INTEGRATION_LAB
EXPECTED_GOAL_SHA = "53d422511b5581266410de92c54627ac67e8085eccb75a9ebfe57de10a34316a"
EXPECTED_DOMAIN_DECISION_SHA = "7f33f48ddd33446a9f6684c673764727f1f01c1f6390b8d409facb9a91daea1e"


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def binding(path: Path, expected: str | None = None) -> dict[str, str]:
    path = path.resolve()
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise ValueError(f"hash mismatch for {path}: {actual} != {expected}")
    return {"path": str(path), "sha256": actual}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _production_module():
    scripts = str(INTEGRATION_LAB / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    v2_dir = str(V2_DIR)
    if v2_dir not in sys.path:
        sys.path.insert(0, v2_dir)
    return importlib.import_module("ds_data02_stage1_production_v2")


def _observed_visual_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = load(PROVENANCE_054)
    manifest_by_id = {row["case_id"]: row for row in manifest["cases"]}
    result: list[dict[str, Any]] = []
    for source_row in provenance["cases"]:
        case_id = source_row["case_id"]
        if case_id not in {
            "F3_STAGE1_DP006_P1000_AY0250",
            "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005",
            "F3_STAGE1_DP006_P1000_AY0750",
        }:
            continue
        visual = source_row.get("visual_provenance") or source_row.get("visual", {})
        row: dict[str, Any] = {
            "case_id": case_id,
            "status": visual.get("review_status", "visual-approved-by-root"),
            "decision": copy.deepcopy(
                visual.get("root_visual_decision")
                or source_row.get("source", {}).get("historical_visual_decision")
            ),
            "integrity_report": copy.deepcopy(
                visual.get("integrity_report", visual.get("animation_integrity_report"))
            ),
        }
        # The decision document already binds the original GIF/H5/keyframes;
        # retain the explicit aggregate paths too when the provenance record
        # supplies them, so the hash set is auditable from the index entry.
        for name in ("full_saved_animation", "trajectory_binding", "saved_frame_manifest"):
            if visual.get(name) is not None:
                row[name] = copy.deepcopy(visual[name])
        if manifest_by_id[case_id]["role"] == "anchor_existing_mother":
            row["historical"] = True
        result.append(row)
    if len(result) != 3:
        raise ValueError("054 provenance did not provide the three observed visual records")
    return result


def build_scope_entry() -> dict[str, Any]:
    manifest = load(MANIFEST_PATH)
    decision_binding = binding(ROOT_DOMAIN_DECISION, EXPECTED_DOMAIN_DECISION_SHA)
    goal_binding = binding(GOAL, EXPECTED_GOAL_SHA)
    prospective = [row["case_id"] for row in manifest["cases"] if str(row.get("role", "")).startswith("interior")]
    return {
        "schema": "ds02.stage1.f3.concrete-v3-scope-entry.v1",
        "family_id": "F3",
        "scope_id": SCOPE_ID,
        "visual_stage_profile": "stage1_visual",
        "status": "preflight_fixture_only",
        "execution_allowed": False,
        "production_scope_approval": False,
        "numerical_precision_status": "not_accepted",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "stage1_label": "视觉检查通过、数值精度未验收",
        "goal_authority": goal_binding,
        "root_visual_domain_decision": decision_binding,
        "physical_domain": binding(DOMAIN_PATH),
        "case_manifest": binding(MANIFEST_PATH),
        "selected_case_ids": prospective,
        "visual_evidence": {
            "observed": _observed_visual_rows(manifest),
            "prospective": [
                {
                    "case_ids": prospective,
                    "status": "pending actual complete solver/state/ParaView/root case decisions",
                    "decision": None,
                    "integrity_report": None,
                }
            ],
        },
        "review_contract": {
            "future_case_visual_decision_required_after_actual_complete_run": True,
            "future_full_saved_frame_integrity_required_after_actual_complete_run": True,
            "independent_case_count_increment_before_case_decision": 0,
            "no_interpolation_or_extrapolation": True,
            "no_q_n_or_numerical_precision_grant": True,
        },
    }


def build_preflight_index(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds02.root-approved-visual-scopes.v2",
        "campaign_id": "DS-DATA-02",
        "interpretation": "visual-stage preflight fixture only; execution_allowed remains false",
        "status": "preflight_fixture_only",
        "goal_authority": binding(GOAL, EXPECTED_GOAL_SHA),
        "production_scope_approval": False,
        "scopes": [dict(entry)],
    }


def build_requests() -> dict[str, dict[str, Any]]:
    production = _production_module()
    manifest = load(MANIFEST_PATH)
    requests: dict[str, dict[str, Any]] = {}
    for row in manifest["cases"]:
        if not str(row.get("role", "")).startswith("interior"):
            continue
        request = production.build_prospective_request(
            manifest,
            row["case_id"],
            family_id="F3",
            scope_id=SCOPE_ID,
            attempt_id=f"root-f3-stage1-{row['role']}-production-v3-pending-root-approval",
            adapter_path=V2_DISPATCH,
            strict_path=STRICT,
            runtime_path=RUNTIME,
            command=copy.deepcopy(row["actual_solver_command"]),
            cwd=row["actual_solver_cwd"],
            complete_event_window_s=list(row["complete_event_window_s"]),
            input_files=[str(SOLVER.resolve())],
            cpu_threads=4,
            max_wall_seconds=7200,
            estimated_peak_gpu_mib=8192,
            estimated_storage_bytes=17179869184,
            worktree_root=str(INTEGRATION_LAB.parent),
        )
        # Keep the request explicit and source-only.  The v2 builder has no
        # launch side effect; these fields are consumed by the later Root
        # adapter/index review and are not approval flags.
        request["production_approval"] = "none"
        request["launch_allowed"] = False
        request["launch_owner"] = "root after explicit adapter-index review"
        request["future_case_visual_review"] = "required_after_actual_complete_run"
        requests[row["case_id"]] = request
    if set(requests) != {
        "F3_STAGE1_DP006_P1000_AY0320",
        "F3_STAGE1_DP006_P1000_AY0390",
        "F3_STAGE1_DP006_P1000_AY0460",
        "F3_STAGE1_DP006_P1000_AY0570",
        "F3_STAGE1_DP006_P1000_AY0640",
    }:
        raise ValueError("request builder did not produce exactly five prospective cases")
    return requests


def authorize_actual_preflight(case_id: str, *, index_path: Path | None = None, request_path: Path | None = None) -> dict[str, Any]:
    """Run v2 AUTHORIZE against actual v3 evidence without launching anything."""

    production = _production_module()
    if request_path is None:
        request_path = HERE / "requests" / f"{case_id}.json"
    request = load(request_path)
    if index_path is None:
        index_path = HERE / "F3_V3_AUTHORIZE_PREFLIGHT_INDEX.fixture.json"
    context: dict[str, Any] = {}
    hashes = production.authorize(request, index_path=index_path, approval_context=context)
    return {
        "status": "preflight_authorize_passed_actual_evidence",
        "fixture_only": True,
        "execution_allowed": False,
        "case_id": case_id,
        "hash_count": len(hashes),
        "approval_context": context,
        "q_n": context.get("q_n"),
        "prospective_domain_launch": context.get("prospective_domain_launch"),
        "future_case_visual_review": context.get("future_case_visual_review"),
    }


def build_templates(out: Path = HERE) -> None:
    manifest = load(MANIFEST_PATH)
    entry = build_scope_entry()
    save(out / "F3_FIRST8_V3_SCOPE_ENTRY.template.json", entry)
    save(out / "F3_V3_AUTHORIZE_PREFLIGHT_INDEX.fixture.json", build_preflight_index(entry))
    requests = build_requests()
    requests_dir = out / "requests"
    requests_dir.mkdir(exist_ok=True)
    for case_id, request in requests.items():
        save(requests_dir / f"{case_id}.json", request)
    save(
        out / "F3_INTERIOR012_V3_REQUESTS.template.json",
        {
            "schema": "ds02.stage1.f3.concrete-v3-request-set.v1",
            "status": "request_templates_pending_root_adapter_index_review",
            "source_only": True,
            "execution_allowed": False,
            "production_scope_approval": False,
            "q_n": "not_granted",
            "scope_id": SCOPE_ID,
            "case_ids": list(requests),
            "request_paths": [str((requests_dir / f"{case_id}.json").resolve()) for case_id in requests],
            "future_case_visual_review": "required_after_actual_complete_run",
            "manifest": binding(MANIFEST_PATH),
        },
    )
    print(f"wrote v3 scope fixture and {len(requests)} request templates under {out}")


if __name__ == "__main__":
    build_templates()
