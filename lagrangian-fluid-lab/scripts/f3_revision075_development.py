"""Revision-bound F3 development execution entry point.

This module is the successor to the historical ``f3_nopen_development``
entry point.  It deliberately requires a *passed* revision075 qualification
gate before it can register or run a development case.  The old NoPen gate is
never consulted or rewritten.  CFD execution is delegated to the shared
``l1r_branch_runner`` so its attempt directory, GPU UUID and resource guards
remain the only launch path.

``plan`` is read-only and is safe to use while qualification is in progress.
``prepare`` and ``run`` remain fail-closed until a later revision gate grants
development permission; this file does not create that gate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # pragma: no cover - direct CLI invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_development_candidates as candidates
from scripts import f3_nopen_qualification as qualification
from scripts import f3_revision075_launch_gate as revision_launch_gate
from scripts import l1r_q2_mdbc_bridge as q2
from scripts.l1r_continuation_evidence import LAB, OUT, check_budget
from scripts.l1r_input_preflight import check_input


REVISION_RECIPE = "F3_CELL3_NS_visco1_native_nopen_revision075"
REVISION_GATE = "F3-075-REVISION-GATE.json"
DEVELOPMENT_MANIFEST = "F3-DEVELOPMENT-CANDIDATES.json"
REGISTRY = "F3-075-DEVELOPMENT-REGISTRY.json"
GATE_SCHEMA = "f3.revision075.qualification_gate.v1"
REGISTRY_SCHEMA = "f3.revision075.development_registry.v1"
GPU_IDS = (4, 5, 6, 7)
PROTECTED_GPU_IDS = (0, 1, 2, 3)


def _read(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"missing required record: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"record must be an object: {path}")
    return value


def _write(name: str, value: dict) -> None:
    q2.atomic_json(OUT / name, value)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _path(relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("development evidence paths must be LAB-relative")
    path = (LAB / relative).resolve()
    path.relative_to(LAB.resolve())
    return path


def _fingerprint(path: Path) -> dict:
    return {"path": _relative(path), "sha256": q2.sha256(path)}


def verify_revision_gate() -> dict:
    """Validate the immutable post-qualification handoff.

    The gate is intentionally a separate artifact from the historical
    ``F3-NOPEN-DOMAIN-GATE.json``.  Its evidence bindings must cover every
    revision cell and the selected production source, and it must explicitly
    opt in to development.  A missing or merely prepared gate therefore
    cannot spend development budget.
    """
    # Keep this successor entry point bound to the same immutable preparation
    # manifest/summary that guards revision075 qualification launches.  The
    # owner authorization is intentionally not reused here: development must
    # wait for the later passed qualification gate below.
    revision_launch_gate.verify_preparation()
    gate_path = OUT / REVISION_GATE
    gate = _read(gate_path)
    if (gate.get("schema") != GATE_SCHEMA
            or gate.get("status") != "passed"
            or gate.get("recipe_id") != REVISION_RECIPE
            or gate.get("development_launch_allowed") is not True):
        raise ValueError("passed revision075 qualification gate with development opt-in is required")
    if gate.get("production_resolution_m") != 0.0075:
        raise ValueError("revision gate must qualify production resolution .0075 m")
    if gate.get("time_window_s") != [0.0, 8.35] or gate.get("scoring_interval_s") != 0.01:
        raise ValueError("revision gate must qualify the full 0-8.35 s, .01 s scoring window")
    if gate.get("coordinate_frame") != "fixed tank computational coordinates with prescribed acceleration; no inertial-world trajectory claim":
        raise ValueError("revision gate coordinate frame is not the registered F3 frame")
    if gate.get("control_domain") != [0.9, 1.1]:
        raise ValueError("revision gate must qualify the registered [0.9, 1.1] control domain")
    source_id = gate.get("production_source_case_id")
    if not isinstance(source_id, str) or not source_id.startswith("F3_"):
        raise ValueError("revision gate has no revision-bound production source")
    evidence = gate.get("evidence_sha256")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("revision gate has no bound evidence")
    for relative, digest in evidence.items():
        path = _path(relative)
        if q2.sha256(path) != digest:
            raise ValueError("revision gate evidence changed: " + relative)
    required_cells = gate.get("required_cell_ids")
    if not isinstance(required_cells, list) or len(required_cells) != 11 or len(set(required_cells)) != 11:
        raise ValueError("revision gate must bind all 11 revision cells")
    for case_id in required_cells:
        relative = _relative(OUT / (case_id + "-AUDIT.json"))
        if relative not in evidence:
            raise ValueError("revision gate omits cell audit: " + case_id)
    source_record = OUT / (source_id + "-PREPARED.json")
    source_solver = OUT / (source_id + "-SOLVER.json")
    source_audit = OUT / (source_id + "-AUDIT.json")
    for path in (source_record, source_solver, source_audit):
        if _relative(path) not in evidence:
            raise ValueError("revision gate omits production source evidence: " + _relative(path))
    return gate


def verify_gpu_contract() -> None:
    """Keep revision development on the guarded physical GPU pool."""
    if tuple(getattr(q2, "GPU_IDS", ())) != GPU_IDS:
        raise RuntimeError("shared GPU selector no longer restricts revision work to physical GPUs 4-7")
    if tuple(getattr(q2, "PROTECTED_GPU_IDS", ())) != PROTECTED_GPU_IDS:
        raise RuntimeError("shared GPU selector protection policy changed")
    if set(GPU_IDS) & set(PROTECTED_GPU_IDS):
        raise RuntimeError("revision GPU allowlist overlaps protected GPUs")


def _manifest() -> dict:
    manifest = _read(OUT / DEVELOPMENT_MANIFEST)
    if (manifest.get("status") != "inputs_registered_no_fluid_data"
            or manifest.get("launch_allowed") is not False
            or manifest.get("initial_physical_definition", {}).get("coordinate_frame") != "fixed computational tank"):
        raise ValueError("registered independent development input manifest is required")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != 32:
        raise ValueError("development manifest must contain exactly 32 cases")
    candidates.validate(rows)
    if {row.get("index") for row in rows} != set(range(32)):
        raise ValueError("development physical-case indices are incomplete or duplicated")
    if q2.sha256(LAB / "scripts/f3_development_candidates.py") != manifest.get("program_sha256"):
        raise ValueError("candidate generation program changed after input registration")
    for row in rows:
        if (not re.fullmatch(r"F3_DEV_[0-9]{2}_a[01]p[0-9]{6}", row.get("case_id", ""))
                or not isinstance(row.get("pilot"), bool)):
            raise ValueError("invalid development case identity or pilot flag")
    return manifest


def candidate(case_id: str) -> dict:
    rows = [row for row in _manifest()["cases"] if row["case_id"] == case_id]
    if len(rows) != 1:
        raise ValueError("case is not an independent registered development candidate")
    return copy.deepcopy(rows[0])


def _source(gate: dict) -> dict:
    source_id = gate["production_source_case_id"]
    record = _read(OUT / (source_id + "-PREPARED.json"))
    if (record.get("id") != source_id
            or record.get("recipe_id") not in {REVISION_RECIPE, qualification.RECIPE}
            or record.get("resource_category") not in {None, "qualification"}
            or record.get("dp_m") != 0.0075 or record.get("drive_amplitude") != 1.0
            or record.get("time_max_s") != 8.35 or record.get("time_out_s") != 0.01
            or record.get("cfl_number") != 0.05 or record.get("coef_dt_min") != 0.05):
        raise ValueError("revision production source does not match the qualified recipe")
    solver = _read(OUT / (source_id + "-SOLVER.json"))
    audit = _read(OUT / (source_id + "-AUDIT.json"))
    if (solver.get("case_id") != source_id or solver.get("status") != "completed"
            or solver.get("resource_category") != "qualification"
            or solver.get("source_record", {}).get("id") != source_id):
        raise ValueError("revision production source solver is not a completed qualified run")
    qualification._hard_audit(record, audit)
    prefix = _path(record["generated_prefix"])
    qualification._verify_assets(prefix, record["input_assets"])
    return {"record": record, "solver": solver, "audit": audit, "prefix": prefix}


def _control(row: dict, manifest: dict, nominal: np.ndarray) -> Path:
    path = _path(row["control_path"])
    if q2.sha256(path) != row["control_file_sha256"]:
        raise ValueError("candidate control file changed after registration")
    actual = np.loadtxt(path, delimiter=";", comments="#")
    expected = nominal.copy()
    gravity = np.array([0.0, 0.0, -9.81])
    amplitude = row["drive_amplitude"]
    expected[:, 1:4] = gravity + amplitude * (nominal[:, 1:4] - gravity)
    expected[:, 4:7] *= amplitude
    effective = candidates.semantic_hash(actual)
    lineage = hashlib.sha256(json.dumps(
        {"initial": manifest["initial_physical_definition"], "effective_control_sha256": effective},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (not np.array_equal(actual, expected) or effective != row["effective_control_sha256"]
            or lineage != row["physical_lineage_sha256"]):
        raise ValueError("candidate precise control or physical lineage is inconsistent")
    return path


def _context(*, register: bool) -> dict:
    gate = verify_revision_gate()
    verify_gpu_contract()
    manifest = _manifest()
    source = _source(gate)
    nominal_path = source["prefix"].parent / "CaseSloshingAccData.csv"
    vendor_nominal_path = (LAB /
        "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv")
    # Preparation rewrites the amplitude-one CSV with a canonical formatter,
    # so its bytes can differ while its parsed forcing must remain identical.
    # Bind the candidate manifest to the immutable vendor bytes and compare
    # the actual source numerically before accepting that formatting change.
    if q2.sha256(vendor_nominal_path) != manifest.get("source_drive_sha256"):
        raise ValueError("development candidate manifest source forcing changed")
    nominal = np.loadtxt(nominal_path, delimiter=";", comments="#")
    vendor_nominal = np.loadtxt(vendor_nominal_path, delimiter=";", comments="#")
    if nominal.shape != vendor_nominal.shape or not np.array_equal(nominal, vendor_nominal):
        raise ValueError("revision production source forcing differs from the registered nominal recipe")
    registry_path = OUT / REGISTRY
    evidence = [_fingerprint(OUT / DEVELOPMENT_MANIFEST), _fingerprint(OUT / REVISION_GATE)]
    evidence += [_fingerprint(OUT / (source["record"]["id"] + suffix))
                 for suffix in ("-PREPARED.json", "-AUDIT.json", "-SOLVER.json")]
    if registry_path.exists():
        registry = _read(registry_path)
        if (registry.get("schema") != REGISTRY_SCHEMA
                or registry.get("recipe_id") != REVISION_RECIPE
                or registry.get("resource_category") != "development"
                or registry.get("cases") != manifest["cases"]
                or registry.get("evidence") != evidence
                or registry.get("production_source_case_id") != source["record"]["id"]
                or registry.get("program_sha256") != q2.sha256(Path(__file__))):
            raise ValueError("immutable revision development registration or evidence is stale")
    else:
        if not register:
            # A dry-run must remain read-only.  Construct the same shape that
            # registration would persist, but do not write it or charge a
            # development attempt.
            registry = {
                "schema": REGISTRY_SCHEMA, "recipe_id": REVISION_RECIPE,
                "resource_category": "development", "cases": manifest["cases"],
                "production_source_case_id": source["record"]["id"],
                "evidence": evidence, "program_sha256": q2.sha256(Path(__file__)),
            }
            return {"gate": gate, "manifest": manifest, "registry": registry,
                    "source": source, "nominal": nominal}
        for row in manifest["cases"]:
            _control(row, manifest, nominal)
        registry = {
            "schema": REGISTRY_SCHEMA, "recorded_at_utc": q2.utc_now(),
            "scope": "independent_development_after_f3_revision075_qualification",
            "recipe_id": REVISION_RECIPE, "resource_category": "development",
            "production_source_case_id": source["record"]["id"],
            "production_resolution_m": 0.0075, "time_window_s": [0.0, 8.35],
            "output_interval_s": 0.01, "evidence": evidence,
            "cases": manifest["cases"],
            "pilot_case_ids": [row["case_id"] for row in manifest["cases"] if row["pilot"]],
            "max_attempts_per_case": 1, "solver_timeout_seconds": 3600,
            "original_inputs_are_solver_results": False,
            "auto_run_remaining_cases": False, "material_layers_qualified": [],
            "training_completed": False, "formal_release": False,
            "program_sha256": q2.sha256(Path(__file__)),
        }
        _write(REGISTRY, registry)
    return {"gate": gate, "manifest": manifest, "registry": registry,
            "source": source, "nominal": nominal}


def _fields(row: dict, context: dict, target: Path) -> dict:
    source = context["source"]["record"]
    source_prefix = context["source"]["prefix"]
    return dict(
        id=row["case_id"], case_id=row["case_id"], family="F3",
        background_id="plain", phase="F3_revision075_development",
        resource_category="development", recipe_id=REVISION_RECIPE,
        dp_m=0.0075, resolution="0.0075", generated_prefix=_relative(target / source_prefix.name),
        candidate_definition=_relative(target / (source_prefix.name + "_Def.xml")),
        drive_amplitude=row["drive_amplitude"], drive_sha256=row["control_file_sha256"],
        effective_control_sha256=row["effective_control_sha256"],
        physical_lineage_sha256=row["physical_lineage_sha256"],
        registered_control_path=row["control_path"], candidate_index=row["index"],
        split=row["split"], evaluation_role=row["evaluation_role"], pilot=row["pilot"],
        solver_mode="-mdbc_noslip:1", expected_slip_mode="No-slip",
        expected_no_penetration=True, max_attempts=1, solver_timeout_seconds=3600,
        cfl_number=0.05, coef_dt_min=0.05, time_max_s=8.35, time_out_s=0.01,
        visco_bound_factor=1, gencase={**{key: source["gencase"][key]
        for key in ("total_particles", "fluid_particles", "boundary_particles")},
        "reuse_source": str(Path(source["generated_prefix"]).parent)},
        native_velocity_displacement_correction=True, posthoc_particle_projection=False,
        control_definition="F3_CELL3_gravity_preserving_amplitude_v1",
        development_registry_path=_relative(OUT / REGISTRY),
        development_registry_sha256=q2.sha256(OUT / REGISTRY),
        source_revision_gate_sha256=q2.sha256(OUT / REVISION_GATE),
        source_candidate_manifest_sha256=q2.sha256(OUT / DEVELOPMENT_MANIFEST),
        reference_recipe_and_domain_verified=True,
        development_case_hard_audit_passed=False, material_layers_qualified=[],
        qualified=False, formal_release=False,
        comparison_scope="Independent physical forcing case inside the qualified F3 revision075 domain; public development only",
        input_repair="Reuse qualified revision075 native initial-state/solver inputs with exact registered independent CSV",
    )


def _prepare(case_id: str, context: dict) -> dict:
    row = next(row for row in context["manifest"]["cases"] if row["case_id"] == case_id)
    control_path = _control(row, context["manifest"], context["nominal"])
    saved = OUT / (case_id + "-PREPARED.json")
    target = LAB / "campaigns/l1-resume/artifacts/f3-revision075-development" / case_id
    source_prefix = context["source"]["prefix"]
    expected = _fields(row, context, target)
    if saved.exists():
        record = _read(saved)
        if any(record.get(key) != value for key, value in expected.items()):
            raise ValueError("revision development prepared record differs from registration")
        qualification._verify_assets(_path(record["generated_prefix"]), record["input_assets"])
        check_input(record)
        return record
    attempts = LAB / "campaigns/l1-resume/runs/branches" / case_id / "attempts"
    if target.exists() or attempts.exists():
        raise ValueError("incomplete or attempted revision development preparation exists; do not overwrite")
    target.mkdir(parents=True)
    for filename in context["source"]["record"]["input_assets"]:
        shutil.copy2(control_path if filename == "CaseSloshingAccData.csv" else source_prefix.parent / filename,
                     target / filename)
    record = copy.deepcopy(context["source"]["record"])
    record.update(expected)
    record["input_assets"] = {path.name: q2.sha256(path) for path in target.iterdir() if path.is_file()}
    record["generated_xml_sha256"] = q2.sha256(target / (source_prefix.name + ".xml"))
    qualification._verify_assets(target / source_prefix.name, record["input_assets"])
    _control(row, context["manifest"], context["nominal"])
    check_input(record)
    _write(saved.name, record)
    return record


def plan(case_id: str) -> dict:
    """Read-only gate/manifest check; never charges or launches anything."""
    row = candidate(case_id)
    context = _context(register=False)
    return {"status": "ready_after_gate", "case_id": case_id, "pilot": row["pilot"],
            "resource_category": "development", "recipe_id": REVISION_RECIPE,
            "production_source_case_id": context["source"]["record"]["id"],
            "gpu_indices": list(GPU_IDS), "protected_gpu_indices": list(PROTECTED_GPU_IDS),
            "solver_attempts": 0, "launch": False}


def run(case_id: str, *, dry_run: bool = False) -> dict:
    row = candidate(case_id)
    if dry_run:
        context = _context(register=False)
        return {"status": "dry_run", "case_id": case_id, "resource_category": "development",
                "recipe_id": REVISION_RECIPE, "gpu_indices": list(GPU_IDS),
                "protected_gpu_indices": list(PROTECTED_GPU_IDS), "solver_attempts": 0,
                "launch": False}
    # Check the development pool before creating the immutable registration.
    # The shared runner performs the same budget check immediately before the
    # native launch and owns the final attempt accounting.
    _context(register=False)
    check_budget(category="development")
    context = _context(register=True)
    record = _prepare(case_id, context)
    from scripts.l1r_branch_runner import run as shared_run
    result = shared_run(record)
    failure = None
    try:
        qualification._hard_audit(record, result)
    except (ValueError, KeyError, FileNotFoundError) as error:
        failure = str(error)
    return {"case_id": case_id, "resource_category": "development", "pilot": row["pilot"],
            "status": "completed" if failure is None else "failed",
            "audit_status": result.get("audit_status"), "solver_status": result.get("status"),
            "frames": result.get("frames"), "issues": result.get("issues"),
            "unknowns": result.get("unknowns"), "hard_audit_passed": failure is None,
            "failure_reason": failure, "reference_recipe_and_domain_verified": True,
            "material_layers_qualified": [], "formal_release": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("case_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = plan(args.case_id) if args.action == "plan" else run(args.case_id, dry_run=args.dry_run)
    except (ValueError, PermissionError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"ready_after_gate", "dry_run", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
