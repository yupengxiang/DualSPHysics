"""Source-only tests for the v2 visual authorizer.

The fixtures contain metadata and tiny placeholder files only.  No solver,
GenCase, converter, ParaView, or raw particle-array operation is performed.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ds_data02_stage1_dispatch_v2 as dispatch  # noqa: E402
import ds_data02_stage1_production_v2 as production  # noqa: E402


def save_bytes(path: Path, value: bytes = b"fixture") -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {"path": str(path), "sha256": hashlib.sha256(value).hexdigest()}


def save_json(path: Path, value: object) -> dict[str, str]:
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    return save_bytes(path, raw)


def install_consumed_stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strict_path = tmp_path / "ds_data02_strict_dispatch_v1.py"
    runtime_path = tmp_path / "ds_data02_runtime_v2.py"
    strict_path.write_text("# consumed strict fixture\n", encoding="utf-8")
    runtime_path.write_text("# consumed runtime fixture\n", encoding="utf-8")
    strict = types.ModuleType("ds_data02_strict_dispatch_v1")
    strict.__file__ = str(strict_path)
    runtime = types.ModuleType("ds_data02_runtime_v2")
    runtime.__file__ = str(runtime_path)
    monkeypatch.setitem(sys.modules, "ds_data02_strict_dispatch_v1", strict)
    monkeypatch.setitem(sys.modules, "ds_data02_runtime_v2", runtime)
    return strict_path, runtime_path, strict


def integrity_report(case_id: str | None = None) -> dict[str, object]:
    report: dict[str, object] = {
        "schema": "ds02.stage1.paraview-full-animation-integrity.v1",
        "frames": 836,
        "all_frames_rendered": True,
        "actual_times_preserved_exactly": True,
        "native_identity_axis_preserved": True,
        "nonfinite_active_states": 0,
        "diagnostic_only": False,
        "frame_diagnostics": [
            {"frame": i, "actual_time_s": i * 0.01, "active": 30, "fluid_points": 67500, "missing": 0}
            for i in range(836)
        ],
    }
    if case_id:
        report["case_id"] = case_id
    return report


def visual_fixture(tmp_path: Path, goal: dict[str, str], case: dict[str, str], *, historical=False):
    gif = save_bytes(tmp_path / f"{case['case_id']}.gif", b"original saved animation")
    trajectory = save_bytes(tmp_path / f"{case['case_id']}.h5", b"original typed trajectory")
    decision = {
        "schema": "ds02.stage1.root-visual-case-decision.v1",
        "status": "visual-approved-by-root",
        "family_id": "F3",
        "case_id": case["case_id"],
        "physical_case_id": case["physical_case_id"],
        "physical_condition_sha256": case["physical_condition_sha256"],
        "stage1_label": "视觉检查通过、数值精度未验收",
        "production_scope_approval": False,
        "numerical_precision_status": "not_accepted",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "physical_window_s": [0.0, 8.35],
        "frames": 836,
        "native_fluid_particles": 67500,
        "visual_rejection_checks": {
            "nonfinite_active_state": "strict all-frame audit reports0",
            "unexplained_large_particle_loss": "observation retained",
        },
        "bindings": {"goal": goal, "animation_gif": gif, "trajectory_binding": trajectory},
    }
    decision_path = save_json(tmp_path / f"{case['case_id']}-decision.json", decision)
    report_path = save_json(tmp_path / f"{case['case_id']}-integrity.json", integrity_report(case["case_id"]))
    return {
        "case_id": case["case_id"],
        "status": "historical_visual_reference_only" if historical else "visual-approved-by-root",
        "decision": decision_path,
        "integrity_report": report_path,
    }


def clone_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strict_path, runtime_path, strict = install_consumed_stubs(tmp_path, monkeypatch)
    goal = save_bytes(tmp_path / "GOAL_STAGE1_VISUAL.md", b"Stage1 visual current goal\n")
    parent_xml = save_bytes(tmp_path / "parent.xml", b"genuine parent XML")
    parent_bi4 = save_bytes(tmp_path / "parent.bi4", b"genuine parent BI4")
    forcing = save_bytes(tmp_path / "clone-forcing.csv", b"frozen forcing")
    prepared_report_path = tmp_path / "prepared-report.json"
    parent_gen = {
        "status": "completed",
        "returncode": 0,
        "solver_dimension_from_gencase": 3,
        "total_particles": 30,
        "fluid_particles": 20,
        "input_hashes_at_launch": {},
        "input_hashes_after_run": {},
        "command": ["GenCase", "parent"],
    }
    parent_gen_binding = save_json(tmp_path / "parent-gencase.json", parent_gen)
    parent_qa = {
        "schema": "ds02.initial-qa.v1",
        "cases": [
            {
                "case_id": "F3-MOTHER",
                "passed": True,
                "native_particles": 30,
                "native_fluid": 20,
                "actual_3d": True,
                "native_initial_BI4_sha256": parent_bi4["sha256"],
                "generated_xml_sha256": parent_xml["sha256"],
            }
        ],
    }
    parent_qa_binding = save_json(tmp_path / "parent-initial-qa.json", parent_qa)
    clone_receipt = save_json(
        tmp_path / "clone-preparation.json",
        {"status": "completed", "returncode": 0, "production_approval": "none"},
    )
    shared = {
        "qa_semantics": "genuine_3d_parent",
        "parent_case_id": "F3-MOTHER",
        "genuine_gencase_receipt": parent_gen_binding,
        "native_initial_qa": parent_qa_binding,
        "generated_xml": parent_xml,
        "initial_bi4": parent_bi4,
        "source_documents": {"first8_preparation_receipt": clone_receipt},
    }
    clone_case = {
        "role": "interior01",
        "case_id": "F3-CLONE",
        "physical_case_id": "F3-PHYSICAL-CLONE",
        "physical_condition_sha256": "c" * 64,
        "transverse_amplitude_m_s2": 0.32,
        "nominal_pitch_multiplier": 1.0,
        "parameter_tuple": {"amplitude": 0.32, "pitch": 1.0},
        "qa_semantics": "exact_initial_clone_of_genuine_3d_parent",
        "independent_case_count_increment": 0,
        "numerical_recipe": "frozen-recipe",
        "actual_solver_command": ["solver", "-mdbc_noslip:1", "prefix", "{attempt_root}/out"],
        "actual_solver_cwd": str(tmp_path),
        "event_window_s": [0.0, 8.35],
        "prepared_input": {
            "report": prepared_report_path if False else None,
            "forcing": forcing,
            "generated_xml": parent_xml,
            "initial_bi4": parent_bi4,
        },
    }
    prepared_report = {
        "case_id": clone_case["case_id"],
        "physical_case_id": clone_case["physical_case_id"],
        "xml_sha256": parent_xml["sha256"],
        "bi4_sha256": parent_bi4["sha256"],
        "xml_byte_identical_to_baseline": True,
        "initial_bi4_byte_identical_to_baseline": True,
        "production_approval": "none",
        "independent_case_increment": 0,
    }
    clone_case["prepared_input"]["report"] = save_json(prepared_report_path, prepared_report)
    for name in ("mass", "physics", "geometry", "motion", "overlap"):
        value = {"checks": {"finite_state": True}}
        if name == "overlap":
            value["checks"]["no_initial_fluid_solid_overlap"] = True
        key = {
            "mass": "initial_mass_discrepancy_report",
            "physics": "physics_evidence",
            "geometry": "geometry_evidence",
            "motion": "motion_evidence",
            "overlap": "no_overlap_finite_state_evidence",
        }[name]
        clone_case[key] = save_json(tmp_path / f"{name}.json", value)
    clone_case["input_bindings"] = [forcing, parent_xml, parent_bi4, clone_case["prepared_input"]["report"]]

    observed = {
        "case_id": "F3-OBS",
        "physical_case_id": "F3-PHYSICAL-OBS",
        "physical_condition_sha256": "o" * 64,
        "parameter_tuple": {"amplitude": 0.25, "pitch": 1.0},
    }
    domain = {"schema": "ds02.stage1.frozen-physical-domain.v1", "cases": [observed, copy.deepcopy(clone_case)]}
    manifest = {
        "schema": "ds02.stage1.visual-case-manifest.v1",
        "cases": [observed, copy.deepcopy(clone_case)],
        "shared_initial_state": shared,
    }
    domain_binding = save_json(tmp_path / "domain.json", domain)
    manifest_binding = save_json(tmp_path / "manifest.json", manifest)
    domain_decision = {
        "schema": "ds02.stage1.root-visual-domain-decision.v1",
        "status": "visual-domain-approved-by-root",
        "family_id": "F3",
        "scope_id": "f3-v2",
        "stage1_label": "视觉检查通过、数值精度未验收",
        "goal_authority": goal,
        "observed_case_ids": ["F3-OBS"],
        "prospective_case_ids": ["F3-CLONE"],
        "selected_case_ids": ["F3-CLONE"],
        "no_interpolation_or_extrapolation": True,
        "production_scope_approval": False,
        "numerical_precision_status": "not_accepted",
        "q_n": "not_granted",
        "q_e": "not_assessed",
    }
    decision_binding = save_json(tmp_path / "domain-decision.json", domain_decision)
    observed_visual = visual_fixture(tmp_path, goal, observed, historical=False)
    entry = {
        "family_id": "F3",
        "scope_id": "f3-v2",
        "visual_stage_profile": "stage1_visual",
        "goal_authority": goal,
        "root_visual_domain_decision": decision_binding,
        "physical_domain": domain_binding,
        "case_manifest": manifest_binding,
        "visual_evidence": {"observed": [observed_visual], "prospective": []},
    }
    index = save_json(
        tmp_path / "APPROVED_VISUAL_SCOPES.json",
        {
            "schema": "ds02.root-approved-visual-scopes.v2",
            "campaign_id": "DS-DATA-02",
            "goal_authority": goal,
            "scopes": [entry],
        },
    )
    request = production.build_prospective_request(
        manifest,
        "F3-CLONE",
        family_id="F3",
        scope_id="f3-v2",
        attempt_id="attempt-001",
        adapter_path=HERE / "ds_data02_stage1_dispatch_v2.py",
        strict_path=strict_path,
        runtime_path=runtime_path,
        command=clone_case["actual_solver_command"],
        cwd=str(tmp_path),
        complete_event_window_s=[0.0, 8.35],
    )
    return locals()


def test_prospective_clone_authorization_does_not_require_future_visual(tmp_path, monkeypatch):
    data = clone_fixture(tmp_path, monkeypatch)
    context: dict[str, object] = {}
    hashes = production.authorize(data["request"], index_path=data["index"]["path"], approval_context=context)
    assert context["prospective_domain_launch"] is True
    assert context["q_n"] == "not_granted"
    assert any("parent-gencase.json" in path for path in hashes)
    assert production.revalidate_approval(context)["status"] == "selected_visual_approval_unchanged"


def test_visual_integrity_content_tamper_is_rejected(tmp_path, monkeypatch):
    data = clone_fixture(tmp_path, monkeypatch)
    decision = json.loads(Path(data["observed_visual"]["integrity_report"]["path"]).read_text())
    decision["all_frames_rendered"] = False
    report_path = Path(data["observed_visual"]["integrity_report"]["path"])
    report_path.write_text(json.dumps(decision), encoding="utf-8")
    index_document = json.loads(Path(data["index"]["path"]).read_text(encoding="utf-8"))
    binding = index_document["scopes"][0]["visual_evidence"]["observed"][0]["integrity_report"]
    binding["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    Path(data["index"]["path"]).write_text(json.dumps(index_document), encoding="utf-8")
    with pytest.raises(ValueError, match="all_frames_rendered"):
        production.authorize(data["request"], index_path=data["index"]["path"])


def test_genuine_generation_branch_does_not_require_clone_flag(tmp_path, monkeypatch):
    strict_path, runtime_path, _ = install_consumed_stubs(tmp_path, monkeypatch)
    source = save_bytes(tmp_path / "source.xml", b"source")
    initial = save_bytes(tmp_path / "initial.bi4", b"initial")
    gen = save_json(
        tmp_path / "gencase.json",
        {
            "status": "completed",
            "returncode": 0,
            "solver_dimension_from_gencase": 3,
            "total_particles": 30,
            "fluid_particles": 20,
            "command": ["GenCase", "source"],
            "input_hashes_at_launch": {source["path"]: source["sha256"]},
            "input_hashes_after_run": {source["path"]: source["sha256"]},
        },
    )
    qa = save_json(
        tmp_path / "qa.json",
        {
            "checks": {"passed": True, "actual_3d": True, "native_fluid": 20},
            "actual_initial_bytes": [initial],
            "provenance": {"gencase_receipt": gen, "input_bindings": [source]},
        },
    )
    case = {
        "qa_semantics": "genuine_3d_generation",
        "input_bindings": [source, initial],
        "gencase_receipt": gen,
        "initial_state_qa": qa,
        "initial_mass_discrepancy_report": save_json(tmp_path / "genuine-mass.json", {"relative_difference": 0.1}),
        "physics_evidence": save_json(tmp_path / "genuine-physics.json", {"checks": {"finite_state": True}}),
        "geometry_evidence": save_json(tmp_path / "genuine-geometry.json", {"checks": {"finite_state": True}}),
        "motion_evidence": save_json(tmp_path / "genuine-motion.json", {"checks": {"finite_state": True}}),
        "no_overlap_finite_state_evidence": save_json(tmp_path / "genuine-overlap.json", {"checks": {"finite_state": True, "no_initial_fluid_solid_overlap": True}}),
    }
    request = {"input_files": [str(path.resolve()) for path in tmp_path.iterdir() if path.is_file()]}
    out = production._actual_case_bindings_v2(case, request, {}, base=tmp_path)
    assert out["qa_semantics"] == "genuine_3d_generation"
    assert "parent_gencase_receipt" not in out["qa_evidence"]


def test_domain_record_042_is_current_goal_bound_and_explicit():
    path = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    membership = production._ensure_domain_decision_v2(
        document,
        family_id="F3",
        scope_id="F3_STAGE1_FIRST8_AY0250_AY0750_VISUAL_V1",
        current_goal=document["goal_authority"],
    )
    assert len(membership["prospective"]) == 5
    assert membership["selected"] == membership["prospective"]


def test_v2_dispatch_restores_alias_and_preserves_receipt(tmp_path, monkeypatch):
    data = clone_fixture(tmp_path, monkeypatch)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(data["request"]), encoding="utf-8")
    original_module = types.ModuleType("legacy-production")
    monkeypatch.setitem(sys.modules, "ds_data02_production", original_module)
    output = tmp_path / "output"
    output.mkdir()
    receipt_path = output / "execution-receipt.json"
    original_bytes = b"legacy receipt bytes\n"
    receipt_path.write_bytes(original_bytes)

    def fake_run(path, **kwargs):
        assert sys.modules["ds_data02_production"] is production
        return {
            "status": "completed",
            "output_root": str(output),
            "numerical_reference_status": "approved_scope_at_launch",
            "scientific_approval_at_launch": {"stage1_profile": "stage1_visual"},
        }

    data["strict"].run_request = fake_run
    result = dispatch.run_request(request_path)
    assert result["visual_stage1_semantic_sidecar"]
    assert sys.modules["ds_data02_production"] is original_module
    assert receipt_path.read_bytes() == original_bytes
    sidecar = json.loads(Path(result["visual_stage1_semantic_sidecar"]).read_text())
    assert sidecar["schema"] == "ds02.stage1.visual-receipt-semantics.v2"
    assert sidecar["future_case_visual_review"] == "required_after_actual_complete_run"
