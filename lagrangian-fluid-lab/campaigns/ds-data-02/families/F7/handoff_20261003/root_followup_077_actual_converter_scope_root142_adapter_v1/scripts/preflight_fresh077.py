#!/usr/bin/env python3
"""Metadata-only preflight for F7 fresh077 and Root142 strict dispatch.

The checker reads JSON/XML/Python source and invokes only the real converter's
``_physical_condition_scope`` on corrected owner metadata. It never opens,
hashes, decodes, or copies BI4/CSV/H5/DAT/VTK/NumPy payloads and never launches
Root142, the converter, XMF, or the renderer.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
OLD = HERE.parent / "root_followup_076_actual_full601_typed_xmf_render_templates_v1"
I = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
L = I / "lagrangian-fluid-lab"
CONVERTER = L / "scripts/ds_data02_direct_convert.py"
RUNTIME_DIR = L / "scripts"
VENV = L / ".venv/bin/python"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RAW_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".dat", ".vtk", ".npy", ".npz", ".ibi4"}
CASES = [f"F7_OBSTACLE_QUINTIC_B08_A{n:03d}P5" for n in (30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,54,59,64)]


def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def converter_module():
    spec = importlib.util.spec_from_file_location("ds02_fresh077_converter", CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load converter source: {CONVERTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_disabled(doc: dict, label: str) -> None:
    for key, expected in {
        "source_only": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "disabled": True,
        "future_hashes_null": True,
        "independent_case_count_increment": 0,
    }.items():
        require(doc.get(key) is expected, f"{label}: {key}")
    require(doc.get("kind") == "cpu", f"{label}: kind")
    require(doc.get("cpu_task_kind") == "conversion", f"{label}: cpu task")
    require(doc.get("expected_frames") == 601 and doc.get("expected_particles") == 70179, f"{label}: frame/particle contract")
    require(doc.get("expected_counts") == {"dimension": 3, "fixed": 27495, "moving": 1984, "floating": 0, "fluid": 40700, "total": 70179}, f"{label}: counts")
    require(doc.get("producer_scope_schema") == "ds-data-02.physical-binding.v1", f"{label}: producer schema")
    require(doc.get("canonical_equals_source_plan_claim") is False, f"{label}: source/canonical collapse")
    for key, value in doc.get("future_outputs", {}).items():
        if key.endswith("_sha256"):
            require(value is None, f"{label}: future output hash populated {key}")


def assert_scope(owner: dict, label: str, converter) -> str:
    physical = owner.get("physical_binding")
    require(isinstance(physical, dict), f"{label}: physical_binding")
    required = {"family_id", "physical_case_id", "mechanism_id", "geometry_family_id", "control_family_id", "geometry", "initial_state", "controls", "gravity_m_s2", "density_kg_m3", "parameters", "event_window"}
    require(required <= set(physical), f"{label}: missing converter fields {sorted(required-set(physical))}")
    require("gravity_m_s2" not in physical["controls"], f"{label}: gravity remains under controls")
    scope = converter._physical_condition_scope(owner)
    scope_hash = converter.canonical_hash(scope)
    require(scope.get("schema") == "ds-data-02.physical-binding.v1", f"{label}: scope schema")
    require(scope_hash == owner.get("canonical_physical_binding_sha256") == owner.get("physical_condition_sha256"), f"{label}: scope hash closure")
    source_hash = owner.get("condition_hash_semantics", {}).get("declared_source_hash")
    require(isinstance(source_hash, str) and HEX64.fullmatch(source_hash), f"{label}: source plan hash")
    require(scope_hash != source_hash, f"{label}: scope/source-plan hash collapse")
    repair = owner.get("scope_repair", {})
    require(repair.get("corrected_scope_sha256") == scope_hash, f"{label}: repair scope hash")
    require(repair.get("arrays_read") is False and repair.get("payloads_read_or_hashed") is False, f"{label}: repair side effects")
    return scope_hash


def main() -> int:
    manifest = load(HERE / "manifest.json")
    require(manifest.get("schema") == "ds02.f7.fresh077.manifest.v1", "manifest schema")
    require(manifest.get("case_count") == 24 and manifest.get("case_ids") == CASES, "manifest cases")
    require(manifest.get("consumed_fresh076_immutable") is True, "fresh076 immutability")
    require(manifest.get("all_requests_disabled") is True and manifest.get("future_hashes_null") is True, "manifest enablement")
    require(manifest.get("arrays_read") is False and manifest.get("jobs_started") is False and manifest.get("shared_state_written") is False, "manifest side effects")

    package_files = [p for p in HERE.rglob("*") if p.is_file()]
    for path in package_files:
        require(path.suffix.lower() not in RAW_SUFFIXES, f"scientific payload shipped: {path}")
        if path.suffix == ".json":
            load(path)
        elif path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        elif path.suffix == ".xml":
            ET.parse(path)

    converter = converter_module()
    scope_meta = load(HERE / "metadata/converter-scope-preflight.json")
    require(scope_meta.get("all_passed") is True and scope_meta.get("case_count") == 24, "converter scope metadata")
    scope_rows = {row["case_id"]: row for row in scope_meta["cases"]}
    require(set(scope_rows) == set(CASES), "scope case identities")
    owners = {}
    for case in CASES:
        owner_path = HERE / "owners" / f"{case}.converter-owner.json"
        owner = load(owner_path)
        owners[case] = owner
        actual_scope_hash = assert_scope(owner, f"owner:{case}", converter)
        row = scope_rows[case]
        require(row["corrected_owner_sha256"] == sha256(owner_path), f"owner:{case}: owner hash")
        require(row["converter_scope_sha256"] == actual_scope_hash, f"owner:{case}: preflight hash")
        require(row["original_owner_sha256"] != row["corrected_owner_sha256"], f"owner:{case}: repair did not change owner")
        require(row["original_declared_canonical_binding_sha256"] != actual_scope_hash, f"owner:{case}: old/corrected collapse")

    root_audit = load(HERE / "metadata/root142-contract-audit.json")
    audit = root_audit["fresh076_static_request_audit"]
    require(audit["total"] == 72 and audit["runtime_validate_passed"] == 72 and audit["strict_digest_closure_passed"] == 72 and not audit["failures"], "Root142 fresh076 audit")
    for path, digest in root_audit["source_hashes"].items():
        require(Path(path).is_file(), f"Root142 source missing: {path}")
        require(sha256(Path(path)) == digest, f"Root142 source hash changed: {path}")

    sys.path.insert(0, str(RUNTIME_DIR))
    import ds_data02_runtime_v2 as runtime
    import ds_data02_strict_dispatch_v1 as strict
    requests = sorted((HERE / "requests/typed").glob("*.json"))
    require(len(requests) == 24, "typed request count")
    runtime_pass = strict_pass = 0
    failures = []
    for request_path in requests:
        request = load(request_path)
        case = request["case_id"]
        try:
            assert_disabled(request, f"request:{case}")
            require(case in owners, f"request:{case}: unknown case")
            owner_path = Path(request["owner_metadata"]["path"])
            require(owner_path == (HERE / "owners" / f"{case}.converter-owner.json").resolve(), f"request:{case}: owner path")
            require(request["canonical_physical_binding_sha256"] == owners[case]["canonical_physical_binding_sha256"], f"request:{case}: owner scope")
            files = [str(Path(p).resolve()) for p in request["input_files"]]
            hashes = {str(Path(p).resolve()): v for p, v in request["input_sha256"].items()}
            require(len(files) == len(set(files)), f"request:{case}: duplicate input")
            require(set(files) == set(hashes), f"request:{case}: input/hash sets differ")
            for path in files:
                require(Path(path).is_file(), f"request:{case}: input missing {path}")
                require(Path(path).suffix.lower() not in RAW_SUFFIXES, f"request:{case}: payload input {path}")
            actual = runtime.validate_request(request)
            runtime_pass += 1
            strict.check_registered_hashes(request, actual)
            strict_pass += 1
        except Exception as exc:
            failures.append({"case_id": case, "path": str(request_path), "error": f"{type(exc).__name__}: {exc}"})
    require(not failures, json.dumps(failures, indent=2))

    report = {
        "schema": "ds02.f7.fresh077.source-validation-report.v1",
        "scope_id": manifest["scope_id"],
        "case_count": 24,
        "converter_scope_cases_passed": 24,
        "root142_runtime_validation_passed": runtime_pass,
        "root142_strict_digest_validation_passed": strict_pass,
        "typed_requests_disabled": True,
        "future_hashes_null": True,
        "input_hash_sets_exact": True,
        "payload_inputs": 0,
        "arrays_read": False,
        "payloads_read_or_hashed": False,
        "jobs_started": False,
        "shared_state_written": False,
        "claim_boundary": "Metadata-only converter scope repair and Root142 request preflight; no downstream product or scientific acceptance claim.",
    }
    (HERE / "metadata/source-validation-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
