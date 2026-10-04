#!/usr/bin/env python3
"""Validate the concrete F3 v3 package and optionally run v2 AUTHORIZE.

All checks are metadata/hash checks.  The optional AUTHORIZE pass uses the
fixture index and the actual Root visual records; it never calls the strict
dispatcher and never launches a workload.  The fixture is explicitly marked
``execution_allowed: false`` and is not an integration approval index.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "F3_FIRST8_V3_CASE_MANIFEST.json"
DOMAIN = HERE / "F3_FIRST8_V3_PHYSICAL_DOMAIN.json"
INDEX = HERE / "F3_V3_AUTHORIZE_PREFLIGHT_INDEX.fixture.json"
TEMPLATES = HERE / "build_f3_v3_templates.py"
GOAL = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
)
ROOT_DOMAIN_DECISION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json"
)
EXPECTED_GOAL_SHA = "53d422511b5581266410de92c54627ac67e8085eccb75a9ebfe57de10a34316a"
EXPECTED_DOMAIN_DECISION_SHA = "7f33f48ddd33446a9f6684c673764727f1f01c1f6390b8d409facb9a91daea1e"
EXPECTED_PROSPECTIVE = {
    "F3_STAGE1_DP006_P1000_AY0320",
    "F3_STAGE1_DP006_P1000_AY0390",
    "F3_STAGE1_DP006_P1000_AY0460",
    "F3_STAGE1_DP006_P1000_AY0570",
    "F3_STAGE1_DP006_P1000_AY0640",
}
EXPECTED_OBSERVED = {
    "F3_STAGE1_DP006_P1000_AY0250",
    "F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005",
    "F3_STAGE1_DP006_P1000_AY0750",
}
EXPECTED_AMPLITUDES = {
    "F3_STAGE1_DP006_P1000_AY0320": 0.32,
    "F3_STAGE1_DP006_P1000_AY0390": 0.39,
    "F3_STAGE1_DP006_P1000_AY0460": 0.46,
    "F3_STAGE1_DP006_P1000_AY0570": 0.57,
    "F3_STAGE1_DP006_P1000_AY0640": 0.64,
}
EXPECTED_CONDITIONS = {
    "F3_STAGE1_DP006_P1000_AY0320": "4f1f90c4f3cc9c12a6c016bac7199436ac9540d3af8249000637562b5304e5e0",
    "F3_STAGE1_DP006_P1000_AY0390": "a7821ee8ef0d72cf3f503ef043ebcf76248d0316d5ea29226c075fe489c4e201",
    "F3_STAGE1_DP006_P1000_AY0460": "1ddefb9be61452ae973a9f8982a27f09b170b70b41524311d483d71240e08863",
    "F3_STAGE1_DP006_P1000_AY0570": "df6cd84199c3a105070f144ff2724a3e1b3502a4059f2c0ade9791b924ede67a",
    "F3_STAGE1_DP006_P1000_AY0640": "1a2663c161f036da596ae67a67d58ec2eac0c3568cb5c058f53b1f561c410daf",
}
PARENT_XML_SHA = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
PARENT_BI4_SHA = "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80"


class PackageError(ValueError):
    pass


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # pragma: no cover - message adds path context
        raise PackageError(f"cannot load JSON: {path}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def check_binding(value: Any, label: str) -> None:
    require(isinstance(value, Mapping), f"{label} must be a path/hash binding")
    path_value = value.get("path")
    expected = value.get("sha256")
    require(isinstance(path_value, str) and path_value, f"{label}.path is required")
    require(isinstance(expected, str) and len(expected) == 64, f"{label}.sha256 is required")
    path = Path(path_value)
    require(path.is_file(), f"{label} is missing: {path}")
    require(digest(path) == expected, f"{label} hash mismatch: {path}")


def check_nested_bindings(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            check_binding(value, label)
            return
        for key, child in value.items():
            check_nested_bindings(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_nested_bindings(child, f"{label}[{index}]")


def load_templates_module():
    spec = importlib.util.spec_from_file_location("f3_v3_templates", TEMPLATES)
    if spec is None or spec.loader is None:
        raise PackageError("cannot import v3 template builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_metadata() -> dict[str, Any]:
    manifest = load(MANIFEST)
    domain = load(DOMAIN)
    index = load(INDEX)
    require(manifest.get("schema") == "ds02.stage1.visual-case-manifest.v3", "manifest schema mismatch")
    require(domain.get("schema") == "ds02.stage1.frozen-physical-domain.v3", "domain schema mismatch")
    require(manifest.get("production_scope_approval") is False, "manifest grants production scope")
    require(domain.get("production_scope_approval") is False, "domain grants production scope")
    require(manifest.get("q_n") == "not_granted" and manifest.get("q_e") == "not_assessed", "manifest Q flags changed")
    require(domain.get("q_n") == "not_granted" and domain.get("q_e") == "not_assessed", "domain Q flags changed")
    require(digest(GOAL) == EXPECTED_GOAL_SHA, "current GOAL authority changed")
    require(digest(ROOT_DOMAIN_DECISION) == EXPECTED_DOMAIN_DECISION_SHA, "Root domain decision changed")
    require(manifest.get("goal_authority", {}).get("sha256") == EXPECTED_GOAL_SHA, "manifest goal binding changed")
    require(manifest.get("root_visual_domain_decision", {}).get("sha256") == EXPECTED_DOMAIN_DECISION_SHA, "manifest domain decision binding changed")

    domain_by_id = {row.get("case_id"): row for row in domain.get("cases", [])}
    manifest_by_id = {row.get("case_id"): row for row in manifest.get("cases", [])}
    require(set(domain_by_id) == EXPECTED_OBSERVED | EXPECTED_PROSPECTIVE, "domain membership is not the frozen eight")
    require(set(manifest_by_id) == set(domain_by_id), "manifest/domain membership differs")
    require(len(domain_by_id) == 8 and len(manifest_by_id) == 8, "first8 must contain exactly eight rows")
    for case_id, row in manifest_by_id.items():
        frozen = domain_by_id[case_id]
        require(row.get("physical_case_id") == frozen.get("physical_case_id"), f"{case_id} physical identity differs")
        require(row.get("physical_condition_sha256") == frozen.get("physical_condition_sha256"), f"{case_id} condition differs")
        require(row.get("transverse_amplitude_m_s2") == frozen.get("transverse_amplitude_m_s2"), f"{case_id} amplitude differs")
        require(row.get("nominal_pitch_multiplier") == frozen.get("nominal_pitch_multiplier"), f"{case_id} pitch differs")

    for case_id in EXPECTED_PROSPECTIVE:
        row = manifest_by_id[case_id]
        require(row.get("role", "").startswith("interior"), f"{case_id} is not an interior row")
        require(row.get("transverse_amplitude_m_s2") == EXPECTED_AMPLITUDES[case_id], f"{case_id} SI amplitude changed")
        require(row.get("physical_condition_sha256") == EXPECTED_CONDITIONS[case_id], f"{case_id} condition hash changed")
        require(row.get("nominal_pitch_multiplier") == 1.0, f"{case_id} pitch changed")
        require(row.get("qa_semantics") == "exact_initial_clone_of_genuine_3d_parent", f"{case_id} clone semantics changed")
        require(row.get("independent_case_count_increment") == 0, f"{case_id} changes independent count")
        require(row.get("production_approval") == "none", f"{case_id} claims production approval")
        require(row.get("root_visual_decision") is None, f"{case_id} has a future visual decision")
        require(row.get("full_saved_frame_integrity") is None, f"{case_id} has a future frame report")
        require(row.get("event_window_s") == [0.0, 8.35], f"{case_id} event window changed")
        require(row.get("complete_event_window_s") == [0.0, 8.35], f"{case_id} request window changed")
        require(row.get("save_interval_s") == 0.01 and row.get("expected_saved_frames") == 836, f"{case_id} save contract changed")
        require(row.get("actual_solver_cwd") == "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab", f"{case_id} solver cwd changed")
        command = row.get("actual_solver_command")
        require(isinstance(command, list) and command[-2:] == ["-tmax:8.35", "-tout:0.01"], f"{case_id} solver argv is not frozen")
        require(command[1] == "-mdbc_noslip:1", f"{case_id} solver mode changed")
        require(row.get("physics", {}).get("control_family_id") == "F3_CTRL_TWOAXIS_TRANSVERSE_LINACC_V1", f"{case_id} physics owner changed")
        require(row.get("physics", {}).get("geometry_family_id") == "F3_CELL3_PLAIN", f"{case_id} geometry family changed")
        require(row.get("physics", {}).get("mass_policy") == "native_massfluid_no_rescaling", f"{case_id} mass policy changed")
        require(row.get("motion", {}).get("actual_forcing_sha256") == row["prepared_input"]["forcing"]["sha256"], f"{case_id} forcing identity differs")
        require(row.get("motion", {}).get("source_forcing_sha256") == "6f42660acb261a5e451436bb3087af86d09310085ea1ee48d0b02eae8b3205d3", f"{case_id} forcing source changed")
        prepared = row.get("prepared_input")
        require(isinstance(prepared, Mapping), f"{case_id} prepared inputs missing")
        require(prepared.get("generated_xml", {}).get("sha256") == PARENT_XML_SHA, f"{case_id} XML hash changed")
        require(prepared.get("initial_bi4", {}).get("sha256") == PARENT_BI4_SHA, f"{case_id} BI4 hash changed")
        require(prepared.get("xml_byte_identical_to_baseline") is True, f"{case_id} XML clone assertion missing")
        require(prepared.get("initial_bi4_byte_identical_to_baseline") is True, f"{case_id} BI4 clone assertion missing")
        require(row.get("initial_native_reference", {}).get("native_particles") == 179208, f"{case_id} native particle count changed")
        require(row.get("initial_native_reference", {}).get("native_fluid") == 67500, f"{case_id} native fluid count changed")
        require(row.get("initial_native_reference", {}).get("native_fixed") == 111708, f"{case_id} native fixed count changed")
        require(row.get("initial_native_reference", {}).get("continuum_reference_mass_kg") == 14.58, f"{case_id} continuum mass changed")
        require(row.get("initial_native_reference", {}).get("native_fluid_mass_kg") == 14.580000000000002, f"{case_id} native mass changed")
        for key in ("initial_mass_discrepancy_report", "physics_evidence", "geometry_evidence", "motion_evidence", "no_overlap_finite_state_evidence"):
            check_binding(row.get(key), f"{case_id}.{key}")
        for key in ("physics_evidence", "geometry_evidence", "motion_evidence", "no_overlap_finite_state_evidence"):
            document = load(Path(row[key]["path"]))
            checks = document.get("checks", document)
            require(checks.get("finite_state") is True, f"{case_id}.{key} finite_state missing")
        overlap = load(Path(row["no_overlap_finite_state_evidence"]["path"]))
        require(overlap.get("checks", {}).get("no_initial_fluid_solid_overlap") is True, f"{case_id} initial overlap check missing")
        mass = load(Path(row["initial_mass_discrepancy_report"]["path"]))
        require(mass.get("native_fluid_mass_kg") == 14.580000000000002, f"{case_id} native mass report changed")
        require(mass.get("continuum_reference_mass_kg") == 14.58, f"{case_id} continuum mass report changed")
        require(mass.get("mass_rescaling") is False, f"{case_id} mass rescaling is enabled")
        check_nested_bindings(row, f"manifest.{case_id}")

    require(index.get("status") == "preflight_fixture_only", "preflight index is no longer a fixture")
    require(index.get("scopes", [{}])[0].get("execution_allowed") is False, "preflight index allows execution")
    require(index.get("scopes", [{}])[0].get("production_scope_approval") is False, "preflight scope grants production")
    check_nested_bindings(index, "preflight_index")
    return {
        "manifest_cases": len(manifest_by_id),
        "prospective_cases": len(EXPECTED_PROSPECTIVE),
        "observed_cases": len(EXPECTED_OBSERVED),
        "status": "metadata_and_hash_invariants_passed",
    }


def run_authorize_preflight() -> list[dict[str, Any]]:
    module = load_templates_module()
    results = []
    for case_id in sorted(EXPECTED_PROSPECTIVE):
        results.append(module.authorize_actual_preflight(case_id))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-authorize", action="store_true", help="only verify metadata/hash invariants")
    args = parser.parse_args(argv)
    result = validate_metadata()
    if not args.skip_authorize:
        result["authorize_preflight"] = run_authorize_preflight()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
