#!/usr/bin/env python3
"""Static, source-only validator for the F3 fresh078 handoff.

This validator reads package JSON and Python text only. It never opens, hashes,
or decodes BI4/CSV/H5/HDF5/VTK/NumPy payloads and never launches a worker.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BAD_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".npy", ".npz", ".gif"}
DECODER = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
PARTVTK = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
N3_SHA = "74e0f88c131f48e06a7605de04611296c7a4405e47b2cfc5099a56f9bb94e4fa"
N3_PATH_PART = "root_followup_090_stage1_f4_root242_typed_xmf_render_bind_v1/render/n3-vector-spec.json"
RENDERER_PART = "root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise AssertionError(message)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_disabled(doc: dict[str, Any], label: str) -> None:
    expect(doc.get("source_only") is True, f"{label}: source_only")
    expect(doc.get("execution_allowed") is False, f"{label}: execution_allowed")
    expect(doc.get("launch_allowed") is False, f"{label}: launch_allowed")
    expect(doc.get("q_n") == "not_granted", f"{label}: q_n")
    expect(doc.get("production_approval") == "none", f"{label}: production_approval")
    expect(doc.get("numerical_precision_status") == "not_accepted", f"{label}: precision")
    expect(doc.get("independent_case_count_increment") == 0, f"{label}: case increment")
    expect(doc.get("actual_converter_physical_condition_scope", {}).get("schema") == "legacy-owner-scope.v0", f"{label}: scope schema")
    expect(doc.get("actual_converter_physical_condition_scope_sha256") == doc.get("physical_condition_sha256"), f"{label}: scope hash")
    expect(doc.get("source_physical_condition_sha256") != doc.get("physical_condition_sha256"), f"{label}: source/actual hash collapse")
    future = doc.get("future_outputs", {})
    for key, value in future.items():
        if key.endswith("_sha256"):
            expect(value is None, f"{label}: future hash populated: {key}")
        if key == "visual_decision":
            expect(value is None, f"{label}: future visual decision populated")


def assert_input_closure(doc: dict[str, Any], label: str) -> None:
    files = doc.get("input_files")
    hashes = doc.get("input_sha256")
    expect(isinstance(files, list), f"{label}: input_files is not a list")
    expect(isinstance(hashes, dict), f"{label}: input_sha256 is not an object")
    for item in files:
        expect(isinstance(item, str), f"{label}: non-string input file")
        expect("root_followup_077" not in item, f"{label}: stale fresh077 input {item}")
        expect(item in hashes, f"{label}: missing input hash key {item}")
    for item in hashes:
        expect("root_followup_077" not in item, f"{label}: stale fresh077 hash key {item}")


def assert_scope_pair(doc: dict[str, Any], owner: dict[str, Any], label: str) -> None:
    expect(doc.get("physical_condition_sha256") == owner.get("physical_condition_sha256"), f"{label}: actual condition hash")
    expect(doc.get("source_physical_condition_sha256") == owner.get("source_physical_condition_sha256"), f"{label}: source condition hash")
    expect(doc.get("source_parameter_tuple") == owner.get("source_parameter_tuple"), f"{label}: source tuple")
    expect(doc.get("actual_converter_physical_condition_scope") == owner.get("actual_converter_physical_condition_scope"), f"{label}: scope object")


def assert_n3(doc: dict[str, Any], label: str) -> None:
    n3 = doc.get("n3_vector_spec")
    expect(isinstance(n3, dict), f"{label}: missing N3 spec")
    expect(n3.get("sha256") == N3_SHA, f"{label}: N3 sha")
    expect(n3.get("path", "").endswith(N3_PATH_PART), f"{label}: N3 path")
    expect(n3.get("field") == "velocity", f"{label}: N3 field")
    expect(n3.get("components") == ["vx", "vy", "vz"], f"{label}: N3 components")
    expect(n3.get("semantic_type") == "N3", f"{label}: N3 semantic type")
    expect(n3.get("preserve_all_native_fields") is True, f"{label}: native field retention")


def main() -> None:
    expect(HERE.name == "root_followup_078_f3_actual_converter_scope_typed_xmf_v1", f"unexpected package: {HERE}")
    package_files = [path for path in HERE.rglob("*") if path.is_file()]
    expect(not any(path.suffix.lower() in BAD_SUFFIXES for path in package_files), "scientific payload shipped in source package")
    for path in package_files:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        elif path.suffix == ".json":
            load(path)

    manifest = load(HERE / "manifest.json")
    expect(manifest.get("fresh_id") == "fresh078", "manifest fresh id")
    expect(manifest.get("family_id") == "F3", "manifest family")
    expect(manifest.get("case_count") == 14, "manifest case count")
    expect(manifest.get("arrays_read") is False, "manifest arrays")
    expect(manifest.get("jobs_started") is False, "manifest jobs")
    expect(manifest.get("shared_state_modified") is False, "manifest shared state")
    expect(manifest.get("all_typed_requests_disabled") is True, "manifest typed disabled")
    expect(manifest.get("all_xmf_requests_disabled") is True, "manifest xmf disabled")
    expect(manifest.get("all_render_requests_disabled") is True, "manifest render disabled")
    manifest_names = {entry.get("path") for entry in manifest.get("files", [])}
    expect("source_metadata_validator.py" in manifest_names, "manifest missing validator")

    selection = load(HERE / "metadata/selection.json")
    expect(selection.get("case_count") == 14, "selection case count")
    expect(selection.get("arrays_read") is False and selection.get("jobs_started") is False, "selection side effects")
    cases = {str(row["case_id"]): row for row in selection.get("cases", [])}
    expect(len(cases) == 14, "selection case identity count")

    audit = load(HERE / "metadata/actual-converter-scope-audit.json")
    expect(audit.get("arrays_read") is False and audit.get("jobs_started") is False and audit.get("shared_state_modified") is False, "audit side effects")
    expect(audit.get("all_native_completed0") is True, "audit native completion")
    expect(audit.get("all_counts") == {"total_particles": 179208, "fixed_particles": 111708, "fluid_particles": 67500, "moving_particles": 0, "dimension": 3, "frames": 836}, "audit counts")
    audit_cases = {str(row["case_id"]): row for row in audit.get("cases", [])}
    expect(set(audit_cases) == set(cases), "audit/selection identity mismatch")

    owners = {path.stem.split(".actual-converter-scope.owner")[0]: load(path) for path in (HERE / "owners").glob("*.json")}
    expect(set(owners) == set(cases), "owner identity mismatch")
    for case_id, owner in owners.items():
        label = f"owner:{case_id}"
        expect(owner.get("source_only") is True and owner.get("execution_allowed") is False, f"{label}: enablement")
        expect("physical_binding" not in owner or owner.get("physical_binding") is None, f"{label}: fabricated physical_binding")
        scope = owner.get("actual_converter_physical_condition_scope")
        expect(scope and scope.get("schema") == "legacy-owner-scope.v0", f"{label}: actual scope")
        expect(owner.get("physical_condition_sha256") == canonical_hash(scope), f"{label}: canonical scope hash")
        expect(owner.get("actual_converter_physical_condition_scope_sha256") == owner.get("physical_condition_sha256"), f"{label}: scope hash field")
        source = owner.get("canonical_physical_binding")
        expect(isinstance(source, dict), f"{label}: source canonical binding")
        expect(owner.get("source_physical_condition_sha256") == source.get("physical_condition_sha256"), f"{label}: source hash provenance")
        expect(owner.get("source_parameter_tuple") == source.get("parameter_tuple"), f"{label}: source tuple provenance")
        native = owner.get("native_full836_binding", {})
        quality = native.get("quality", {})
        expect(native.get("status") == "completed" and native.get("returncode") == 0, f"{label}: native receipt")
        expect(native.get("actual_3d") is True and native.get("dimension") == 3, f"{label}: native dimensionality")
        expect(native.get("expected_saved_frames") == 836 and quality.get("saved_frames") == 836, f"{label}: native frames")
        expect(native.get("total_particles") == 179208 and quality.get("total_particles") == 179208, f"{label}: total count")
        expect(native.get("fixed_particles") == 111708 and quality.get("fixed_particles") == 111708, f"{label}: fixed count")
        expect(native.get("fluid_particles") == 67500 and quality.get("fluid_particles") == 67500, f"{label}: fluid count")
        expect(native.get("moving_particles") == 0 and quality.get("moving_particles") == 0, f"{label}: moving count")
        expect(owner.get("typed_scope_provenance", {}).get("typed_receipt_sha256") is None, f"{label}: typed future receipt")

    typed = {path.stem: load(path) for path in (HERE / "requests/typed").glob("*.json")}
    expect(set(typed) == set(cases), "typed identity mismatch")
    for case_id, request in typed.items():
        label = f"typed:{case_id}"
        owner = owners[case_id]
        assert_disabled(request, label)
        assert_input_closure(request, label)
        assert_scope_pair(request, owner, label)
        owner_path = request.get("owner_metadata", {}).get("path", "")
        expect(owner_path.endswith(f"owners/{case_id}.actual-converter-scope.owner.json"), f"{label}: owner path")
        expect(owner_path in request["input_files"], f"{label}: owner not in input files")
        expect(request.get("decoder_binding") == {"path": DECODER, "sha256": DECODER_SHA}, f"{label}: decoder binding")
        expect(request.get("partvtk_binding") == {"path": PARTVTK, "sha256": PARTVTK_SHA}, f"{label}: PartVTK binding")
        command = request.get("command", [])
        expect("--decoder" in command and command[command.index("--decoder") + 1] == DECODER, f"{label}: decoder command")
        expect("--partvtk" in command and command[command.index("--partvtk") + 1] == PARTVTK, f"{label}: PartVTK command")
        expect("--validation-dir" in command, f"{label}: validation dir")
        expect(request.get("future_typed_outputs", {}).get("typed_receipt_sha256") is None, f"{label}: typed receipt future hash")
        expect(request.get("future_typed_outputs", {}).get("trajectory_h5_sha256") is None, f"{label}: H5 future hash")

    xmf_requests = {path.stem.removesuffix("-normal-xmf-request"): load(path) for path in (HERE / "requests/xmf").glob("*-normal-xmf-request.json")}
    xmf_bindings = {path.stem.removesuffix("-xmf-binding"): load(path) for path in (HERE / "requests/xmf").glob("*-xmf-binding.json")}
    render = {path.stem.removesuffix("-native023-render-request"): load(path) for path in (HERE / "requests/render").glob("*.json")}
    expect(len(xmf_requests) == len(xmf_bindings) == len(render) == 14, "XMF/render count")
    expect(set(xmf_requests) == set(xmf_bindings) == set(render), "XMF/render identities")
    for physical_case_id, request in xmf_requests.items():
        label = f"xmf:{physical_case_id}"
        assert_disabled(request, label)
        assert_input_closure(request, label)
        assert_n3(request, label)
        case_id = request["case_id"]
        assert_scope_pair(request, owners[case_id], label)
        expect(request.get("binding", {}).get("path", "").endswith(f"requests/xmf/{physical_case_id}-xmf-binding.json"), f"{label}: binding path")
        expect(request.get("typed_request", {}).get("path", "").endswith(f"requests/typed/{case_id}.json"), f"{label}: typed path")
        binding = xmf_bindings[physical_case_id]
        expect(binding.get("owner_and_input_lineage", {}).get("owner", {}).get("path", "").endswith(f"owners/{case_id}.actual-converter-scope.owner.json"), f"{label}: actual owner lineage")
        assert_n3(binding, f"xmf-binding:{physical_case_id}")
        expect(binding.get("owner_and_input_lineage", {}).get("typed_request", {}).get("path", "").endswith(f"requests/typed/{case_id}.json"), f"{label}: binding typed lineage")
        renderer = render[physical_case_id]
        assert_disabled(renderer, f"render:{physical_case_id}")
        assert_input_closure(renderer, f"render:{physical_case_id}")
        assert_n3(renderer, f"render:{physical_case_id}")
        expect(RENDERER_PART in " ".join(renderer.get("command", [])), f"render:{physical_case_id}: renderer")
        expect(renderer.get("xmf_binding", {}).get("path", "").endswith(f"requests/xmf/{physical_case_id}-xmf-binding.json"), f"render:{physical_case_id}: xmf binding")

    for aggregate, expected in [("requests/typed-bindings.json", 14), ("requests/xmf-bindings.json", 14), ("requests/render-bindings.json", 14)]:
        doc = load(HERE / aggregate)
        expect(doc.get("all_requests_disabled") is True, f"{aggregate}: disabled aggregate")
        expect(len(doc.get("cases", [])) == expected, f"{aggregate}: aggregate count")

    print(json.dumps({"status": "pass", "package": str(HERE), "cases": 14, "typed": 14, "xmf": 14, "render": 14, "arrays_opened": False, "jobs_started": False}, indent=2))


if __name__ == "__main__":
    main()
