"""Prepare/run one independently registered F3 development case after domain gates.

Candidate CSV bytes and precise amplitudes are consumed from the frozen manifest.
Qualification trajectories cannot be relabelled as development.  Nonpilot runs
require all eight original pilot identities to have real passing hard audits.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np

from scripts import f3_development_candidates as candidates
from scripts import f3_nopen_qualification as qualification
from scripts.l1r_continuation_evidence import LAB, OUT, check_budget
from scripts.l1r_input_preflight import check_input
from scripts import l1r_q2_mdbc_bridge as q2

MANIFEST = "F3-DEVELOPMENT-CANDIDATES.json"
REGISTRY = "F3-NOPEN-DEVELOPMENT-REGISTRY.json"
DOMAIN_GATE = "F3-NOPEN-DOMAIN-GATE.json"
RECIPE = qualification.RECIPE


def _read(path):
    return json.loads(path.read_text())


def _write(name, value):
    q2.atomic_json(OUT / name, value)


def _relative(path):
    return str(path.resolve().relative_to(LAB.resolve()))


def _path(relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("development evidence paths must be LAB-relative")
    path = (LAB / relative).resolve()
    path.relative_to(LAB.resolve())
    return path


def _fingerprint(path):
    return dict(path=_relative(path), sha256=q2.sha256(path))


def verify_domain_gate():
    """Read-only validation; production fields must come from actual scoring."""
    gate = _read(OUT / DOMAIN_GATE)
    names = {qualification.case_id_for(i) for i in ("NP13", "NP14")}
    if (gate.get("schema") != "f3.nopen.domain_gate.v1" or gate.get("stage") != "domain"
            or gate.get("status") != "passed" or gate.get("recipe_id") != RECIPE
            or len(gate.get("case_ids", [])) != 2 or set(gate.get("case_ids", [])) != names):
        raise ValueError("complete NoPen domain gate is required before development")
    if (gate.get("production_resolution_m") != .01
            or gate.get("time_window_s") != [0, 8.35]
            or gate.get("scoring_interval_s") != .01):
        raise ValueError("domain scoring must explicitly qualify production dp=.01, full 0-8.35 s and .01 s scoring")
    bindings = gate.get("evidence_sha256")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("domain gate has no bound scoring/source evidence")
    for relative, digest in bindings.items():
        if q2.sha256(_path(relative)) != digest:
            raise ValueError("domain evidence changed: " + relative)
    for filename in ("F3-NOPEN-NOMINAL-GATE.json", "F3-NOPEN-ENDPOINT-GATE.json"):
        if _relative(OUT / filename) not in bindings:
            raise ValueError("domain gate omits its nominal or endpoint prerequisite")
    qualification.verify_stage_gate("endpoints")
    for plan_id in ("NP13", "NP14"):
        name = qualification.case_id_for(plan_id)
        if _relative(OUT / (name + "-AUDIT.json")) not in bindings:
            raise ValueError("domain gate omits an independent internal hard audit")
        qualification.verified_source(plan_id)
    scoring = gate.get("scoring_evidence_paths")
    if not isinstance(scoring, list) or not scoring:
        raise ValueError("domain gate must name substantive scoring reports")
    covered = set()
    for relative in scoring:
        if relative not in bindings or relative.endswith(("-AUDIT.json", "-GATE.json")):
            raise ValueError("domain scoring evidence is not a bound scoring report")
        score = _read(_path(relative))
        covered.update(score.get("case_ids", score.get("cases", [])))
        if score.get("case_id"):
            covered.add(score["case_id"])
    if not names.issubset(covered):
        raise ValueError("domain scoring does not cover both independent internal cases")
    return gate


def _manifest():
    manifest = _read(OUT / MANIFEST)
    if (manifest.get("status") != "inputs_registered_no_fluid_data"
            or manifest.get("launch_allowed") is not False
            or manifest.get("initial_physical_definition") != candidates.INITIAL):
        raise ValueError("original independent development input manifest is required")
    rows = manifest["cases"]
    candidates.validate(rows)
    if {row.get("index") for row in rows} != set(range(32)):
        raise ValueError("development physical-case indices are incomplete or duplicated")
    for row in rows:
        if (not re.fullmatch(r"F3_DEV_[0-9]{2}_a[01]p[0-9]{6}", row["case_id"])
                or not isinstance(row.get("pilot"), bool)):
            raise ValueError("invalid development identity or pilot flag")
    if q2.sha256(LAB / "scripts/f3_development_candidates.py") != manifest.get("program_sha256"):
        raise ValueError("candidate generation program changed after input registration")
    return manifest


def candidate(case_id):
    """Read the exact registered physical case; never infer amplitude from its ID."""
    rows = [r for r in _manifest()["cases"] if r["case_id"] == case_id]
    if len(rows) != 1:
        raise ValueError("case is not an independent registered development candidate")
    return copy.deepcopy(rows[0])


def _control(row, manifest, nominal):
    path = _path(row["control_path"])
    if q2.sha256(path) != row["control_file_sha256"]:
        raise ValueError("candidate control file changed after registration")
    actual = np.loadtxt(path, delimiter=";", comments="#")
    expected = nominal.copy()
    gravity = np.array([0., 0., -9.81])
    amplitude = row["drive_amplitude"]  # Preserve the original binary float value.
    expected[:, 1:4] = gravity + amplitude * (nominal[:, 1:4] - gravity)
    expected[:, 4:7] *= amplitude
    effective = candidates.semantic_hash(actual)
    lineage = hashlib.sha256(json.dumps({"initial": manifest["initial_physical_definition"],
                                        "effective_control_sha256": effective},
                                       sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (not np.array_equal(actual, expected) or effective != row["effective_control_sha256"]
            or lineage != row["physical_lineage_sha256"]):
        raise ValueError("candidate precise control or physical lineage is inconsistent")
    return path


def _context(*, register):
    gate = verify_domain_gate()
    manifest = _manifest()
    base, _, _ = qualification.verified_source("NP01")
    prefix = _path(base["generated_prefix"])
    nominal_path = prefix.parent / "CaseSloshingAccData.csv"
    if q2.sha256(nominal_path) != manifest["source_drive_sha256"]:
        raise ValueError("development source forcing differs from the qualified nominal recipe")
    nominal = np.loadtxt(nominal_path, delimiter=";", comments="#")
    evidence = [_fingerprint(OUT / MANIFEST), _fingerprint(OUT / DOMAIN_GATE)]
    evidence += [_fingerprint(OUT / (base["id"] + suffix)) for suffix in ("-PREPARED.json", "-AUDIT.json", "-SOLVER.json")]
    path = OUT / REGISTRY
    if path.exists():
        registry = _read(path)
        if (registry.get("schema") != "f3.nopen.development_registry.v1"
                or registry.get("recipe_id") != RECIPE or registry.get("resource_category") != "development"
                or registry.get("cases") != manifest["cases"] or registry.get("evidence") != evidence
                or registry.get("production_resolution_m") != gate["production_resolution_m"]
                or registry.get("max_attempts_per_case") != 1
                or registry.get("solver_timeout_seconds") != 1800
                or registry.get("pilot_case_ids") != [r["case_id"] for r in manifest["cases"] if r["pilot"]]
                or registry.get("program_sha256") != q2.sha256(Path(__file__))
                or registry.get("qualification_driver_sha256") != q2.sha256(Path(qualification.__file__))):
            raise ValueError("immutable development registration or its qualified sources changed")
        source = registry["initial_source"]
        if (source.get("prefix") != _relative(prefix)
                or set(source.get("assets", {})) != set(qualification._asset_names(prefix))):
            raise ValueError("development registration does not use the qualified native initial source")
        qualification._verify_assets(_path(source["prefix"]), source["assets"])
        actual_initial = qualification._initial_state(prefix, .01)
        if any(source.get(key) != value for key, value in actual_initial.items()):
            raise ValueError("registered development native initial-state metadata differs from the actual BI4")
    else:
        if not register:
            raise ValueError("independent development execution has not been registered")
        # Check all 32 physical controls once at execution registration, keeping
        # their original input hashes and pilot roles. Each selected CSV is checked
        # again before copying or accepting a completed case.
        for row in manifest["cases"]:
            _control(row, manifest, nominal)
        source = dict(prefix=_relative(prefix),
                      assets={name: q2.sha256(prefix.parent / name) for name in qualification._asset_names(prefix)},
                      **qualification._initial_state(prefix, .01))
        registry = dict(schema="f3.nopen.development_registry.v1", recorded_at_utc=q2.utc_now(),
                        scope="independent_development_execution_after_qualified_reference_domain",
                        recipe_id=RECIPE, resource_category="development", production_resolution_m=.01,
                        time_window_s=[0, 8.35], output_interval_s=.01, evidence=evidence,
                        source_qualification_case_id=base["id"], initial_source=source,
                        cases=manifest["cases"], pilot_case_ids=[r["case_id"] for r in manifest["cases"] if r["pilot"]],
                        max_attempts_per_case=1, solver_timeout_seconds=1800,
                        program_sha256=q2.sha256(Path(__file__)), qualification_driver_sha256=q2.sha256(Path(qualification.__file__)),
                        original_inputs_are_solver_results=False, auto_run_remaining_cases=False,
                        material_layers_qualified=[], training_completed=False, formal_release=False)
        _write(REGISTRY, registry)
    return dict(gate=gate, manifest=manifest, registry=registry, base=base, nominal=nominal)


def _row(case_id, context):
    rows = [r for r in context["manifest"]["cases"] if r["case_id"] == case_id]
    if len(rows) != 1:
        raise ValueError("case is not an independent registered development candidate")
    return rows[0]


def _fields(row, context, target):
    source = context["registry"]["initial_source"]
    prefix = _path(source["prefix"])
    return dict(id=row["case_id"], case_id=row["case_id"], family="F3", background_id="plain",
                phase="F3_native_nopen_development", resource_category="development", recipe_id=RECIPE,
                dp_m=.01, resolution="0.01", generated_prefix=_relative(target / prefix.name),
                candidate_definition=_relative(target / (prefix.name + "_Def.xml")),
                drive_amplitude=row["drive_amplitude"], drive_sha256=row["control_file_sha256"],
                effective_control_sha256=row["effective_control_sha256"], physical_lineage_sha256=row["physical_lineage_sha256"],
                registered_control_path=row["control_path"], candidate_index=row["index"],
                split=row["split"], evaluation_role=row["evaluation_role"], pilot=row["pilot"],
                solver_mode="-mdbc_noslip:1", expected_slip_mode="No-slip", expected_no_penetration=True,
                max_attempts=1, solver_timeout_seconds=1800, cfl_number=.05, coef_dt_min=.05,
                time_max_s=8.35, time_out_s=.01, visco_bound_factor=1,
                gencase={**{k: source[k] for k in ("total_particles", "fluid_particles", "boundary_particles")},
                         "reuse_source": str(Path(source["prefix"]).parent)},
                actual_y_layers=18, initial_mass_kg=source["initial_mass_kg"], initial_com_m=source["initial_com_m"],
                initial_target_mass_kg=14.58, initial_mass_relative_error=abs(source["initial_mass_kg"] / 14.58 - 1),
                native_velocity_displacement_correction=True, posthoc_particle_projection=False,
                control_definition="F3_CELL3_gravity_preserving_amplitude_v1",
                development_registry_path=_relative(OUT / REGISTRY), development_registry_sha256=q2.sha256(OUT / REGISTRY),
                source_domain_gate_sha256=q2.sha256(OUT / DOMAIN_GATE), source_candidate_manifest_sha256=q2.sha256(OUT / MANIFEST),
                reference_recipe_and_domain_verified=True, development_case_hard_audit_passed=False,
                material_layers_qualified=[], qualified=False, formal_release=False,
                comparison_scope="Independent physical forcing case inside the scored NoPen reference domain; public development only",
                input_repair="Reuse qualified native NoPen initial-state/solver inputs with the exact registered independent CSV")


def _validate_record(record, row, context):
    target = LAB / "campaigns/l1-resume/artifacts/f3-nopen-development" / row["case_id"]
    expected = _fields(row, context, target)
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError("development prepared record differs from its independent registered case")
    source = context["registry"]["initial_source"]
    source_prefix = _path(source["prefix"])
    prefix = _path(record["generated_prefix"])
    qualification._verify_assets(prefix, record["input_assets"])
    if record.get("generated_xml_sha256") != source["assets"][prefix.name + ".xml"]:
        raise ValueError("development XML does not use the qualified numerical recipe")
    for filename, digest in source["assets"].items():
        expected_digest = row["control_file_sha256"] if filename == "CaseSloshingAccData.csv" else digest
        if record["input_assets"].get(filename) != expected_digest:
            raise ValueError("development native assets or precise control bytes changed")
    if source_prefix.name != prefix.name:
        raise ValueError("development native initial prefix changed")
    _control(row, context["manifest"], context["nominal"])


def _prepare(case_id, context):
    row = _row(case_id, context)
    control_path = _control(row, context["manifest"], context["nominal"])
    saved = OUT / (case_id + "-PREPARED.json")
    if saved.exists():
        record = _read(saved)
        _validate_record(record, row, context)
        check_input(record)
        return record
    target = LAB / "campaigns/l1-resume/artifacts/f3-nopen-development" / case_id
    attempts = LAB / "campaigns/l1-resume/runs/branches" / case_id / "attempts"
    if target.exists() or attempts.exists():
        raise ValueError("incomplete or attempted development preparation exists; do not overwrite")
    target.mkdir(parents=True)
    source = context["registry"]["initial_source"]
    prefix = _path(source["prefix"])
    for filename in source["assets"]:
        shutil.copy2(control_path if filename == "CaseSloshingAccData.csv" else prefix.parent / filename,
                     target / filename)
    record = copy.deepcopy(context["base"])
    record.update(_fields(row, context, target))
    record["wall_spec"].pop("runtime_domain", None)
    record.update(input_assets={p.name: q2.sha256(p) for p in target.iterdir() if p.is_file()},
                  generated_xml_sha256=q2.sha256(target / (prefix.name + ".xml")))
    _validate_record(record, row, context)
    check_input(record)
    _write(saved.name, record)
    return record


def prepare(case_id):
    candidate(case_id)  # Reject non-development identities before writes/charges.
    check_budget(category="development")
    return _prepare(case_id, _context(register=True))


def _verified_development(case_id, context):
    from scripts.l1r_branch_runner import check_completed_boundary

    row = _row(case_id, context)
    record = _read(OUT / (case_id + "-PREPARED.json"))
    _validate_record(record, row, context)
    audit = _read(OUT / (case_id + "-AUDIT.json"))
    qualification._hard_audit(record, audit)
    solver = _read(OUT / (case_id + "-SOLVER.json"))
    if (solver.get("case_id") != case_id or solver.get("status") != "completed"
            or solver.get("resource_category") != "development"
            or solver.get("solver_sha256") != q2.sha256(q2.SOLVER)):
        raise ValueError("development solver case/category/executable is not the registered completed run")
    executed = solver.get("source_record", {})
    for key in ("id", "generated_prefix", "input_assets", "gencase", "solver_mode", "recipe_id",
                "resource_category", "drive_amplitude", "effective_control_sha256", "physical_lineage_sha256"):
        if executed.get(key) != record.get(key):
            raise ValueError("development inputs differ from the actual solver source_record")
    check_completed_boundary(record, solver)
    return record, audit, solver


def verified_development(case_id):
    """Read-only complete development source verification for downstream loading."""
    candidate(case_id)
    return _verified_development(case_id, _context(register=False))


def run(case_id):
    row = candidate(case_id)
    check_budget(category="development")
    context = _context(register=True)
    if not row["pilot"]:
        # Read the frozen manifest flags, not a replacement set of surviving runs.
        pilot = [r["case_id"] for r in context["manifest"]["cases"] if r["pilot"]]
        for pilot_id in pilot:
            _verified_development(pilot_id, context)
    record = _prepare(case_id, context)
    from scripts.l1r_branch_runner import run as shared_run

    result = shared_run(record)
    failure = None
    try:
        qualification._hard_audit(record, result)
        _verified_development(case_id, context)
    except (ValueError, KeyError, FileNotFoundError) as error:
        failure = str(error)
    return dict(case_id=case_id, resource_category="development", pilot=row["pilot"],
                status="completed" if failure is None else "failed", audit_status=result.get("audit_status"),
                solver_status=result.get("status"),
                frames=result.get("frames"), issues=result.get("issues"), unknowns=result.get("unknowns"),
                hard_audit_passed=failure is None, failure_reason=failure,
                reference_recipe_and_domain_verified=True, material_layers_qualified=[],
                remaining_cases_launched=False, formal_release=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("case_id")
    args = parser.parse_args(argv)
    if args.action == "prepare":
        print(prepare(args.case_id)["id"], flush=True)
        return 0
    result = run(args.case_id)
    print(json.dumps(result), flush=True)
    return 0 if result["hard_audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
