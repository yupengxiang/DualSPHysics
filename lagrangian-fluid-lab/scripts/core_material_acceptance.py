"""Read-only acceptance checks for the independent material overlay.

The material tracer is a diagnostic overlay.  This module deliberately keeps
its result separate from the Core registry and from qualification: a passing
check here means that an artifact is internally consistent and that its
registered gates can be evaluated.  It never grants T2.

The checks are CPU-only.  They inspect JSON, HDF5 metadata and the small
checkpoint sidecar emitted by :mod:`scripts.core_material`; they do not open a
solver input, acquire a resource slot or start a computation.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np


UNKNOWN_FRACTION_LIMIT = 0.01
ACCEPTANCE_SCHEMA = "core.material.acceptance.v1"
F4_TALLWALL120_DIAGNOSTIC_SCHEMA = "core.material.f4.tallwall120.diagnostic.v1"
F4_TALLWALL120_GENERATION_SCHEMA = "core.material.f4.tallwall120.generation.v1"
F4_TALLWALL120_CHECKPOINT_SCHEMA = "core.material.f4.tallwall120.checkpoint.v2"
F4_TALLWALL120_UNKNOWN_FRACTION_LIMIT = 0.01
F4_TALLWALL120_ENDPOINT_TOLERANCE_M = 1.0e-8
F4_TALLWALL120_SAVED_CHORD_CROSSINGS_ALLOWED = 0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHECKPOINT_FIELDS_F3 = (
    "position", "reliable", "first_passage", "return_time", "residence",
    "residence_left", "residence_right", "returned",
)
_CHECKPOINT_FIELDS_F4 = (
    "position", "reliable", "contact_time", "upward_time", "return_time",
    "residence", "contacted", "upward", "returned",
)


def _digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _as_binding(binding):
    if isinstance(binding, (bytes, np.bytes_)):
        binding = binding.decode("utf-8")
    if isinstance(binding, str):
        try:
            binding = json.loads(binding)
        except json.JSONDecodeError as error:
            raise ValueError("material binding is not valid JSON") from error
    if not isinstance(binding, dict):
        raise ValueError("material binding must be an object")
    return binding


def _finite_number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _sha256(value, name, *, allow_provider=False):
    if allow_provider and value == "provider-supplied":
        return value
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _normalize_source_rows(rows, expected):
    if not isinstance(rows, list):
        raise ValueError("source coverage must be a list")
    seen = set()
    total_mass = 0.0
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or "source_id" not in row:
            raise ValueError("source coverage row must declare source_id")
        source = str(row["source_id"])
        if not source or source in seen or source not in expected:
            raise ValueError("duplicate or undeclared material source")
        seen.add(source)
        mass = _finite_number(row.get("initial_mass_kg"), "initial_mass_kg")
        unknown = _finite_number(row.get("unknown_fraction_max"), "unknown_fraction_max")
        if mass <= 0:
            raise ValueError("source mass denominator must be positive")
        if not 0 <= unknown <= 1:
            raise ValueError("source unknown fraction must be in [0,1]")
        total_mass += mass
        normalized.append({
            "source_id": source,
            "initial_mass_kg": mass,
            "unknown_fraction_max": unknown,
        })
    if seen != set(expected):
        raise ValueError("missing material source coverage")
    return normalized, total_mass


def validate_source_coverage(rows, required_source_ids, maximum_unknown_fraction=UNKNOWN_FRACTION_LIMIT):
    """Validate full-denominator, per-source material coverage.

    ``rows`` must contain one row for every explicitly registered source.  The
    unknown fraction is charged against that source's own initial mass; an
    aggregate unknown fraction can therefore never hide one failing source.
    This is a necessary gate only and does not make a material result a T2
    result.
    """
    if not isinstance(required_source_ids, list) or not required_source_ids:
        raise ValueError("required material sources must be explicitly declared")
    expected = [str(x) for x in required_source_ids]
    if any(not source for source in expected):
        raise ValueError("required material source id must be non-empty")
    if len(set(expected)) != len(expected):
        raise ValueError("duplicate required material source")
    maximum = _finite_number(maximum_unknown_fraction, "unknown mass limit")
    if not 0 <= maximum <= UNKNOWN_FRACTION_LIMIT:
        raise ValueError("unknown mass limit must be finite and no greater than 1%")
    normalized, total_mass = _normalize_source_rows(rows, expected)
    for row in normalized:
        if row["unknown_fraction_max"] > maximum:
            raise ValueError("material source unknown mass exceeds registered limit: " + row["source_id"])
    return {
        "all_sources_pass": True,
        "source_count": len(expected),
        "total_initial_mass_kg": total_mass,
        "maximum_source_unknown_fraction": max(row["unknown_fraction_max"] for row in normalized),
        "sources": normalized,
    }


def validate_material_binding(
    binding,
    *,
    expected_schema=None,
    source=None,
    expected_neighbour_variant=None,
    verify_code_hashes=True,
):
    """Validate an immutable F3/F4 material binding and return its JSON object.

    The backend, neighbour count, estimator and fixed support gate are checked
    against the registered constants in ``core_material.py``.  Code and input
    hashes are checked when available; callers auditing a moved historical
    artifact can set ``verify_code_hashes=False`` while retaining the binding
    shape and variant checks.
    """
    binding = _as_binding(binding)
    from scripts import core_material as material

    schema = binding.get("schema")
    accepted_schemas = {material.SCHEMA, material.F4_SCHEMA}
    if schema not in accepted_schemas:
        raise ValueError("unsupported material binding schema")
    if expected_schema is not None and schema != expected_schema:
        raise ValueError("material binding schema mismatch")
    required = (
        "source_sha256", "code_sha256", "neighbor_code_sha256", "passive_code_sha256",
        "initial_sha256", "weight_sha256", "source_label_sha256", "tracer_id_sha256",
        "walls_sha256", "backend", "neighbour_variant", "neighbours", "error_estimator",
        "regularization_m", "maximum_support_distance_m", "support_gate",
    )
    missing = [name for name in required if name not in binding]
    if missing:
        raise ValueError("material binding is missing: " + ", ".join(missing))
    _sha256(binding["source_sha256"], "source_sha256", allow_provider=True)
    for name in (
        "code_sha256", "neighbor_code_sha256", "passive_code_sha256",
        "initial_sha256", "weight_sha256", "source_label_sha256",
        "tracer_id_sha256", "walls_sha256",
    ):
        _sha256(binding[name], name)
    variant = binding["neighbour_variant"]
    if expected_neighbour_variant is not None and variant != expected_neighbour_variant:
        raise ValueError("material neighbour variant mismatch")
    try:
        expected_backend, expected_neighbours = material.NEIGHBOUR_VARIANTS[variant]
        expected_estimator = material.ERROR_ESTIMATORS[variant]
    except (KeyError, TypeError) as error:
        raise ValueError("unregistered material neighbour variant") from error
    if binding["backend"] != expected_backend or binding["neighbours"] != expected_neighbours:
        raise ValueError("material backend/neighbor binding mismatch")
    if binding["error_estimator"] != expected_estimator:
        raise ValueError("material error estimator binding mismatch")
    if _finite_number(binding["regularization_m"], "regularization_m") != float(material.REGULARIZATION_M):
        raise ValueError("material regularization binding mismatch")
    if _finite_number(binding["maximum_support_distance_m"], "maximum_support_distance_m") != float(material.MAXIMUM_SUPPORT_DISTANCE_M):
        raise ValueError("material support distance binding mismatch")
    gate = binding["support_gate"]
    if not isinstance(gate, dict) or set(gate) != set(material.GATE):
        raise ValueError("material support gate binding mismatch")
    for name, expected in material.GATE.items():
        if _finite_number(gate[name], "support_gate." + name) != float(expected):
            raise ValueError("material support gate binding mismatch: " + name)
    if schema == material.F4_SCHEMA and not isinstance(binding.get("f4_definition"), dict):
        raise ValueError("F4 material binding must include f4_definition")
    if schema == material.SCHEMA and not isinstance(binding.get("source_definition"), dict):
        raise ValueError("F3 material binding must include source_definition")
    if verify_code_hashes:
        expected_files = {
            "code_sha256": Path(material.__file__),
            "neighbor_code_sha256": Path(material.__file__).with_name("f3_material_neighbors.py"),
            "passive_code_sha256": Path(material.__file__).with_name("passive_tracers.py"),
        }
        for name, path in expected_files.items():
            if _digest(path) != binding[name]:
                raise ValueError("material code version binding mismatch: " + name)
    if source is not None:
        expected_source = _digest(source)
        if binding["source_sha256"] != expected_source:
            raise ValueError("material source version binding mismatch")
    return binding


def _checkpoint_paths(output):
    output = Path(output)
    return (
        output.with_name(output.name + ".checkpoint.npz"),
        output.with_name(output.name + ".checkpoint.json"),
    )


def _validate_checkpoint_state(state, fields):
    expected = _CHECKPOINT_FIELDS_F4 if fields == _CHECKPOINT_FIELDS_F4 else _CHECKPOINT_FIELDS_F3
    if tuple(fields) != tuple(expected) or set(state) != set(expected):
        raise ValueError("material checkpoint fields do not match its schema")
    position = np.asarray(state["position"])
    if position.ndim != 2 or position.shape[1:] != (3,) or not np.isfinite(position).all():
        raise ValueError("material checkpoint position has an invalid shape or value")
    count = len(position)
    for name in expected:
        if name == "position":
            continue
        value = np.asarray(state[name])
        if value.shape != (count,):
            raise ValueError("material checkpoint state axes do not match position")
        if name in ("reliable", "returned", "contacted", "upward"):
            if value.dtype.kind != "b":
                raise ValueError("material checkpoint boolean state must use bool dtype")
        elif np.isinf(value).any() or (name == "residence" and not np.isfinite(value).all()):
            raise ValueError("material checkpoint numeric state contains non-finite values")
    if np.any(np.asarray(state["residence"]) < 0):
        raise ValueError("material checkpoint residence cannot be negative")
    return {name: np.array(state[name], copy=True) for name in expected}


def validate_checkpoint_manifest(
    output,
    *,
    binding=None,
    expected_schema=None,
    expected_committed=None,
):
    """Validate a material checkpoint sidecar without mutating the artifact."""
    npz_path, manifest_path = _checkpoint_paths(output)
    if not npz_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("material checkpoint sidecar is incomplete")
    try:
        record = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("material checkpoint manifest is not valid JSON") from error
    from scripts import core_material as material

    schemas = {
        material.CHECKPOINT_SCHEMA: (material.SCHEMA, _CHECKPOINT_FIELDS_F3),
        material.F4_CHECKPOINT_SCHEMA: (material.F4_SCHEMA, _CHECKPOINT_FIELDS_F4),
    }
    schema = record.get("schema")
    if schema not in schemas:
        raise ValueError("unsupported material checkpoint schema")
    artifact_schema, fields = schemas[schema]
    if expected_schema is not None and schema != expected_schema:
        raise ValueError("material checkpoint schema mismatch")
    if binding is not None:
        if isinstance(binding, dict):
            binding = _canonical(binding)
        if not isinstance(binding, str):
            raise ValueError("checkpoint binding must be JSON text or an object")
        expected_binding = hashlib.sha256(binding.encode()).hexdigest()
        if record.get("binding_sha256") != expected_binding:
            raise ValueError("material checkpoint provenance mismatch")
    committed = record.get("committed")
    if isinstance(committed, bool) or not isinstance(committed, (int, np.integer)) or int(committed) < 0:
        raise ValueError("material checkpoint committed frame is invalid")
    committed = int(committed)
    if expected_committed is not None and committed != int(expected_committed):
        raise ValueError("material checkpoint committed frame mismatch")
    if record.get("fields") != list(fields):
        raise ValueError("material checkpoint fields are incomplete")
    if _digest(npz_path) != record.get("state_sha256"):
        raise ValueError("material checkpoint state hash mismatch")
    try:
        with np.load(npz_path, allow_pickle=False) as archive:
            names = tuple(archive.files)
            state = {name: np.array(archive[name], copy=True) for name in names}
    except (OSError, ValueError) as error:
        raise ValueError("material checkpoint state is unreadable") from error
    state = _validate_checkpoint_state(state, fields)
    return {
        "schema": ACCEPTANCE_SCHEMA,
        "checkpoint_schema": schema,
        "artifact_schema": artifact_schema,
        "committed": committed,
        "fields": list(fields),
        "state_sha256": record["state_sha256"],
        "manifest": record,
        "state": state,
    }


def _source_rows_from_summary(summary):
    rows = summary.get("by_source") if isinstance(summary, dict) else None
    if not isinstance(rows, list):
        raise ValueError("material summary must declare by_source rows")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or "source" not in row:
            raise ValueError("material summary source row must declare source")
        mass = row.get("initial_mass_kg", row.get("initial_mass_fraction"))
        unknown = row.get("unknown_fraction_max", row.get("unknown_fraction"))
        normalized.append({
            "source_id": str(row["source"]),
            "initial_mass_kg": mass,
            "unknown_fraction_max": unknown,
        })
    return normalized


def evaluate_material_summary(
    summary,
    required_source_ids,
    maximum_unknown_fraction=UNKNOWN_FRACTION_LIMIT,
    *,
    require_complete_window=False,
    cdf_sup_abs_difference=None,
    cdf_limit=None,
):
    """Evaluate registered material gates while preserving the no-T2 boundary.

    Structural errors raise ``ValueError``.  A scientific gate failure returns
    ``passed=False`` with its reason, which lets a CPU-only audit preserve
    negative evidence instead of mistaking it for a missing artifact.
    """
    if not isinstance(summary, dict):
        raise ValueError("material summary must be an object")
    if summary.get("qualification_claim", "none") not in ("none", None):
        raise ValueError("material diagnostic summary carries a qualification claim")
    if summary.get("T2_macro", False) is True or summary.get("qualified_T2_macro", False) is True:
        raise ValueError("material diagnostic cannot claim T2_macro")
    try:
        coverage = validate_source_coverage(
            _source_rows_from_summary(summary), required_source_ids, maximum_unknown_fraction
        )
        unknown_pass = True
        unknown_reason = None
    except ValueError as error:
        rows = _source_rows_from_summary(summary)
        if not isinstance(required_source_ids, list) or not required_source_ids:
            raise
        expected = [str(item) for item in required_source_ids]
        if len(set(expected)) != len(expected) or any(not item for item in expected):
            raise
        normalized, total_mass = _normalize_source_rows(rows, expected)
        coverage = {
            "all_sources_pass": False,
            "source_count": len(expected),
            "total_initial_mass_kg": total_mass,
            "maximum_source_unknown_fraction": max(row["unknown_fraction_max"] for row in normalized),
            "sources": normalized,
        }
        unknown_pass = False
        unknown_reason = str(error)
    mass_closed = summary.get("mass_closed") is True
    if not mass_closed:
        raise ValueError("material summary mass closure is not established")
    event_pass = True
    event_reason = None
    if require_complete_window:
        event_pass = summary.get("event_window_complete") is True and summary.get("event_window_status") == "complete"
        if not event_pass:
            event_reason = "material event window is incomplete or right-censored"
    cdf_pass = True
    cdf_reason = None
    if cdf_sup_abs_difference is not None or cdf_limit is not None:
        if cdf_sup_abs_difference is None or cdf_limit is None:
            raise ValueError("CDF difference and limit must be supplied together")
        difference = _finite_number(cdf_sup_abs_difference, "CDF difference")
        limit = _finite_number(cdf_limit, "CDF limit")
        if difference < 0 or limit < 0:
            raise ValueError("CDF difference and limit must be nonnegative")
        cdf_pass = difference <= limit
        if not cdf_pass:
            cdf_reason = f"CDF difference {difference} exceeds registered limit {limit}"
    return {
        "schema": ACCEPTANCE_SCHEMA,
        "status": "diagnostic_only",
        "passed": bool(unknown_pass and mass_closed and event_pass and cdf_pass),
        "qualification_claim": "none",
        "T2_macro": False,
        "T2_path": False,
        "source_coverage": coverage,
        "unknown_gate_pass": bool(unknown_pass),
        "unknown_gate_reason": unknown_reason,
        "mass_closed": mass_closed,
        "event_window_pass": bool(event_pass),
        "event_window_reason": event_reason,
        "cdf_gate_pass": bool(cdf_pass),
        "cdf_gate_reason": cdf_reason,
    }


def evaluate_material_output_json(
    payload,
    *,
    required_source_ids,
    expected_family=None,
    expected_case_id=None,
    require_complete_window=False,
    cdf_sup_abs_difference=None,
    cdf_limit=None,
):
    """Evaluate the v1 JSON material contract without granting qualification.

    This is the acceptance-layer consumer for
    :mod:`core_material_output_contract_v1`.  It accepts an already
    materialized JSON-like object only; it does not read HDF5, bridge receipts,
    paths, registries or ledgers.  ``passed`` means that the supplied JSON
    satisfies the requested diagnostic gates.  It is never a T1/T2 credit.

    ``required_source_ids`` is deliberately mandatory and external.  The
    output cannot infer a complete registered source set from its own rows.
    When ``require_complete_window`` is true, any right-censored event keeps
    the diagnostic acceptance gate closed.
    """
    from scripts.core_material_output_contract_v1 import (
        EVENTS,
        MASS_CLOSURE_TOLERANCE_KG,
        OUTPUT_SCHEMA,
        evaluate_material_output,
    )

    if isinstance(required_source_ids, (str, bytes)) or not isinstance(required_source_ids, list):
        raise ValueError("required_source_ids must be a non-empty list")
    if not required_source_ids:
        raise ValueError("required_source_ids must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in required_source_ids):
        raise ValueError("required_source_ids must contain unique non-empty ids")
    normalized_source_ids = list(required_source_ids)
    if len(set(normalized_source_ids)) != len(normalized_source_ids):
        raise ValueError("required_source_ids must contain unique non-empty ids")

    contract = evaluate_material_output(payload)
    if contract["schema"] != OUTPUT_SCHEMA:
        raise ValueError("material JSON contract schema mismatch")
    if expected_family is not None and contract["family"] != expected_family:
        raise ValueError("material JSON family does not match expected_family")
    if expected_case_id is not None and contract["case_id"] != expected_case_id:
        raise ValueError("material JSON case_id does not match expected_case_id")

    source_coverage = payload.get("source_coverage")
    if not isinstance(source_coverage, dict):
        raise ValueError("material JSON must include source_coverage for acceptance")
    declared_ids = source_coverage.get("required_source_ids")
    if declared_ids != sorted(normalized_source_ids):
        raise ValueError("material JSON source_coverage does not match required_source_ids")
    if source_coverage.get("family") != contract["family"] or source_coverage.get("case_id") != contract["case_id"]:
        raise ValueError("material JSON source_coverage identity does not match output")
    rows = source_coverage.get("rows")
    coverage, coverage_reason = _coverage_audit(
        rows,
        normalized_source_ids,
        UNKNOWN_FRACTION_LIMIT,
    )
    initial_mass = contract["mass"]["initial_mass_kg"]
    if abs(coverage["total_initial_mass_kg"] - initial_mass) > MASS_CLOSURE_TOLERANCE_KG:
        raise ValueError("material JSON source coverage does not close the output mass denominator")

    event_pass = True
    event_reason = None
    if require_complete_window:
        censored = [
            name for name in EVENTS
            if contract["events"][name]["censor"]["type"] == "right"
        ]
        event_pass = not censored
        if not event_pass:
            event_reason = "material JSON contains right-censored event(s): " + ", ".join(censored)

    cdf_pass = True
    cdf_reason = None
    if cdf_sup_abs_difference is not None or cdf_limit is not None:
        if cdf_sup_abs_difference is None or cdf_limit is None:
            raise ValueError("CDF difference and limit must be supplied together")
        difference = _finite_number(cdf_sup_abs_difference, "CDF difference")
        limit = _finite_number(cdf_limit, "CDF limit")
        if difference < 0 or limit < 0:
            raise ValueError("CDF difference and limit must be nonnegative")
        cdf_pass = difference <= limit
        if not cdf_pass:
            cdf_reason = f"CDF difference {difference} exceeds registered limit {limit}"

    source_pass = bool(coverage["all_sources_pass"])
    unknown_pass = bool(contract["unknown_bound"]["gate_pass"] and source_pass)
    gates = {
        "output_contract": bool(contract["passed"]),
        "source_coverage": source_pass,
        "unknown_bound": unknown_pass,
        "complete_event_window": bool(event_pass),
        "cdf_comparison": bool(cdf_pass),
    }
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "schema": ACCEPTANCE_SCHEMA,
        "status": "diagnostic_only",
        "diagnostic_only": True,
        "input_schema": OUTPUT_SCHEMA,
        "passed": not failures,
        "failure_reasons": failures,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "qualified_T2_macro": False,
        "qualified_T2_path": False,
        "family": contract["family"],
        "case_id": contract["case_id"],
        "source_coverage": coverage,
        "source_coverage_reason": coverage_reason,
        "event_window_pass": bool(event_pass),
        "event_window_reason": event_reason,
        "cdf_gate_pass": bool(cdf_pass),
        "cdf_gate_reason": cdf_reason,
        "gates": gates,
        "contract": contract,
        "execution_constraints": {
            "read_only": True,
            "json_source_only": True,
            "hdf5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "registry_written": False,
            "ledger_written": False,
            "evidence_written": False,
            "qualification_credit_registered": 0,
        },
    }


_F4_TALLWALL120_IDENTITY_FIELDS = ("case_id", "scope_id", "revision_id", "recipe_id")
_F4_TALLWALL120_EVENT_NAMES = ("contact", "upward", "return", "residence")
_F4_TALLWALL120_GATE_NAMES = (
    "schema", "identity", "generation_hash_binding", "checkpoint_hash_binding",
    "source_denominator", "unknown_bound", "contact", "upward", "return",
    "residence", "complete_event_window", "right_censor_free",
    "f4_cdf_tolerance", "f4_residence_tolerance", "f4_endpoint_tolerance",
    "f4_saved_chord_tolerance",
)


def _f4_tallwall120_json_like(value, path="payload", active=None):
    """Reject non-JSON values before the F4-only validator inspects a value."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{path} contains a cyclic object")
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} has a non-string object key")
                _f4_tallwall120_json_like(item, f"{path}.{key}", active)
        finally:
            active.remove(identity)
        return
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{path} contains a cyclic list")
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _f4_tallwall120_json_like(item, f"{path}[{index}]", active)
        finally:
            active.remove(identity)
        return
    raise ValueError(f"{path} is not JSON-like")


def _f4_tallwall120_object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _f4_tallwall120_list(value, name):
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _f4_tallwall120_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _f4_tallwall120_number(value, name, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def _f4_tallwall120_identity(payload):
    if payload.get("family") != "F4":
        raise ValueError("F4 tallwall120 diagnostic family must be F4")
    identity = _f4_tallwall120_object(payload.get("identity"), "identity")
    if identity.get("family") != "F4":
        raise ValueError("F4 tallwall120 identity family must be F4")
    normalized = {"family": "F4"}
    for name in _F4_TALLWALL120_IDENTITY_FIELDS:
        root_value = _f4_tallwall120_string(payload.get(name), name)
        identity_value = _f4_tallwall120_string(identity.get(name), "identity." + name)
        if root_value != identity_value:
            raise ValueError("F4 tallwall120 identity binding mismatch: " + name)
        if "tallwall120" not in root_value.lower():
            raise ValueError(name + " must identify tallwall120")
        normalized[name] = root_value
    return normalized


def _f4_tallwall120_hash_bindings(payload, identity, expected_generation, expected_checkpoint):
    bindings = _f4_tallwall120_object(payload.get("hash_bindings"), "hash_bindings")
    normalized = {}
    for kind, schema, expected in (
        ("generation", F4_TALLWALL120_GENERATION_SCHEMA, expected_generation),
        ("checkpoint", F4_TALLWALL120_CHECKPOINT_SCHEMA, expected_checkpoint),
    ):
        entry = _f4_tallwall120_object(bindings.get(kind), "hash_bindings." + kind)
        if entry.get("schema") != schema:
            raise ValueError("hash_bindings." + kind + ".schema mismatch")
        digest = _sha256(entry.get("sha256"), "hash_bindings." + kind + ".sha256")
        bound = _sha256(entry.get("bound_sha256"), "hash_bindings." + kind + ".bound_sha256")
        if digest != bound:
            raise ValueError("hash_bindings." + kind + " hash mismatch")
        if expected is not None:
            expected = _sha256(expected, "expected_" + kind + "_sha256")
            if digest != expected:
                raise ValueError("hash_bindings." + kind + " does not match expected hash")
        if _f4_tallwall120_object(entry.get("identity"), "hash_bindings." + kind + ".identity") != identity:
            raise ValueError("hash_bindings." + kind + " identity mismatch")
        normalized[kind] = {
            "schema": schema,
            "sha256": digest,
            "bound_sha256": bound,
        }
    return normalized


def _f4_tallwall120_source_denominator(payload):
    source = _f4_tallwall120_object(payload.get("source_denominator"), "source_denominator")
    if source.get("denominator_policy") != "all_initial_mass":
        raise ValueError("source_denominator.denominator_policy must be all_initial_mass")
    total = _f4_tallwall120_number(
        source.get("total_initial_mass_kg"), "source_denominator.total_initial_mass_kg", minimum=0.0
    )
    if total <= 0.0:
        raise ValueError("source_denominator.total_initial_mass_kg must be positive")
    rows = _f4_tallwall120_list(source.get("source_rows"), "source_denominator.source_rows")
    if not rows:
        raise ValueError("source_denominator.source_rows must not be empty")
    seen = set()
    normalized_rows = []
    for index, row in enumerate(rows):
        row = _f4_tallwall120_object(row, f"source_denominator.source_rows[{index}]")
        source_id = _f4_tallwall120_string(row.get("source_id"), "source_id")
        if source_id in seen:
            raise ValueError("duplicate source_id in source denominator")
        seen.add(source_id)
        mass = _f4_tallwall120_number(row.get("initial_mass_kg"), "initial_mass_kg", minimum=0.0)
        if mass <= 0.0:
            raise ValueError("source denominator mass must be positive")
        unknown = _f4_tallwall120_number(
            row.get("unknown_fraction_max"), "unknown_fraction_max", minimum=0.0, maximum=1.0
        )
        normalized_rows.append({
            "source_id": source_id,
            "initial_mass_kg": mass,
            "unknown_fraction_max": unknown,
        })
    mass_sum = sum(row["initial_mass_kg"] for row in normalized_rows)
    mass_tolerance = max(1.0e-12, total * 1.0e-12)
    if abs(mass_sum - total) > mass_tolerance:
        raise ValueError("source denominator rows do not close total_initial_mass_kg")

    bound = _f4_tallwall120_object(source.get("unknown_bound"), "source_denominator.unknown_bound")
    if bound.get("denominator_policy") != "all_initial_mass":
        raise ValueError("unknown_bound.denominator_policy must be all_initial_mass")
    observed = _f4_tallwall120_number(bound.get("observed_fraction"), "unknown_bound.observed_fraction", minimum=0.0, maximum=1.0)
    worst = _f4_tallwall120_number(bound.get("worst_case_fraction"), "unknown_bound.worst_case_fraction", minimum=0.0, maximum=1.0)
    limit = _f4_tallwall120_number(bound.get("limit"), "unknown_bound.limit", minimum=0.0, maximum=1.0)
    if limit != F4_TALLWALL120_UNKNOWN_FRACTION_LIMIT:
        raise ValueError("unknown_bound.limit is not the fixed F4 1% limit")
    if worst < observed:
        raise ValueError("unknown_bound.worst_case_fraction cannot be below observed_fraction")
    if bound.get("includes_right_censored_mass") is not True:
        raise ValueError("unknown_bound.includes_right_censored_mass must be true")
    expected_observed = sum(row["initial_mass_kg"] * row["unknown_fraction_max"] for row in normalized_rows) / total
    if abs(observed - expected_observed) > 1.0e-12:
        raise ValueError("unknown_bound.observed_fraction is not bound to source denominator")
    unknown_pass = all(row["unknown_fraction_max"] <= limit for row in normalized_rows) and worst <= limit
    return {
        "denominator_policy": "all_initial_mass",
        "total_initial_mass_kg": total,
        "source_rows": normalized_rows,
        "unknown_bound": {
            "denominator_policy": "all_initial_mass",
            "observed_fraction": observed,
            "worst_case_fraction": worst,
            "limit": limit,
            "includes_right_censored_mass": True,
            "gate_pass": bool(unknown_pass),
        },
        "gate_pass": bool(abs(mass_sum - total) <= mass_tolerance and unknown_pass),
    }, bool(unknown_pass)


def _f4_tallwall120_event(name, event):
    event = _f4_tallwall120_object(event, "events." + name)
    definition = _f4_tallwall120_string(event.get("definition"), "events." + name + ".definition")
    if event.get("denominator_policy") != "all_initial_mass":
        raise ValueError("events." + name + ".denominator_policy must be all_initial_mass")
    fraction = _f4_tallwall120_number(event.get("event_fraction"), "events." + name + ".event_fraction", minimum=0.0, maximum=1.0)
    cdf = _f4_tallwall120_object(event.get("cdf"), "events." + name + ".cdf")
    times = _f4_tallwall120_list(cdf.get("time_s"), "events." + name + ".cdf.time_s")
    lower = _f4_tallwall120_list(cdf.get("lower"), "events." + name + ".cdf.lower")
    upper = _f4_tallwall120_list(cdf.get("upper"), "events." + name + ".cdf.upper")
    if not times or len(times) != len(lower) or len(lower) != len(upper):
        raise ValueError("events." + name + ".cdf arrays must be non-empty and aligned")
    times = [_f4_tallwall120_number(value, "CDF time", minimum=0.0) for value in times]
    lower = [_f4_tallwall120_number(value, "CDF lower", minimum=0.0, maximum=1.0) for value in lower]
    upper = [_f4_tallwall120_number(value, "CDF upper", minimum=0.0, maximum=1.0) for value in upper]
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValueError("events." + name + ".cdf.time_s must be strictly increasing")
    if any(lo > hi for lo, hi in zip(lower, upper)):
        raise ValueError("events." + name + ".cdf lower exceeds upper")
    if any(later < earlier for earlier, later in zip(lower, lower[1:])) or any(later < earlier for earlier, later in zip(upper, upper[1:])):
        raise ValueError("events." + name + ".cdf bounds must be non-decreasing")
    if cdf.get("denominator_policy") != "all_initial_mass":
        raise ValueError("events." + name + ".cdf.denominator_policy must be all_initial_mass")
    censor = _f4_tallwall120_object(event.get("censor"), "events." + name + ".censor")
    censor_type = censor.get("type")
    if censor_type not in ("none", "right"):
        raise ValueError("events." + name + ".censor.type must be none or right")
    censor_fraction = _f4_tallwall120_number(censor.get("fraction"), "censor.fraction", minimum=0.0, maximum=1.0)
    if censor.get("counts_as_acceptance") is not False:
        raise ValueError("events." + name + ".censor.counts_as_acceptance must be false")
    expected_policy = "no_censoring" if censor_type == "none" else "right_censored_mass_remains_in_denominator"
    if censor.get("policy") != expected_policy:
        raise ValueError("events." + name + ".censor.policy mismatch")
    if (censor_type == "none" and censor_fraction != 0.0) or (censor_type == "right" and censor_fraction <= 0.0):
        raise ValueError("events." + name + ".censor.fraction is inconsistent with type")
    normalized = {
        "definition": definition,
        "denominator_policy": "all_initial_mass",
        "event_fraction": fraction,
        "cdf": {"time_s": times, "lower": lower, "upper": upper, "denominator_policy": "all_initial_mass"},
        "censor": {"type": censor_type, "fraction": censor_fraction, "policy": expected_policy, "counts_as_acceptance": False},
    }
    if name == "residence":
        mean = _f4_tallwall120_number(event.get("residence_mean_s"), "events.residence.residence_mean_s", minimum=0.0)
        residence_censored = _f4_tallwall120_number(event.get("residence_censored_fraction"), "events.residence.residence_censored_fraction", minimum=0.0, maximum=1.0)
        if abs(residence_censored - censor_fraction) > 1.0e-12:
            raise ValueError("residence_censored_fraction is not bound to residence censor")
        normalized.update({"residence_mean_s": mean, "residence_censored_fraction": residence_censored})
    return normalized, censor_type == "right"


def _f4_tallwall120_tolerances(payload, identity):
    values = _f4_tallwall120_object(payload.get("f4_tolerances"), "f4_tolerances")
    normalized = {}
    for name in ("cdf", "residence", "endpoint", "saved_chord"):
        entry = _f4_tallwall120_object(values.get(name), "f4_tolerances." + name)
        if entry.get("family") != "F4" or entry.get("registered") is not True:
            raise ValueError("f4_tolerances." + name + " is not registered for F4")
        if entry.get("scope_id") != identity["scope_id"] or entry.get("revision_id") != identity["revision_id"]:
            raise ValueError("f4_tolerances." + name + " identity mismatch")
        normalized[name] = dict(entry)
    cdf_observed = _f4_tallwall120_number(normalized["cdf"].get("observed"), "f4_tolerances.cdf.observed", minimum=0.0)
    cdf_limit = _f4_tallwall120_number(normalized["cdf"].get("tolerance"), "f4_tolerances.cdf.tolerance", minimum=0.0)
    residence_observed = _f4_tallwall120_number(normalized["residence"].get("observed_s"), "f4_tolerances.residence.observed_s", minimum=0.0)
    residence_limit = _f4_tallwall120_number(normalized["residence"].get("tolerance_s"), "f4_tolerances.residence.tolerance_s", minimum=0.0)
    endpoint_observed = _f4_tallwall120_number(normalized["endpoint"].get("observed_max_error_m"), "f4_tolerances.endpoint.observed_max_error_m", minimum=0.0)
    endpoint_limit = _f4_tallwall120_number(normalized["endpoint"].get("tolerance_m"), "f4_tolerances.endpoint.tolerance_m", minimum=0.0)
    if endpoint_limit != F4_TALLWALL120_ENDPOINT_TOLERANCE_M:
        raise ValueError("F4 endpoint tolerance changed")
    saved_observed = normalized["saved_chord"].get("observed_crossings")
    saved_allowed = normalized["saved_chord"].get("allowed_crossings")
    if isinstance(saved_observed, bool) or not isinstance(saved_observed, int) or saved_observed < 0:
        raise ValueError("saved-chord observed_crossings must be a non-negative integer")
    if isinstance(saved_allowed, bool) or not isinstance(saved_allowed, int) or saved_allowed < 0:
        raise ValueError("saved-chord allowed_crossings must be a non-negative integer")
    if saved_allowed != F4_TALLWALL120_SAVED_CHORD_CROSSINGS_ALLOWED:
        raise ValueError("F4 saved-chord allowance changed")
    normalized["cdf"] = {"family": "F4", "registered": True, "observed": cdf_observed, "tolerance": cdf_limit}
    normalized["residence"] = {"family": "F4", "registered": True, "observed_s": residence_observed, "tolerance_s": residence_limit}
    normalized["endpoint"] = {"family": "F4", "registered": True, "observed_max_error_m": endpoint_observed, "tolerance_m": endpoint_limit}
    normalized["saved_chord"] = {"family": "F4", "registered": True, "observed_crossings": saved_observed, "allowed_crossings": saved_allowed}
    return normalized, {
        "f4_cdf_tolerance": cdf_observed <= cdf_limit,
        "f4_residence_tolerance": residence_observed <= residence_limit,
        "f4_endpoint_tolerance": endpoint_observed <= endpoint_limit,
        "f4_saved_chord_tolerance": saved_observed <= saved_allowed,
    }


def _f4_tallwall120_validate(payload, expected_generation, expected_checkpoint):
    if payload.get("schema") != F4_TALLWALL120_DIAGNOSTIC_SCHEMA:
        raise ValueError("unsupported F4 tallwall120 diagnostic schema")
    if payload.get("diagnostic_only", True) is not True:
        raise ValueError("F4 tallwall120 diagnostic must be diagnostic_only")
    if payload.get("status", "diagnostic_only") != "diagnostic_only":
        raise ValueError("F4 tallwall120 diagnostic status must be diagnostic_only")
    if payload.get("qualification_claim", "none") != "none":
        raise ValueError("F4 tallwall120 diagnostic carries a qualification claim")
    for name in ("credit", "qualification_credit"):
        value = payload.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 0.0:
            raise ValueError("F4 tallwall120 diagnostic credit must be zero")
    for name in ("T2_macro", "T2_path", "qualified_T2_macro", "qualified_T2_path"):
        if payload.get(name, False) is not False:
            raise ValueError("F4 tallwall120 diagnostic cannot claim " + name)
    identity = _f4_tallwall120_identity(payload)
    hashes = _f4_tallwall120_hash_bindings(payload, identity, expected_generation, expected_checkpoint)
    source, unknown_pass = _f4_tallwall120_source_denominator(payload)
    events_payload = _f4_tallwall120_object(payload.get("events"), "events")
    events = {}
    censored = False
    event_gates = {}
    for name in _F4_TALLWALL120_EVENT_NAMES:
        events[name], event_censored = _f4_tallwall120_event(name, events_payload.get(name))
        censored = censored or event_censored
        event_gates[name] = not event_censored
    event_window = _f4_tallwall120_object(payload.get("event_window"), "event_window")
    if not isinstance(event_window.get("complete"), bool):
        raise ValueError("event_window.complete must be boolean")
    if not isinstance(event_window.get("right_censored"), bool):
        raise ValueError("event_window.right_censored must be boolean")
    if not isinstance(event_window.get("status"), str):
        raise ValueError("event_window.status is required")
    complete_window = event_window["complete"] is True and event_window["status"] == "complete" and event_window["right_censored"] is False
    censored = censored or event_window["right_censored"] is True or event_window["status"] != "complete"
    tolerances, tolerance_gates = _f4_tallwall120_tolerances(payload, identity)
    gates = {name: True for name in _F4_TALLWALL120_GATE_NAMES}
    gates.update({"complete_event_window": complete_window, "right_censor_free": not censored, "unknown_bound": unknown_pass})
    gates.update(event_gates)
    gates.update(tolerance_gates)
    reasons = []
    if not unknown_pass:
        reasons.append("source unknown bound exceeds the fixed F4 1% limit")
    if censored:
        reasons.append("right-censored or incomplete F4 event window is not acceptance")
    for name, passed in tolerance_gates.items():
        if not passed:
            reasons.append(name + " failed")
    return {
        "identity": identity,
        "hash_bindings": hashes,
        "source_denominator": source,
        "events": events,
        "event_window": {
            "complete": bool(event_window["complete"]),
            "status": event_window["status"],
            "right_censored": bool(event_window["right_censored"]),
        },
        "f4_tolerances": tolerances,
        "gates": gates,
        "blocking_reasons": reasons,
    }


def evaluate_f4_tallwall120_diagnostic_json(
    payload,
    *,
    expected_generation_sha256=None,
    expected_checkpoint_sha256=None,
):
    """Evaluate an F4/tallwall120 JSON diagnostic without touching artifacts.

    The input is JSON-like only.  Generation/checkpoint hashes are compared to
    their explicit ``bound_sha256`` fields and, when supplied, to the caller's
    expected hashes.  Missing or malformed fields, right censoring, an unknown
    bound above 1%, or any F4 tolerance failure return a blocked diagnostic.
    This function never opens HDF5/bridge inputs and never writes state.
    """
    result = {
        "schema": F4_TALLWALL120_DIAGNOSTIC_SCHEMA,
        "status": "diagnostic_only",
        "diagnostic_only": True,
        "passed": False,
        "diagnostic_state": "blocked_diagnostic",
        "qualification_claim": "none",
        "credit": 0,
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "qualified_T2_macro": False,
        "qualified_T2_path": False,
        "failure_reasons": [],
        "blocking_reasons": [],
        "gates": {name: False for name in _F4_TALLWALL120_GATE_NAMES},
        "execution_constraints": {
            "read_only": True,
            "json_source_only": True,
            "hdf5_opened": False,
            "bridge_read": False,
            "solver_started": False,
            "gpu_started": False,
            "registry_written": False,
            "ledger_written": False,
            "evidence_written": False,
            "completion_written": False,
            "qualification_credit_registered": 0,
        },
    }
    try:
        _f4_tallwall120_json_like(payload)
        if not isinstance(payload, dict):
            raise ValueError("F4 tallwall120 diagnostic payload must be an object")
        checked = _f4_tallwall120_validate(payload, expected_generation_sha256, expected_checkpoint_sha256)
    except (TypeError, ValueError) as error:
        result["failure_reasons"] = ["structural_validation"]
        result["blocking_reasons"] = [str(error)]
        return result
    result.update({key: value for key, value in checked.items() if key != "gates"})
    result["gates"] = checked["gates"]
    result["failure_reasons"] = [name for name, passed in checked["gates"].items() if not passed]
    result["passed"] = not result["failure_reasons"]
    result["diagnostic_state"] = "diagnostic_pass" if result["passed"] else "blocked_diagnostic"
    return result


def validate_f4_tallwall120_diagnostic_json(*args, **kwargs):
    """Named validator alias for the additive F4 JSON diagnostic consumer."""
    return evaluate_f4_tallwall120_diagnostic_json(*args, **kwargs)


def validate_material_summary(*args, **kwargs):
    """Strict summary gate used by a future qualification collector.

    The returned receipt remains explicitly diagnostic.  It is useful when a
    caller wants a failing gate to stop a qualification collector, while
    :func:`evaluate_material_summary` is preferable for negative-evidence
    audits.
    """
    result = evaluate_material_summary(*args, **kwargs)
    if not result["passed"]:
        reasons = [
            result.get("unknown_gate_reason"),
            result.get("event_window_reason"),
            result.get("cdf_gate_reason"),
        ]
        raise ValueError("material acceptance gate failed: " + "; ".join(item for item in reasons if item))
    return result


def _h5_text(value):
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8")
    return str(value)


def _coverage_audit(rows, required_source_ids, maximum_unknown_fraction):
    """Return a gate result while reserving exceptions for malformed rows."""
    maximum = _finite_number(maximum_unknown_fraction, "unknown mass limit")
    if not 0 <= maximum <= UNKNOWN_FRACTION_LIMIT:
        raise ValueError("unknown mass limit must be finite and no greater than 1%")
    try:
        return validate_source_coverage(rows, required_source_ids, maximum), None
    except ValueError as error:
        expected = [str(item) for item in required_source_ids]
        normalized, total_mass = _normalize_source_rows(rows, expected)
        # The relaxed normalization above still rejects missing, duplicate and
        # non-finite rows.  Only a source over the fixed threshold becomes a
        # negative gate result that the audit can preserve.
        coverage = {
            "all_sources_pass": False,
            "source_count": len(expected),
            "total_initial_mass_kg": total_mass,
            "maximum_source_unknown_fraction": max(row["unknown_fraction_max"] for row in normalized),
            "sources": normalized,
        }
        return coverage, str(error)


def audit_material_h5(
    output,
    *,
    required_source_ids=None,
    maximum_unknown_fraction=UNKNOWN_FRACTION_LIMIT,
    source=None,
    require_complete_window=False,
    verify_code_hashes=True,
):
    """Audit one F3/F4 trace and its checkpoint sidecar without mutation.

    This is an artifact-integrity and gate-evaluation receipt.  It reports a
    failing unknown or event gate as ``passed=False`` and keeps
    ``qualified_T2_macro=False``; malformed data or a version mismatch raises
    so a collector cannot silently accept an incomplete artifact.
    """
    import h5py

    output = Path(output)
    with h5py.File(output, "r") as handle:
        schema = _h5_text(handle.attrs.get("schema", ""))
        from scripts import core_material as material
        if schema not in (material.SCHEMA, material.F4_SCHEMA):
            raise ValueError("unsupported material H5 schema")
        binding_text = _h5_text(handle.attrs.get("binding", ""))
        binding = validate_material_binding(
            binding_text,
            expected_schema=schema,
            source=source,
            verify_code_hashes=verify_code_hashes,
        )
        try:
            result = json.loads(_h5_text(handle.attrs["result"]))
        except (KeyError, json.JSONDecodeError) as error:
            raise ValueError("material H5 is missing a valid terminal result") from error
        if result.get("qualification_claim", "none") not in ("none", None):
            raise ValueError("material H5 carries a qualification claim")
        if result.get("T2_macro", False) is True or result.get("qualified_T2_macro", False) is True:
            raise ValueError("material H5 cannot claim T2_macro")
        if "binding" in result and _canonical(result["binding"]) != _canonical(binding):
            raise ValueError("material H5 result binding disagrees with artifact binding")
        committed = handle.attrs.get("committed", -1)
        if isinstance(committed, (bool, np.bool_)) or not isinstance(committed, (int, np.integer)):
            raise ValueError("material H5 committed frame is invalid")
        committed = int(committed)
        if committed < 0:
            raise ValueError("material H5 has no committed frame")
        if not {"time", "initial_position", "weight", "source_label", "tracer_id", "position", "reliable"} <= set(handle):
            raise ValueError("material H5 is missing required datasets")
        times = np.asarray(handle["time"], dtype=np.float64)
        if len(times) != committed + 1 or len(times) < 1 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise ValueError("material H5 time prefix is incomplete or non-monotone")
        initial = np.asarray(handle["initial_position"], dtype=np.float64)
        weight = np.asarray(handle["weight"], dtype=np.float64)
        if initial.ndim != 2 or initial.shape[1:] != (3,) or not np.isfinite(initial).all():
            raise ValueError("material H5 initial_position has an invalid shape or value")
        count = len(initial)
        if weight.shape != (count,) or not np.isfinite(weight).all() or np.any(weight < 0) or not weight.sum() > 0:
            raise ValueError("material H5 weight denominator is invalid")
        if schema == material.F4_SCHEMA:
            definition = binding.get("f4_definition")
            if not isinstance(definition, dict) or "q" not in definition:
                raise ValueError("F4 material binding has no source definition")
            expected_memberships = {
                "source_membership": material.f4_source_membership(initial, definition["q"]),
                "destination_membership": material.f4_destination_membership(initial),
            }
            for name, expected in expected_memberships.items():
                if name not in handle:
                    raise ValueError("F4 material H5 is missing " + name)
                actual = np.asarray(handle[name][:])
                if actual.shape != (count,) or actual.dtype.kind != "b":
                    raise ValueError("F4 material H5 " + name + " has an invalid shape or dtype")
                if not np.array_equal(actual, expected):
                    raise ValueError("F4 material H5 " + name + " disagrees with bound geometry")
        labels = handle["source_label"].asstr()[:] if handle["source_label"].dtype.kind in "OSU" else np.asarray(handle["source_label"][:])
        labels = np.asarray([str(item) for item in labels])
        if labels.shape != (count,):
            raise ValueError("material H5 source labels have an invalid shape")
        tracer_ids = np.asarray(handle["tracer_id"].asstr()[:])
        if tracer_ids.shape != (count,) or len(set(tracer_ids.tolist())) != count:
            raise ValueError("material H5 tracer identity is incomplete or duplicated")
        position = np.asarray(handle["position"], dtype=np.float64)
        reliable = np.asarray(handle["reliable"], dtype=bool)
        if position.shape != (len(times), count, 3) or reliable.shape != (len(times), count):
            raise ValueError("material H5 history axes do not match seed metadata")
        if np.any(reliable[1:] & ~reliable[:-1]):
            raise ValueError("material H5 reliability recovered after an unknown state")
        active = reliable[committed]
        if not np.isfinite(position[committed][active]).all():
            raise ValueError("material H5 has non-finite active terminal positions")
        history_fields = material.HISTORY_FIELDS if schema == material.SCHEMA else material.F4_HISTORY_FIELDS
        for name in history_fields:
            if name not in handle or handle[name].shape[0] != len(times):
                raise ValueError("material H5 history is missing or has a mismatched field: " + name)
        expected_sources = (
            [str(item) for item in required_source_ids]
            if required_source_ids is not None
            else sorted(set(labels.tolist()))
        )
        observed_sources = set(labels.tolist())
        if observed_sources != set(expected_sources):
            raise ValueError("material H5 source labels do not match declared source coverage")
        source_rows = []
        mass_closed = True
        for source_id in expected_sources:
            select = labels == str(source_id)
            source_mass = float(weight[select].sum())
            if source_mass <= 0:
                raise ValueError("material H5 source has no positive mass: " + str(source_id))
            unknown = float(weight[select & ~active].sum() / source_mass)
            if schema == material.SCHEMA:
                terminal_a = float(weight[select & active & (position[committed, :, 0] < 0.0)].sum() / source_mass)
                terminal_b = float(weight[select & active & (position[committed, :, 0] >= 0.0)].sum() / source_mass)
            else:
                destination = material.f4_destination_membership(position[committed])
                terminal_a = float(weight[select & active & destination].sum() / source_mass)
                terminal_b = float(weight[select & active & ~destination].sum() / source_mass)
            mass_closed = mass_closed and abs(terminal_a + terminal_b + unknown - 1.0) <= 1e-12
            source_rows.append({
                "source_id": str(source_id),
                "initial_mass_kg": source_mass,
                "unknown_fraction_max": unknown,
            })
        coverage, coverage_reason = _coverage_audit(source_rows, expected_sources, maximum_unknown_fraction)
        checkpoint_schema = material.CHECKPOINT_SCHEMA if schema == material.SCHEMA else material.F4_CHECKPOINT_SCHEMA
        checkpoint = validate_checkpoint_manifest(
            output,
            binding=binding_text,
            expected_schema=checkpoint_schema,
            expected_committed=committed,
        )
        for name in checkpoint["fields"]:
            if not np.array_equal(checkpoint["state"][name], handle[name][committed], equal_nan=True):
                raise ValueError("material checkpoint state disagrees with committed H5 frame: " + name)
        event_pass = True
        event_reason = None
        if require_complete_window:
            event_pass = result.get("event_window_complete") is True and result.get("event_window_status") == "complete"
            if not event_pass:
                event_reason = "material event window is incomplete or right-censored"
        return {
            "schema": ACCEPTANCE_SCHEMA,
            "status": "diagnostic_only",
            "artifact_sha256": _digest(output),
            "trace_schema": schema,
            "committed_frame": committed,
            "frame_count": len(times),
            "source_coverage": coverage,
            "source_coverage_reason": coverage_reason,
            "mass_closed": bool(mass_closed),
            "event_window_pass": bool(event_pass),
            "event_window_reason": event_reason,
            "passed": bool(coverage["all_sources_pass"] and mass_closed and event_pass),
            "qualification_claim": "none",
            "T2_macro": False,
            "T2_path": False,
            "qualified_T2_macro": False,
            "qualified_T2_path": False,
            "checkpoint": {
                "schema": checkpoint["checkpoint_schema"],
                "committed": checkpoint["committed"],
                "state_sha256": checkpoint["state_sha256"],
            },
            "binding": {
                "schema": binding["schema"],
                "backend": binding["backend"],
                "neighbour_variant": binding["neighbour_variant"],
                "code_sha256": binding["code_sha256"],
                "source_sha256": binding["source_sha256"],
            },
        }
