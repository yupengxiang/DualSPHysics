import copy
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ds_data02_stage1_dispatch_v1 as dispatch  # noqa: E402
import ds_data02_stage1_production as production  # noqa: E402


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save_bytes(path, value=b"actual initial bytes"):
    path.write_bytes(value)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def install_consumed_stubs(tmp_path, monkeypatch):
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


def fixture(tmp_path, monkeypatch):
    strict_path, runtime_path, strict = install_consumed_stubs(tmp_path, monkeypatch)
    goal = save_bytes(tmp_path / "GOAL_STAGE1_VISUAL.md", b"Stage1 visual active goal\n")
    initial = save_bytes(tmp_path / "initial.bi4", b"genuine initial bytes")
    source = save_bytes(tmp_path / "source.xml", b"source xml bytes")
    input_bindings = [source]
    gencase = {
        "status": "completed",
        "returncode": 0,
        "solver_dimension_from_gencase": 3,
        "total_particles": 30,
        "fluid_particles": 20,
        "command": ["GenCase", "native", "native"],
        "input_hashes_at_launch": {source["path"]: source["sha256"]},
        "input_hashes_after_run": {source["path"]: source["sha256"]},
    }
    gen_binding = save_json(tmp_path / "gencase.json", gencase)
    checks = {
        "actual_3d": True,
        "positive_fluid_particles": True,
        "finite_state": True,
        "no_initial_fluid_solid_overlap": True,
        "equivalent_clone": True,
    }
    qa = {
        "schema": "ds02.stage1.initial-state-qa.v1",
        "checks": checks,
        "actual_initial_bytes": [initial],
        "provenance": {"gencase_receipt": gen_binding, "input_bindings": input_bindings},
    }
    qa_binding = save_json(tmp_path / "initial-qa.json", qa)
    mass_binding = save_json(
        tmp_path / "mass-discrepancy.json",
        {"status": "reported", "relative_difference": 0.17, "mass_rescaling": False},
    )
    physics = save_json(tmp_path / "physics.json", {"checks": {"finite_state": True}})
    geometry = save_json(tmp_path / "geometry.json", {"checks": {"finite_state": True}})
    motion = save_json(tmp_path / "motion.json", {"checks": {"finite_state": True}})
    overlap = save_json(
        tmp_path / "overlap.json",
        {"checks": {"finite_state": True, "no_initial_fluid_solid_overlap": True}},
    )
    case = {
        "case_id": "F3-AY050",
        "physical_case_id": "F3-TWOAXIS-AY050",
        "parameter_tuple": [0.50, 1.0, "nominal-pitch"],
        "physical_condition_sha256": "a" * 64,
        "physics": {"mechanism": "two-axis"},
        "geometry": {"tank": "finite-open-top"},
        "motion": {"ay": 0.50},
        "parent_group_id": "F3-twoaxis",
        "split": "visual-train",
        "numerical_recipe": {"dt": "adaptive-cfl05", "coef": 0.005},
        "actual_solver_command": ["/solver", "native", "{attempt_root}/out"],
        "actual_solver_cwd": str(tmp_path),
        "event_window_s": [0.0, 8.35],
        "input_bindings": input_bindings,
        "gencase_receipt": gen_binding,
        "initial_state_qa": qa_binding,
        "initial_mass_discrepancy_report": mass_binding,
        "physics_evidence": physics,
        "geometry_evidence": geometry,
        "motion_evidence": motion,
        "no_overlap_finite_state_evidence": overlap,
    }
    domain = save_json(
        tmp_path / "domain.json",
        {"schema": "ds02.stage1.frozen-physical-domain.v1", "cases": [copy.deepcopy(case)]},
    )
    manifest = save_json(
        tmp_path / "manifest.json",
        {"schema": "ds02.stage1.visual-case-manifest.v1", "cases": [copy.deepcopy(case)]},
    )
    decision = save_json(
        tmp_path / "visual-decision.json",
        {
            "schema": "ds02.stage1.root-visual-case-decision.v1",
            "status": "visual-approved-by-root",
            "family_id": "F3",
            "case_id": case["case_id"],
            "stage1_label": "视觉检查通过、数值精度未验收",
            "production_scope_approval": False,
            "numerical_precision_status": "not_accepted",
            "q_n": "not_granted",
            "q_e": "not_assessed",
            "physical_case_id": case["physical_case_id"],
            "physical_condition_sha256": case["physical_condition_sha256"],
            "physical_window_s": [0.0, 8.35],
            "bindings": {"goal": goal},
        },
    )
    visual_mother = save_json(tmp_path / "mother.json", {"review": "actual mother"})
    visual_endpoint = save_json(tmp_path / "endpoint.json", {"review": "actual endpoint"})
    visual_interior = save_json(tmp_path / "interior.json", {"review": "actual interior"})
    integrity = save_json(tmp_path / "integrity.json", {"all_saved_frames": True, "finite_state": True})
    entry = {
        "family_id": "F3",
        "scope_id": "f3-stage1-visual-v1",
        "visual_stage_profile": "stage1_visual",
        "goal_authority": goal,
        "root_visual_decision": decision,
        "visual_evidence": {
            "mother": [visual_mother],
            "endpoints": [visual_endpoint],
            "interior": [visual_interior],
            "final_visualization_decision": decision,
            "integrity": integrity,
        },
        "physical_domain": domain,
        "case_manifest": manifest,
    }
    index = save_json(
        tmp_path / "APPROVED_VISUAL_SCOPES.json",
        {
            "schema": "ds02.root-approved-visual-scopes.v1",
            "campaign_id": "DS-DATA-02",
            "goal_authority": goal,
            "interpretation": "Stage 1 visual-only launch bindings",
            "scopes": [entry],
        },
    )
    request = production.build_request(
        case,
        family_id="F3",
        scope_id=entry["scope_id"],
        attempt_id="attempt-001",
        adapter_path=HERE / "ds_data02_stage1_dispatch_v1.py",
        strict_path=strict_path,
        runtime_path=runtime_path,
        cwd=str(tmp_path),
        complete_event_window_s=[0.0, 8.35],
    )
    return {
        "index": index,
        "request": request,
        "entry": entry,
        "strict": strict,
        "goal": goal,
        "case": case,
    }


def test_visual_authorization_binds_sources_evidence_and_context(tmp_path, monkeypatch):
    data = fixture(tmp_path, monkeypatch)
    context = {}
    hashes = production.authorize(data["request"], index_path=data["index"]["path"], approval_context=context)
    assert str(data["index"]["path"]) not in hashes
    assert context["stage1_profile"] == "stage1_visual"
    assert context["precision_context"] == "pending"
    assert context["q_n"] == "not_granted"
    assert context["selected_entry_sha256"]
    assert context["source_paths"]["visual_stage_adapter"] in hashes
    assert context["source_paths"]["consumed_runtime"] in hashes
    assert production.revalidate_approval(context)["status"] == "selected_visual_approval_unchanged"


def test_unrelated_scope_can_be_added_but_selected_scope_revocation_stops(tmp_path, monkeypatch):
    data = fixture(tmp_path, monkeypatch)
    context = {}
    production.authorize(data["request"], index_path=data["index"]["path"], approval_context=context)
    document = json.loads(Path(data["index"]["path"]).read_text())
    document["scopes"].append({"family_id": "F7", "scope_id": "other", "visual_stage_profile": "stage1_visual"})
    save_json(Path(data["index"]["path"]), document)
    assert production.revalidate_approval(context)["status"] == "selected_visual_approval_unchanged"
    document["scopes"][0]["scope_id"] = "revoked"
    save_json(Path(data["index"]["path"]), document)
    with pytest.raises(ValueError, match="changed or was revoked"):
        production.revalidate_approval(context)


def test_tampering_command_tuple_or_mass_rescaling_is_rejected(tmp_path, monkeypatch):
    data = fixture(tmp_path, monkeypatch)
    request = copy.deepcopy(data["request"])
    request["command"] = ["/solver", "different"]
    with pytest.raises(ValueError, match="actual solver command"):
        production.authorize(request, index_path=data["index"]["path"])
    request = copy.deepcopy(data["request"])
    request["parameter_tuple"] = [0.50, 1.0, "different"]
    with pytest.raises(ValueError, match="parameter_tuple"):
        production.authorize(request, index_path=data["index"]["path"])
    request = copy.deepcopy(data["request"])
    request["mass_rescaling"] = True
    with pytest.raises(ValueError, match="rescaling"):
        production.authorize(request, index_path=data["index"]["path"])


def test_adapter_profile_gate_alias_lifecycle_and_receipt_sidecar(tmp_path, monkeypatch):
    data = fixture(tmp_path, monkeypatch)
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(data["request"], indent=2), encoding="utf-8")
    original_module = types.ModuleType("legacy-production")
    monkeypatch.setitem(sys.modules, "ds_data02_production", original_module)
    receipt_dir = tmp_path / "output"
    receipt_dir.mkdir()
    receipt_path = receipt_dir / "execution-receipt.json"
    original_bytes = b"legacy receipt bytes\n"
    receipt_path.write_bytes(original_bytes)

    def fake_run(path, **kwargs):
        assert sys.modules["ds_data02_production"] is production
        return {
            "status": "completed",
            "output_root": str(receipt_dir),
            "numerical_reference_status": "approved_scope_at_launch",
            "scientific_approval_at_launch": {"stage1_profile": "stage1_visual"},
        }

    data["strict"].run_request = fake_run
    result = dispatch.run_request(request_path)
    assert result["visual_stage1_semantic_sidecar"]
    assert sys.modules["ds_data02_production"] is original_module
    assert receipt_path.read_bytes() == original_bytes
    sidecar = json.loads(Path(result["visual_stage1_semantic_sidecar"]).read_text())
    assert sidecar["legacy_top_level_numerical_reference_status"] == "approved_scope_at_launch"
    assert sidecar["numerical_precision_status"] == "not_accepted"
    assert sidecar["final_acceptance"] == "separate_root_visual_and_numerical_acceptance"
    invalid = copy.deepcopy(data["request"])
    invalid.pop("visual_stage_profile")
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="visual_stage_profile"):
        dispatch.run_request(invalid_path)


def test_alias_context_restores_absent_legacy_module():
    sys.modules.pop("ds_data02_production", None)
    request = {"kind": "production", "visual_stage_profile": "stage1_visual"}
    with dispatch.install_stage1_authorizer_alias(request):
        assert sys.modules["ds_data02_production"] is production
    assert "ds_data02_production" not in sys.modules
