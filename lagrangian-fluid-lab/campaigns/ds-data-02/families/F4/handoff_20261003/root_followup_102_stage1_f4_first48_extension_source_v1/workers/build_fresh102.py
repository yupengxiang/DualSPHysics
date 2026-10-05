#!/usr/bin/env python3
"""Build F4 fresh102 first48 source-only extension.

The builder reads JSON/XML/code metadata only.  It never opens scientific
payloads, starts a job, or writes shared campaign state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

PACKAGE_NAME = "root_followup_102_stage1_f4_first48_extension_source_v1"
FAMILY = "F4"
DP = 0.01
TIME_MAX = 1.2
TIME_OUT = 0.001
FRAMES = 1201
WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics")
F4_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/families/F4")
FAMILY_ROOT = WORKTREE / F4_REL
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003"
MOTHER_REL = Path("root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1/definitions/F4_DROP_LATTICE_GAP0p19000_DP010_Def.xml")
MOTHER = FAMILY_ROOT / "handoff_20261003" / MOTHER_REL
CURRENT24_PLAN = FAMILY_ROOT / "handoff_20261003/root_followup_091_stage1_f4_first24_coverage_audit_v1/source-plan.json"
INTERNAL8_PLAN = FAMILY_ROOT / "handoff_20261003/root_followup_081_stage1_drop_gap_internal8_source_v1/source-plan.json"
FALLBACK6_PLAN = FAMILY_ROOT / "handoff_20261003/root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1/source-plan.json"
REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CWD = GENCASE.parent
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003")
ROOT561 = INTEGRATION / "root_stage1_f4_actualtyped533_XMF547_all24_independent_review_561/actual-root-all24-full1201-typed-XMF-review.json"
ROOT570 = INTEGRATION / "root_stage1_f4_fresh100_exact_actualXMF547_adoption_570/actual-source-adoption-review.json"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_obj(value: Any) -> str:
    return digest_bytes(canon(value))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def path_digest(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": digest_file(path)}


def token(value: float) -> str:
    return f"{value:.5f}".replace("-", "m").replace(".", "p")


def case_id(gap: float, x: float, y: float, speed: float) -> str:
    return f"F4_DROP_gap{token(gap)}_xoff{token(x)}_yoff{token(y)}_uz{token(speed)}"


def read_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def xml_mutate(source: Path, target: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    main = root.find("./casedef/geometry/commands/mainlist")
    if main is None:
        raise RuntimeError("source XML lacks geometry mainlist")
    active: int | None = None
    fluid_blocks: dict[int, ET.Element] = {}
    for node in list(main):
        if node.tag == "setmkfluid":
            active = int(node.get("mk", "-1"))
        elif node.tag == "setmkbound":
            active = None
        elif node.tag == "drawbox" and active is not None:
            fluid_blocks[active] = node
    if set(fluid_blocks) != {0, 1}:
        raise RuntimeError(f"unexpected fluid blocks: {sorted(fluid_blocks)}")
    point = fluid_blocks[1].find("point")
    if point is None:
        raise RuntimeError("drop block lacks point")
    # The frozen F4 source uses pool top=.195 and keeps one DP of vertical
    # clearance in the named gap parameter: drop low z=.205+gap.
    low = {
        "x": 0.475 + cfg["x_offset_m"],
        "y": 0.125 + cfg["y_offset_m"],
        "z": 0.205 + cfg["gap_m"],
    }
    for axis, value in low.items():
        point.set(axis, f"{value:.17g}")
    velocity = root.find("./casedef/initials/velocity[@mkfluid='1']")
    if velocity is None:
        raise RuntimeError("source XML lacks mkfluid=1 velocity")
    velocity.set("x", "0")
    velocity.set("y", "0")
    velocity.set("z", f"{-cfg['speed_m_per_s']:.17g}")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or definition.get("dp") != "0.01":
        raise RuntimeError("source DP contract changed")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "drop_low_m": [low["x"], low["y"], low["z"]],
        "drop_size_m": [0.25, 0.15, 0.13],
        "drop_velocity_m_per_s": [0.0, 0.0, -cfg["speed_m_per_s"]],
        "changed_fields": [
            "casedef.geometry.commands.mainlist.setmkfluid(mk=1).drawbox.point.x",
            "casedef.geometry.commands.mainlist.setmkfluid(mk=1).drawbox.point.y",
            "casedef.geometry.commands.mainlist.setmkfluid(mk=1).drawbox.point.z",
            "casedef.initials.velocity[@mkfluid=1].z",
        ],
        "unchanged_fields": [
            "pool point/size and mkfluid=0",
            "drop size and mkfluid=1",
            "tank/wall geometry",
            "gravity and solver controls",
            "DP=.01",
            "TimeMax=1.2",
            "TimeOut=.001",
            "no forcing",
            "no mdbc",
        ],
    }


def source_core(cfg: dict[str, Any], definition: Path) -> dict[str, Any]:
    return {
        "family_id": FAMILY,
        "mechanism_id": "finite_drop_pool",
        "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "physical_case_id": cfg["physical_case_id"],
        "parameters": {
            "gap_m": cfg["gap_m"],
            "x_offset_m": cfg["x_offset_m"],
            "y_offset_m": cfg["y_offset_m"],
            "speed_m_per_s": cfg["speed_m_per_s"],
        },
        "dp_m": DP,
        "time_max_s": TIME_MAX,
        "time_out_s": TIME_OUT,
        "native_frame_count": FRAMES,
        "no_forcing": True,
        "no_mdbc": True,
        "drop_low_m": [0.475 + cfg["x_offset_m"], 0.125 + cfg["y_offset_m"], 0.205 + cfg["gap_m"]],
        "drop_size_m": [0.25, 0.15, 0.13],
        "pool_low_m": [0.085, 0.045, 0.045],
        "pool_size_m": [1.03, 0.31, 0.15],
        "tank_low_m": [0.0, 0.0, 0.0],
        "tank_size_m": [1.2, 0.4, 0.6],
        "initial_drop_velocity_m_per_s": [0.0, 0.0, -cfg["speed_m_per_s"]],
        "solver_options": ["-tmax:1.2", "-tout:0.001"],
    }


def make_owner(cfg: dict[str, Any], definition: Path, plan_path: Path, plan_sha: str, mutation: dict[str, Any], physical_hash: str, plan_condition_hash: str) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": FAMILY,
        "case_id": cfg["case_id"],
        "physical_case_id": cfg["physical_case_id"],
        "mechanism_id": "finite_drop_pool",
        "lineage_group_id": "finite_drop_pool_frozen_geometry_control_domain",
        "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "parameters": {
            "gap_m": cfg["gap_m"],
            "x_offset_m": cfg["x_offset_m"],
            "y_offset_m": cfg["y_offset_m"],
            "speed_m_per_s": cfg["speed_m_per_s"],
        },
        "physical_condition_sha256": physical_hash,
        "source_plan_condition_sha256": plan_condition_hash,
        "source_plan": {"path": str(plan_path), "sha256": plan_sha},
        "source_definition": {"path": str(definition), "sha256": digest_file(definition)},
        "mother_definition": {"path": str(MOTHER), "sha256": digest_file(MOTHER)},
        "geometry": {
            "tank": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.2, 0.4, 0.6], "wall_faces_closed": ["bottom", "left", "right", "front", "back"]},
            "pool": {"low_m": [0.085, 0.045, 0.045], "size_m": [1.03, 0.31, 0.15], "mkfluid": 0},
            "drop": {"low_m": mutation["drop_low_m"], "size_m": [0.25, 0.15, 0.13], "mkfluid": 1},
        },
        "controls": {
            "boundary": "DBC", "step_algorithm": "Verlet", "kernel": "Wendland",
            "viscosity": 0.08, "density_dt": 2, "density_dt_value": 0.1,
            "gravity_m_s2": [0.0, 0.0, -9.81], "open_inlet": False, "periodic_boundary": False,
        },
        "initial_state": {
            "source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"},
            "velocities_m_per_s": {"mkfluid:0": [0.0, 0.0, 0.0], "mkfluid:1": mutation["drop_velocity_m_per_s"]},
            "actual_counts": None,
            "actual_solver_dimension": None,
            "initial_mass_by_source_kg": None,
            "initial_mass_total_kg": None,
            "initial_native_mass_status": "pending actual GenCase/initial QA; no mass rescale",
        },
        "solver_recipe": {
            "dp_m": DP, "time_max_s": TIME_MAX, "time_out_s": TIME_OUT,
            "native_frame_count": FRAMES, "solver_options": ["-tmax:1.2", "-tout:0.001"],
            "no_forcing": True, "no_mdbc": True,
            "native_types": {"fixed": [0], "floating": [], "fluid": [3], "moving": []},
        },
        "mutation_contract": mutation,
        "claim_boundary": {
            "status": "prospective_source_only",
            "actual_gencase": False, "actual_initial_qa": False, "actual_native": False,
            "actual_typed": False, "actual_xmf": False, "actual_render": False,
            "visual_approval": False, "precision_status": "not_accepted", "q_n": "not_granted",
        },
        "future_artifacts": {
            "generated_xml_sha256": None, "generated_bi4_sha256": None,
            "gencase_receipt_sha256": None, "initial_qa_receipt_sha256": None,
            "native_receipt_sha256": None, "typed_receipt_sha256": None,
            "xmf_sha256": None, "render_sha256": None,
        },
        "status": "prospective_source_only",
    }


def make_request(cfg: dict[str, Any], definition: Path, owner: Path, plan_path: Path, plan_sha: str, plan_condition_hash: str, physical_hash: str, package: Path) -> dict[str, Any]:
    case = cfg["case_id"]
    attempt = f"root-stage1-f4-{case.lower()}-genuine-gencase-102"
    static_files = [definition, owner, plan_path, MOTHER, CURRENT24_PLAN, INTERNAL8_PLAN, FALLBACK6_PLAN, REGISTRY]
    return {
        "schema": "ds02.runner-request.v1",
        "family_id": FAMILY,
        "case_id": case,
        "physical_case_id": cfg["physical_case_id"],
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 4,
        "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/prepared/{case}", "-save:all"],
        "cwd": str(GENCASE_CWD),
        "worktree_root": str(WORKTREE),
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "jobs_started_by_source": False,
        "arrays_read_by_source": False,
        "disabled": True,
        "status": "disabled_pending_root_review",
        "disabled_reason": "Fresh102 prospective first48 source only; Root must review and run one registered GenCase per condition.",
        "launch_owner": "root",
        "launch_commit": None,
        "launch_commit_policy": "bind exact adopted fresh102 scoped commit before enabling",
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 4294967296,
        "input_files": [str(p) for p in static_files],
        "input_sha256": {str(p): digest_file(p) for p in static_files},
        "expected": {
            "solver_dimension": "3D",
            "data2d": False,
            "actual_counts_required": True,
            "total_particles_from_gencase": None,
            "fluid_particles_from_gencase": None,
            "fixed_particles_from_gencase": None,
            "moving_particles_from_gencase": None,
            "native_mass_by_source_kg": None,
            "generated_xml_sha256": None,
            "generated_bi4_sha256": None,
        },
        "output_contract": {
            "generated_xml": f"{{attempt_root}}/prepared/{case}.xml",
            "generated_bi4": f"{{attempt_root}}/prepared/{case}.bi4",
            "prepared_input_report": f"{{attempt_root}}/prepared/prepared-input-report.json",
            "execution_receipt": "{attempt_root}/execution-receipt.json",
            "future_sha256": None,
        },
        "physical_condition_sha256": physical_hash,
        "source_plan_condition_sha256": plan_condition_hash,
        "source_plan": {"path": str(plan_path), "sha256": plan_sha},
        "owner_binding": {"path": str(owner), "sha256": digest_file(owner)},
        "recipe": {
            "dp_m": DP, "time_max_s": TIME_MAX, "time_out_s": TIME_OUT,
            "native_frame_count": FRAMES, "solver_options": ["-tmax:1.2", "-tout:0.001"],
            "no_forcing": True, "no_mdbc": True,
        },
        "precision_status": "not_accepted",
        "q_n_status": "not_granted",
        "production_approval": False,
        "independent_case_count_increment": 0,
        "root_review_required": True,
        "claim_boundary": "No GenCase/3D/count/mass/QA/native/typed/XMF/render success is claimed until Root actual receipts and prepared reports.",
    }


def inventory(cfgs: list[dict[str, Any]], current_plan: Any, internal_plan: Any, fallback_plan: Any, current_evidence: dict[str, Any]) -> dict[str, Any]:
    def current_rows() -> list[dict[str, Any]]:
        rows = []
        for row in current_plan["rows"]:
            p = row["parameters"]
            rows.append({
                "physical_case_id": row["physical_case_id"],
                "mechanism": "finite_drop_pool",
                "parameters": p,
                "source_scope": "frozen current exact24",
                "status": "actual_native_typed_xmf_completed0; allframe_visual_pending",
                "source_plan": str(CURRENT24_PLAN),
            })
        return rows
    old8 = []
    for row in internal_plan.get("endpoints", []):
        old8.append({
            "physical_case_id": row["physical_case_id"],
            "mechanism": "finite_drop_pool",
            "parameters": {"gap_m": row["gap_m"], "x_offset_m": 0.0, "y_offset_m": 0.0, "speed_m_per_s": 0.5},
            "source_scope": "historical internal8",
            "status": "Root216_native_initial_QA_negative_all_source_population_checks; retained_negative_excluded",
            "source_plan": str(INTERNAL8_PLAN),
        })
    fallback = []
    for row in fallback_plan.get("endpoints", []):
        fallback.append({
            "physical_case_id": row["physical_case_id"],
            "mechanism": "finite_drop_pool",
            "parameters": {"gap_m": row["gap_m"], "x_offset_m": 0.0, "y_offset_m": 0.0, "speed_m_per_s": 0.5},
            "source_scope": "fallback6 lattice-aligned center",
            "status": "actual_products_separate_scope; not current exact24",
            "source_plan": str(FALLBACK6_PLAN),
        })
    registry_rows = []
    for row in read_registry():
        p = row.get("parameters", {})
        registry_rows.append({
            "physical_case_id": row.get("physical_case_id", row.get("case_id")),
            "mechanism": row.get("mechanism_id"),
            "parameters": {k: p.get(k) for k in ("gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s") if k in p},
            "source_scope": "F4 case_registry metadata",
            "status": row.get("production_artifact_status"),
            "source_plan": str(REGISTRY),
        })
    existing_by_id: dict[str, dict[str, Any]] = {}
    for row in registry_rows + old8 + fallback + current_rows():
        existing_by_id.setdefault(row["physical_case_id"], row)
    proposed = []
    for cfg in cfgs:
        proposed.append({
            "physical_case_id": cfg["physical_case_id"],
            "mechanism": "finite_drop_pool",
            "parameters": {k: cfg[k] for k in ("gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s")},
            "source_scope": "fresh102 prospective first48 extension",
            "status": "prospective_source_only; disabled; no qualification",
        })
    current_ids = {r["physical_case_id"] for r in current_rows()}
    old_ids = {r["physical_case_id"] for r in old8}
    fallback_ids = {r["physical_case_id"] for r in fallback}
    proposed_ids = {r["physical_case_id"] for r in proposed}
    registry_ids = {r["physical_case_id"] for r in registry_rows}
    return {
        "schema": "ds02.f4.first48.physical-condition-inventory.v1",
        "family_id": FAMILY,
        "source_only": True,
        "arrays_read_by_source": False,
        "scientific_payloads_read": [],
        "source_policy": "JSON/XML/code metadata only; no BI4/H5/CSV/VTK/DAT/scientific payload read or hash",
        "current_exact24": {"count": len(current_ids), "unique": len(current_ids) == 24, "rows": current_rows(), "evidence": current_evidence},
        "historical_internal8": {"count": len(old_ids), "unique": len(old_ids) == 8, "rows": old8, "included_in_target": False, "negative_preserved": True},
        "fallback6": {"count": len(fallback_ids), "unique": len(fallback_ids) == 6, "rows": fallback, "included_in_current_exact24": False},
        "registry_metadata": {"count": len(registry_ids), "unique": len(registry_ids) == len(registry_rows), "path": str(REGISTRY), "sha256": digest_file(REGISTRY)},
        "fresh102_proposed24": {"count": len(proposed_ids), "unique": len(proposed_ids) == 24, "rows": proposed},
        "set_relations": {
            "internal8_intersects_current24": sorted(old_ids & current_ids),
            "internal8_intersects_proposed24": sorted(old_ids & proposed_ids),
            "current24_intersects_proposed24": sorted(current_ids & proposed_ids),
            "fallback6_intersects_current24": sorted(fallback_ids & current_ids),
            "fallback6_intersects_proposed24": sorted(fallback_ids & proposed_ids),
            "registry_intersects_proposed24": sorted(registry_ids & proposed_ids),
        },
        "target_count_statement": {
            "current_exact24_plus_proposed24": 48,
            "new_rows_are_not_admitted_or_qualified": True,
            "historical_internal8_not_counted": True,
            "visual_or_precision_qualification": "not granted by this source package",
        },
    }


def evidence_summary() -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": "ds02.f4.first48.current24-evidence-summary.v1",
        "source_only": True,
        "payloads_read": [],
        "records": [],
    }
    for label, path in (("root561_actual24_review", ROOT561), ("root570_source_adoption", ROOT570)):
        if not path.is_file():
            out["records"].append({"label": label, "path": str(path), "exists": False})
            continue
        d = load_json(path)
        record = {
            "label": label,
            "path": str(path),
            "sha256": digest_file(path),
            "exists": True,
            "status": d.get("status", d.get("actual_source_static_validation_pass")),
            "row_count": len(d.get("rows", [])) if isinstance(d.get("rows"), list) else None,
            "case_ids": [r.get("physical_case_id") for r in d.get("rows", []) if isinstance(r, dict) and r.get("physical_case_id")],
        }
        if label == "root561_actual24_review":
            record["allframe_visual_pending"] = d.get("actual_allframe_render_and_visual_pending")
            record["actual_initial_frame0_velocity_QA_pass"] = d.get("actual_initial_frame0_velocity_QA530_all24_pass")
            record["negative_mass_lattice_preserved"] = d.get("numerical_mass_and_DP_lattice_negatives_preserved")
        else:
            record["source_commit"] = d.get("source_commit")
            record["all24_reviewed"] = d.get("all24actualXMF547_completed0_independently_reviewed_root561")
            record["source_unchanged"] = d.get("fresh099_source_unchanged_new_paths_rebound")
        out["records"].append(record)
    return out


def make_validator() -> str:
    return '''#!/usr/bin/env python3
"""Validate fresh102 source-only metadata without touching scientific payloads."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))

def main():
    inv = load("inventory/existing-physical-condition-inventory.json")
    plan = load("source-plan.json")
    idx = load("requests/index.json")
    proposed = [r["physical_case_id"] for r in plan["rows"]]
    assert len(proposed) == 24 and len(set(proposed)) == 24
    assert inv["current_exact24"]["count"] == 24
    assert inv["historical_internal8"]["count"] == 8
    assert inv["set_relations"]["internal8_intersects_current24"] == []
    assert inv["set_relations"]["internal8_intersects_proposed24"] == []
    assert inv["set_relations"]["current24_intersects_proposed24"] == []
    assert inv["set_relations"]["registry_intersects_proposed24"] == []
    assert len(idx["rows"]) == 24 and idx["launch_allowed"] is False
    for row in idx["rows"]:
        req = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        assert req["disabled"] and not req["launch_allowed"] and not req["execution_allowed"]
        assert req["source_only"] and not req["jobs_started_by_source"] and not req["arrays_read_by_source"]
        assert req["expected"]["total_particles_from_gencase"] is None
        assert req["expected"]["fluid_particles_from_gencase"] is None
        assert req["expected"]["generated_bi4_sha256"] is None
        assert req["output_contract"]["future_sha256"] is None
    print("fresh102 source contract: PASS (24 prospective rows, 0 overlaps, 24 disabled GenCase requests)")

if __name__ == "__main__":
    main()
'''


def make_tests() -> str:
    return '''from __future__ import annotations
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def load(rel): return json.loads((ROOT / rel).read_text(encoding="utf-8"))
def test_target_extension_is_disjoint():
    inv = load("inventory/existing-physical-condition-inventory.json")
    assert inv["current_exact24"]["count"] == 24
    assert inv["historical_internal8"]["count"] == 8
    assert inv["fresh102_proposed24"]["count"] == 24
    for key in ("internal8_intersects_current24", "internal8_intersects_proposed24", "current24_intersects_proposed24", "registry_intersects_proposed24"):
        assert inv["set_relations"][key] == []
def test_recipe_and_claim_boundary():
    plan = load("source-plan.json")
    assert len(plan["rows"]) == 24
    assert plan["recipe"] == {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_forcing": True, "no_mdbc": True}
    assert plan["stage_contract"]["launch_allowed"] is False
    assert plan["stage_contract"]["actual_counts"] is None
def test_all_gencase_requests_disabled_and_unknown():
    idx = load("requests/index.json")
    assert len(idx["rows"]) == 24 and idx["launch_allowed"] is False
    for row in idx["rows"]:
        d = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        assert d["disabled"] and not d["launch_allowed"] and not d["execution_allowed"]
        assert d["expected"]["total_particles_from_gencase"] is None
        assert d["expected"]["fluid_particles_from_gencase"] is None
        assert d["output_contract"]["future_sha256"] is None
        assert d["precision_status"] == "not_accepted" and d["q_n_status"] == "not_granted"
'''


def build(worktree: Path) -> Path:
    global FAMILY_ROOT, HANDOFF_ROOT, MOTHER, CURRENT24_PLAN, INTERNAL8_PLAN, FALLBACK6_PLAN, REGISTRY
    FAMILY_ROOT = worktree / F4_REL
    HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003"
    MOTHER = HANDOFF_ROOT / MOTHER_REL
    CURRENT24_PLAN = HANDOFF_ROOT / "root_followup_091_stage1_f4_first24_coverage_audit_v1/source-plan.json"
    INTERNAL8_PLAN = HANDOFF_ROOT / "root_followup_081_stage1_drop_gap_internal8_source_v1/source-plan.json"
    FALLBACK6_PLAN = HANDOFF_ROOT / "root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1/source-plan.json"
    REGISTRY = FAMILY_ROOT / "case_registry.jsonl"
    package = HANDOFF_ROOT / PACKAGE_NAME
    if package.exists():
        raise RuntimeError(f"refusing to overwrite existing package: {package}")
    for p in (MOTHER, CURRENT24_PLAN, INTERNAL8_PLAN, FALLBACK6_PLAN, REGISTRY):
        if not p.is_file():
            raise RuntimeError(f"required metadata missing: {p}")
    package.mkdir(parents=True)
    for d in ("definitions", "owners", "requests", "inventory", "evidence", "workers", "tests"):
        (package / d).mkdir()

    # Build the prospective domain from the already used pose/speed controls.
    cfgs: list[dict[str, Any]] = []
    for gap in (0.20, 0.25, 0.26):
        for x in (-0.08, 0.08):
            for y in (-0.04, 0.04):
                for speed in (0.4, 0.6):
                    cid = case_id(gap, x, y, speed)
                    cfgs.append({
                        "case_id": cid, "physical_case_id": cid,
                        "gap_m": gap, "x_offset_m": x, "y_offset_m": y, "speed_m_per_s": speed,
                    })
    if len(cfgs) != 24 or len({c["case_id"] for c in cfgs}) != 24:
        raise RuntimeError("fresh102 candidate generation is not 24 unique rows")

    # Definitions are built before the plan so their immutable hashes can be
    # included without a circular plan reference.
    mutations: dict[str, dict[str, Any]] = {}
    definition_paths: dict[str, Path] = {}
    for cfg in cfgs:
        target = package / "definitions" / f"{cfg['case_id']}_Def.xml"
        mutations[cfg["case_id"]] = xml_mutate(MOTHER, target, cfg)
        definition_paths[cfg["case_id"]] = target

    plan_rows: list[dict[str, Any]] = []
    for rank, cfg in enumerate(cfgs):
        definition = definition_paths[cfg["case_id"]]
        core = source_core(cfg, definition)
        physical_hash = digest_obj(core)
        plan_condition = {
            "physical_core": core,
            "mother_definition": path_digest(MOTHER),
            "current24_source_plan": path_digest(CURRENT24_PLAN),
            "historical_internal8_source_plan": path_digest(INTERNAL8_PLAN),
            "fallback6_source_plan": path_digest(FALLBACK6_PLAN),
            "mutation": mutations[cfg["case_id"]],
        }
        plan_condition_hash = digest_obj(plan_condition)
        plan_rows.append({
            "rank": rank,
            "case_id": cfg["case_id"], "physical_case_id": cfg["physical_case_id"],
            "parameters": {k: cfg[k] for k in ("gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s")},
            "mechanism": "finite_drop_pool",
            "variation_dimension": "gap_and_drop_pose_speed_extension",
            "definition": {"path": str(definition), "sha256": digest_file(definition)},
            "physical_condition_sha256": physical_hash,
            "source_plan_condition_sha256": plan_condition_hash,
            "drop_geometry": mutations[cfg["case_id"]],
            "actual_stage": "prospective_source_only",
            "actual_counts": None,
            "generated_xml_sha256": None,
            "generated_bi4_sha256": None,
            "gencase_receipt_sha256": None,
            "initial_qa_receipt_sha256": None,
            "native_receipt_sha256": None,
            "typed_receipt_sha256": None,
            "xmf_sha256": None,
            "render_sha256": None,
            "request_hash": None,
        })
    plan = {
        "schema": "ds02.f4.first48.extension-source-plan.v1",
        "scope_id": PACKAGE_NAME,
        "family_id": FAMILY,
        "model_policy": {"authorized_model": "GPT-5.6 Luna/max", "gemini": False, "recursive_agents": False},
        "scope_definition": "Current exact24 plus 24 disjoint prospective finite_drop_pool rows for the first48 target; only the fresh102 rows are source definitions here.",
        "mother_source": {"path": str(MOTHER), "sha256": digest_file(MOTHER), "mutation_policy": "only falling-drop point x/y/z and mkfluid=1 z velocity; pool/tank/controls frozen"},
        "recipe": {"dp_m": DP, "time_max_s": TIME_MAX, "time_out_s": TIME_OUT, "native_frame_count": FRAMES, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_forcing": True, "no_mdbc": True},
        "candidate_domain": {"gaps_m": [0.20, 0.25, 0.26], "x_offsets_m": [-0.08, 0.08], "y_offsets_m": [-0.04, 0.04], "drop_speeds_m_per_s": [0.4, 0.6], "count": 24, "legal_geometry_reason": "all drop bounds remain inside tank and above pool with the frozen one-DP clearance; exact native occupancy remains unknown until Root GenCase"},
        "existing_scope_refs": {"current24_source_plan": path_digest(CURRENT24_PLAN), "historical_internal8_source_plan": path_digest(INTERNAL8_PLAN), "fallback6_source_plan": path_digest(FALLBACK6_PLAN), "registry": path_digest(REGISTRY)},
        "stage_contract": {"source_only": True, "jobs_started_by_source": False, "arrays_read_by_source": False, "scientific_payloads_read": [], "launch_allowed": False, "actual_counts": None, "future_hash_policy": "all generated/native/typed/XMF/render hashes remain null until Root actual execution", "visual_qualification": "not granted", "precision_status": "not_accepted", "q_n": "not_granted", "independent_case_count_increment": 0},
        "rows": plan_rows,
    }
    write_json(package / "source-plan.json", plan)
    plan_sha = digest_file(package / "source-plan.json")

    owner_paths: dict[str, Path] = {}
    for cfg, row in zip(cfgs, plan_rows):
        owner = package / "owners" / f"{cfg['case_id']}.owner.json"
        owner_obj = make_owner(cfg, definition_paths[cfg["case_id"]], package / "source-plan.json", plan_sha, mutations[cfg["case_id"]], row["physical_condition_sha256"], row["source_plan_condition_sha256"])
        write_json(owner, owner_obj)
        owner_paths[cfg["case_id"]] = owner

    request_records: list[dict[str, Any]] = []
    for cfg, row in zip(cfgs, plan_rows):
        owner = owner_paths[cfg["case_id"]]
        req = make_request(cfg, definition_paths[cfg["case_id"]], owner, package / "source-plan.json", plan_sha, row["source_plan_condition_sha256"], row["physical_condition_sha256"], package)
        req_path = package / "requests" / f"{cfg['case_id']}-gencase.request.json"
        write_json(req_path, req)
        req_sha = digest_file(req_path)
        row["request_hash"] = req_sha
        request_records.append({"case_id": cfg["case_id"], "physical_case_id": cfg["physical_case_id"], "kind": "gencase", "path": str(req_path), "sha256": req_sha, "launch_allowed": False, "status": req["status"]})
    # The plan deliberately remains free of request hashes to avoid making the
    # owner/plan/request closure circular.  A sidecar records the request map.
    write_json(package / "requests/index.json", {"schema": "ds02.f4.first48.extension-disabled-gencase-index.v1", "source_plan": path_digest(package / "source-plan.json"), "rows": request_records, "launch_allowed": False, "source_only": True})
    write_json(package / "source-plan-request-hashes.json", {"schema": "ds02.f4.first48.extension-request-hash-sidecar.v1", "source_plan": path_digest(package / "source-plan.json"), "rows": [{"case_id": r["case_id"], "physical_condition_sha256": r["physical_condition_sha256"], "request_sha256": r["request_hash"]} for r in plan_rows], "note": "sidecar only; source-plan hash excludes request hashes"})

    current_plan = load_json(CURRENT24_PLAN)
    internal_plan = load_json(INTERNAL8_PLAN)
    fallback_plan = load_json(FALLBACK6_PLAN)
    current_evidence = evidence_summary()
    write_json(package / "evidence/current24-adoption-summary.json", current_evidence)
    write_json(package / "evidence/historical-negative-scope.json", {
        "schema": "ds02.f4.first48.historical-negative-scope.v1",
        "internal8_source_plan": path_digest(INTERNAL8_PLAN),
        "internal8_root_failure": internal_plan.get("root216_failure_evidence"),
        "fallback6_source_plan": path_digest(FALLBACK6_PLAN),
        "claim": "Root216 internal8 scientific negative is preserved; fallback6 and accepted anchors remain separate condition scopes; none are silently promoted by fresh102.",
        "source_only": True,
        "scientific_payloads_read": [],
    })
    inv = inventory(cfgs, current_plan, internal_plan, fallback_plan, current_evidence)
    write_json(package / "inventory/existing-physical-condition-inventory.json", inv)
    write_json(package / "inventory/overlap-audit.json", {"schema": "ds02.f4.first48.overlap-audit.v1", "current24_count": 24, "fresh102_count": 24, "historical_internal8_count": 8, "current24_plus_fresh102_target_count": 48, "intersections": inv["set_relations"], "all_required_intersections_empty": all(not v for v in inv["set_relations"].values()), "source_only": True})

    # Keep builder/validator/test sources in the package as reviewable code.
    shutil.copy2(Path(__file__), package / "workers/build_fresh102.py")
    (package / "workers/validate_fresh102_source.py").write_text(make_validator(), encoding="utf-8")
    (package / "tests/test_source_contract.py").write_text(make_tests(), encoding="utf-8")
    manifest = {
        "schema": "ds02.f4.first48.extension-source-manifest.v1",
        "family_id": FAMILY, "scope_id": PACKAGE_NAME,
        "source_only": True, "launch_allowed": False,
        "definition_count": 24, "owner_count": 24, "disabled_gencase_request_count": 24,
        "target_current_plus_prospective_count": 48,
        "current_exact24_visual_status": "Root561/570 actual typed/XMF metadata reviewed; allframe visual remains pending",
        "historical_internal8_status": "Root216 negative preserved and excluded",
        "future_artifact_hashes": None,
        "source_plan": path_digest(package / "source-plan.json"),
        "inventory": path_digest(package / "inventory/existing-physical-condition-inventory.json"),
        "overlap_audit": path_digest(package / "inventory/overlap-audit.json"),
        "requests": path_digest(package / "requests/index.json"),
    }
    write_json(package / "manifest.json", manifest)
    (package / "README.md").write_text(f'''# F4 first48 source-only extension (fresh102)\n\nThis package inventories F4 condition identities and adds 24 disjoint prospective finite-drop-pool rows to the current exact24 target. The current exact24 uses gaps 0.18, 0.22, and 0.24 m with x offsets +/-0.08 m, y offsets +/-0.04 m, and initial drop speeds 0.4/0.6 m/s. The fresh102 rows use gaps 0.20, 0.25, and 0.26 m over the same four offset combinations and two speeds. Therefore current24 plus fresh102 is 48 distinct physical tuples.\n\nThe historical centered internal8 (`.185` through `.255`, x=y=0, speed=.5) is inventoried separately. Root216 recorded a negative native initial check for that scope; those rows are preserved and excluded from the 48 target. The six centered lattice-aligned fallback rows and the three accepted centered/endpoint visual anchors are also separate condition scopes. The overlap audit is explicit and must remain empty before any Root registration.\n\nEach new XML changes only the finite falling-drop point and the `mkfluid=1` vertical velocity relative to the frozen F4 DP010 source. Pool, tank, wall faces, controls, DP=.01, no forcing/no mdbc, `TimeMax=1.2`, `TimeOut=.001`, and 1201 frames remain fixed. Candidate bounds stay inside the tank and maintain the source one-DP clearance above the pool; actual native occupancy, mass, generated hashes, QA, solver, typed, XMF, render, visual, precision, and Q-N status remain unknown or ungranted.\n\nThe 24 GenCase requests are disabled and Root-owned. They are source-only metadata handoffs with `launch_allowed=false`, `execution_allowed=false`, `independent_case_count_increment=0`, and null generated output hashes/counts. Root must review the exact adopted commit and run each request only through the registered CPU worker. No solver, conversion, render, scientific payload, shared registry, or ledger was touched while producing this package.\n''', encoding="utf-8")
    return package


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", type=Path, default=WORKTREE)
    args = ap.parse_args()
    print(build(args.worktree.resolve()))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
