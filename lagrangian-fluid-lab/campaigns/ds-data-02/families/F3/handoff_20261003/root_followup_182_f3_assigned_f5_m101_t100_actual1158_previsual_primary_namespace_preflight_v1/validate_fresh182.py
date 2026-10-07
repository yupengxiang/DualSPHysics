#!/usr/bin/env python3
"""Fail-closed metadata validator for fresh182.

It reads only JSON/XML/XMF/Python/Markdown metadata.  It never opens or hashes
H5, BI4, IBI4, CSV, DAT, VTK, or any other scientific payload.  A live render
receipt is allowed to remain ``running``; that state is explicitly pending and
cannot satisfy a terminal-render or visual-review gate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
ALLOWED = {".json", ".xml", ".xmf", ".py", ".md"}
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34"
PHYSICAL = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M101_T100"
CANONICAL = "1a04363bffefde127740d3da87de48ba66db566b7ae0cdf44d6c6f4b73137cf3"
LEGACY = "80039c17cc7a088b7bc0fdc5c7a74d9051aa72763652261e2823635fcd5ad93d"
FRAMES = 801
PARTICLES = 194427


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read refused: {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {label}: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"object expected for {label}: {path}")
    return value


def metadata_sha(path: Path, label: str) -> str:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN:
        fail(f"scientific payload access attempted: {label}: {path}")
    if suffix not in ALLOWED:
        fail(f"unsupported metadata file: {label}: {path}")
    if not path.is_file():
        fail(f"missing metadata: {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ref(ref: Any, label: str, *, exact_sha: bool = True) -> Path:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        fail(f"malformed metadata reference: {label}")
    path = Path(ref["path"])
    if not path.is_absolute():
        fail(f"non-absolute metadata reference: {label}: {path}")
    actual = metadata_sha(path, label)
    if exact_sha and ref.get("sha256") != actual:
        fail(f"metadata SHA mismatch: {label}: {ref.get('sha256')} != {actual}")
    return path


def check_stage(ref: Any, label: str) -> dict[str, Any]:
    path = check_ref(ref, label)
    obj = load_json(path, label)
    if obj.get("status") != "completed" or obj.get("returncode") != 0:
        fail(f"{label} is not completed/0")
    req = obj.get("request") if isinstance(obj.get("request"), dict) else {}
    if req.get("case_id", obj.get("case_id")) not in (None, CASE):
        fail(f"{label} case mismatch")
    if req.get("physical_case_id", obj.get("physical_case_id")) not in (None, PHYSICAL):
        fail(f"{label} physical case mismatch")
    return obj


def check_field_mask(obj: dict[str, Any], mask: dict[str, Any], label: str) -> None:
    for key, expected in mask.items():
        if key not in obj:
            actual = {"presence": "absent"}
        elif obj[key] is None:
            actual = {"presence": "null"}
        else:
            actual = {"presence": "present"}
        if actual.get("presence") != expected.get("presence"):
            fail(f"{label}.{key} presence changed: {actual} != {expected}")


def check_manifest_files() -> None:
    manifest = load_json(HERE / "package-manifest.json", "package manifest")
    if manifest.get("package_manifest_excluded_from_own_hash") is not True:
        fail("package manifest self-exclusion missing")
    listed = {entry.get("path") for entry in manifest.get("files", [])}
    expected = {"README.md", "build_fresh182.py", "validate_fresh182.py", "metadata/M101_T100-previsual-primary-namespace-preflight.json"}
    if listed != expected:
        fail(f"package manifest file set mismatch: {listed}")
    for entry in manifest["files"]:
        rel = entry.get("path")
        if not isinstance(rel, str) or Path(rel).is_absolute() or Path(rel).suffix.lower() in FORBIDDEN:
            fail(f"invalid package file path: {rel}")
        path = HERE / rel
        if not path.is_file() or path.stat().st_size != entry.get("bytes"):
            fail(f"package file size/path mismatch: {rel}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            fail(f"package file SHA mismatch: {rel}")


def validate() -> dict[str, Any]:
    check_manifest_files()
    proof = load_json(HERE / "metadata/M101_T100-previsual-primary-namespace-preflight.json", "previsual proof")
    if proof.get("schema") != "ds02.f3.assigned.f5.m101_t100.previsual-primary-namespace-preflight.v1":
        fail("wrong proof schema")
    if proof.get("fresh_id") != "fresh182":
        fail("wrong fresh id")
    scope = proof.get("package_scope", {})
    if scope.get("assigned_worktree_family") != "F3" or scope.get("actual_case_family") != "F5":
        fail("assigned/actual family mismatch")
    if scope.get("source_only") is not True or scope.get("science_payload_opened_or_hashed_by_source_agent") is not False:
        fail("source-only/payload boundary failed")
    if scope.get("new_case_credit") != 0 or scope.get("q_n_granted") is not False or scope.get("q_e_granted") is not False:
        fail("credit or qualification boundary failed")
    ident = proof.get("identity", {})
    if ident.get("case_id") != CASE or ident.get("physical_case_id") != PHYSICAL:
        fail("identity mismatch")
    if ident.get("canonical_native_physical_condition_sha256") != CANONICAL or ident.get("actual_typed_legacy_scope_sha256") != LEGACY:
        fail("scope identity mismatch")
    counts = proof.get("counts", {})
    for key, value in {"frames": FRAMES, "total": PARTICLES, "solver_dimension": 3, "fixed": 158559, "fluid": 31658, "moving": 4210, "floating": 0}.items():
        if counts.get(key) != value:
            fail(f"count mismatch {key}: {counts.get(key)}")
    lifecycle = proof.get("producer_lifecycle", {})
    for label in ("gencase", "initial_qa", "native", "typed", "xmf", "bed"):
        check_stage(lifecycle.get(label), f"{label} producer")
    refs = proof.get("metadata_refs", [])
    if not refs:
        fail("metadata refs missing")
    for ref in refs:
        check_ref(ref, f"metadata ref {ref.get('role')}")

    roles = proof.get("namespace_roles", {})
    if roles.get("native", {}).get("condition_scope") != CANONICAL:
        fail("native canonical role missing")
    if roles.get("typed", {}).get("legacy_scope") != LEGACY:
        fail("typed legacy role missing")
    if roles.get("xmf", {}).get("canonical_physical_scope") != CANONICAL:
        fail("XMF canonical physical role missing")
    if roles.get("xmf", {}).get("source_plan_file_scope") is None:
        fail("XMF source-plan file role missing")
    if roles.get("bed", {}).get("source_definition_file_scope") is None:
        fail("bed SourceDef role missing")
    if roles.get("trajectory_h5", {}).get("source_agent_opened_or_hashed") is not False:
        fail("H5 source-agent boundary failed")
    # Re-open only metadata files to verify the absent/null masks and actual report contracts.
    for role, ref_key in (("native", "native"), ("xmf", "xmf"), ("typed", "typed"), ("bed", "bed")):
        mask = roles[role].get("raw_field_mask")
        if not isinstance(mask, dict):
            fail(f"{role} raw field mask missing")
        if role == "native":
            target = load_json(Path(str(proof["metadata_refs"][0]["path"])), "chain")  # replaced below
            # The native request is the only native role source; find it by role.
            native_ref = next(r for r in refs if r.get("role") == "native request")
            target = load_json(Path(native_ref["path"]), "native request")
        elif role == "xmf":
            target = load_json(Path(next(r for r in refs if r.get("role") == "XMF manifest")["path"]), "XMF manifest")
        elif role == "typed":
            target = load_json(Path(next(r for r in refs if r.get("role") == "typed conversion report")["path"]), "typed report")
        else:
            target = load_json(Path(next(r for r in refs if r.get("role") == "bed report")["path"]), "bed report")
        check_field_mask(target, mask, f"{role} raw field mask")

    times = proof.get("time_and_fields", {})
    if times.get("xmf_frame_count") != FRAMES or not isinstance(times.get("xmf_time_sequence_sha256"), str):
        fail("XMF time contract missing")
    if times.get("typed_time_evidence", {}).get("strictly_increasing") is not True:
        fail("typed time evidence is not strictly increasing")
    if times.get("bed_time_evidence", {}).get("frame_count") != FRAMES or times.get("bed_time_evidence", {}).get("match") is not True:
        fail("bed time evidence incomplete")
    initial = proof.get("initial_qa", {})
    if initial.get("basic_placement_pass") is not True or initial.get("precision_accepted") is not False or initial.get("q_n_granted") is not False:
        fail("initial QA role/negative evidence mismatch")
    runtime = proof.get("runtime_binding", {})
    if runtime.get("current_attempt_id") != runtime.get("reservation_id"):
        fail("attempt/reservation mismatch")
    if runtime.get("future_render_hashes") != {"receipt": None, "report": None}:
        fail("future render hashes must remain null")

    render = proof.get("render_previsual", {})
    receipt = render.get("receipt", {})
    render_path = Path(receipt.get("path", ""))
    current = load_json(render_path, "volatile current render receipt")
    req = current.get("request") if isinstance(current.get("request"), dict) else {}
    if req.get("case_id", current.get("case_id")) != CASE or req.get("physical_case_id", current.get("physical_case_id")) != PHYSICAL:
        fail("volatile render identity mismatch")
    if current.get("status") not in {"running", "completed", "failed", "cancelled"}:
        fail(f"unknown volatile render status: {current.get('status')}")
    if current.get("status") == "running" and current.get("returncode") is not None:
        fail("running render has a returncode")
    if current.get("status") == "completed" and current.get("returncode") != 0:
        fail("completed render is not returncode 0")
    if render.get("visual_status") != "pending actual complete render and personal delegated review" or render.get("case_credit") != 0:
        fail("previsual status/credit boundary failed")
    return {"status": "PASS", "fresh_id": "fresh182", "render_status_at_validation": current.get("status"), "visual_status": render.get("visual_status")}


def main() -> int:
    try:
        print(json.dumps(validate(), indent=2, sort_keys=True))
    except ValidationError as exc:
        print(f"fresh182 validation FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
