#!/usr/bin/env python3
"""Collect the F4 tall-wall production products at the public Core boundary.

The tall-wall production design is a fixed 32-case registration.  This module
joins that registration to hash-bound prepared inputs and per-case CFD audit
products without touching the scheduler, a ledger, or an in-flight HDF5.  A
case with no terminal audit remains in the denominator and a scientific audit
failure remains a failed case; neither is silently dropped from the report.

The collector emits a diagnostic ``core.dataset.v1`` reader manifest whenever
there are hash-checked trajectory products.  It only marks that manifest as a
formal release when the caller requests release *and* all 32 registered cases
have complete, passing production audits.  Qualification artifacts are
recorded as an admission binding and are never copied into the reader cases.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

# Keep direct CLI execution equivalent to ``python -m`` from the lab root.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts.core_cfd_dataset import known_inputs_from_cfd_config
from scripts.core_contract import contract_hash
from scripts.core_dataset import SCHEMA as DATASET_SCHEMA
from scripts.core_dataset import sha256_file, validate_manifest


SCHEMA = "core.f4.tallwall120.production_collection.v1"
ASSEMBLY_SCHEMA = "core.multifamily.dataset_collection.v1"
PRODUCTION_DESIGN_SCHEMA = "core.production_design.v1"
PRODUCTION_BATCH_SCHEMA = "core.f4.tallwall120.production_batch.v1"
LEGACY_QUALIFICATION_RECEIPT_SCHEMA = "core.f4.tallwall120.production_qualification_binding.v1"
FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
HEIGHT_M = 1.2
EXPECTED_CASE_COUNT = 32
EXPECTED_SPLITS = {"train": 16, "validation": 4, "id_test": 6, "ood_test": 6}


class CollectionError(ValueError):
    """Raised when an immutable production binding is inconsistent."""


def _require_qualification_receipt_schema(payload: Mapping[str, Any]) -> None:
    schema = payload.get("schema")
    if type(schema) is not str or schema != LEGACY_QUALIFICATION_RECEIPT_SCHEMA:
        raise CollectionError("qualification receipt schema mismatch")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_json(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectionError(f"{role} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CollectionError(f"{role} must be a JSON object: {path}")
    return value


def _resolve_path(value: Any, root: Path, parent: Path | None, role: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise CollectionError(f"{role} has no path")
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (parent / candidate).resolve() if parent is not None else (root / candidate).resolve()
        if not target.exists():
            target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise CollectionError(f"{role} escapes data_root: {value}") from exc
    return target


def _ref(path: Path, root: Path, *, role: str, declared: Any = None,
         require_declared: bool = False) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise CollectionError(f"{role} is missing: {path}")
    observed = sha256_file(path)
    if declared is not None:
        if not isinstance(declared, str) or len(declared) != 64:
            raise CollectionError(f"{role} has a malformed SHA-256 declaration")
        if observed.lower() != declared.lower():
            raise CollectionError(f"{role} SHA-256 mismatch: {path}")
    elif require_declared:
        raise CollectionError(f"{role} requires a declared SHA-256")
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CollectionError(f"{role} is outside data_root: {path}") from exc
    return {"path": relative, "sha256": observed, "bytes": path.stat().st_size,
            "role": role}


def _load_json_ref(value: Any, root: Path, *, parent: Path | None, role: str,
                   declared: Any = None, require_declared: bool = False) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Load a JSON path or inline object and return payload, binding, file flag."""
    if isinstance(value, Mapping) and value.get("path") is None:
        payload = copy.deepcopy(dict(value))
        return payload, {"path": "<inline>", "sha256": canonical_sha256(payload),
                         "role": role}, False
    if isinstance(value, Mapping):
        path_value = value.get("path")
        expected = value.get("sha256", declared)
    else:
        path_value = value
        expected = declared
    target = _resolve_path(path_value, root, parent, role)
    binding = _ref(target, root, role=role, declared=expected,
                   require_declared=require_declared)
    payload = _read_json(target, role)
    # A few frozen scheduler specs bind large JSON designs by their canonical
    # serialization rather than by the raw pretty-printed file bytes.  Keep
    # both digests explicit; either may be compared only where the producer
    # declared that representation.
    binding["canonical_sha256"] = canonical_sha256(payload)
    return payload, binding, True


def _marker(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _qualification_marker(value: Mapping[str, Any]) -> bool:
    if value.get("qualification_only") is True or value.get("qualification_case") is True:
        return True
    if str(value.get("split", "")).lower() in {"qualification", "qualification_only"}:
        return True
    if str(value.get("stage", "")).lower() in {
        "qualification", "qualification_only", "canary", "repair_canary",
        "calibration", "diagnostic", "repair", "qualification_canary",
    }:
        return True
    claim = value.get("qualification_claim")
    return claim not in (None, "", "none", False)


def _product_rows(products: Any) -> list[Mapping[str, Any]]:
    if products is None:
        return []
    if isinstance(products, list):
        rows = products
    elif isinstance(products, Mapping):
        rows = products.get("cases", products.get("products", products.get("rows")))
    else:
        rows = None
    if not isinstance(rows, list):
        raise CollectionError("case product index requires a cases/products/rows list")
    if not all(isinstance(row, Mapping) for row in rows):
        raise CollectionError("case product index contains a non-object row")
    return rows


def _find_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _as_path_ref(value: Any, *, path_key: str, hash_key: str | None = None) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    return {"path": value, **({"sha256": hash_key} if hash_key is not None else {})}


def _validate_qualification(payload: Mapping[str, Any], *, formal: bool = False) -> dict[str, Any]:
    """Validate the qualification admission and, for formal release, re-run
    the authoritative connector evidence contract.

    A qualification tick is itself a useful diagnostic binding, but its
    summary booleans are not an authority boundary: a caller could rewrite
    the JSON and update the batch hash.  Formal promotion therefore requires
    the connector's evaluator receipt to be revalidated against the actual
    evaluator manifest and its receipt-linked artifacts.  The expensive H5
    verification is deliberately deferred until a formal release is actually
    requested; partial collection/reader construction remains lightweight and
    cannot become formal.
    """
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
    if not isinstance(summary, Mapping):
        raise CollectionError("qualification binding has no summary")
    for key in ("matrix_complete", "T1_numerical"):
        if summary.get(key) is not True:
            raise CollectionError(f"qualification binding does not pass {key}")
    binding = summary.get("binding")
    if binding is None:
        binding = payload.get("binding")
    if not isinstance(binding, Mapping) or binding.get("verified") is not True:
        raise CollectionError("qualification binding is not verified")
    if binding.get("artifact_bindings_verified") is not True:
        raise CollectionError("qualification artifact bindings are not verified")

    evidence_verified = False
    evidence_contract = {
        "authoritative_verifier": "deferred",
        "manifest_sha256": binding.get("manifest_sha256"),
        "reevaluation_sha256": binding.get("reevaluation_sha256"),
    }
    if formal:
        # Import lazily so a diagnostic collection does not initialize the
        # qualification verifier or touch its multi-gigabyte trajectories.
        from scripts import f4_tallwall120_production_connector as connector

        evaluation = payload.get("result")
        if not isinstance(evaluation, Mapping):
            raise CollectionError(
                "formal qualification requires the evaluator result, not summary booleans"
            )

        # Check the small, self-consistent declarations before invoking the
        # verifier.  This rejects a forged result plus rehashed qualification
        # and batch immediately, without rescanning qualification H5 files.
        for key in ("matrix_complete", "T1_numerical"):
            if evaluation.get(key) is not summary.get(key):
                raise CollectionError(
                    f"qualification evaluator {key} differs from the bound summary"
                )
            if evaluation.get(key) is not binding.get(key):
                raise CollectionError(
                    f"qualification evaluator {key} differs from the bound tick"
                )
        if evaluation.get("schema") != "core.f4.tallwall120.qualification_evaluation.v2":
            raise CollectionError("formal qualification evaluator result schema is unsupported")
        if evaluation.get("scope_id") != SCOPE_ID:
            raise CollectionError("formal qualification evaluator scope differs from F4 tallwall120")
        if binding.get("schema") != connector.QUALIFICATION_BINDING_SCHEMA:
            raise CollectionError("formal qualification binding schema is unsupported")
        manifest_value = binding.get("manifest_path")
        manifest_sha = binding.get("manifest_sha256")
        if not isinstance(manifest_value, str) or not isinstance(manifest_sha, str) or len(manifest_sha) != 64:
            raise CollectionError("formal qualification lacks a hash-bound evaluator manifest")
        manifest_path = Path(manifest_value).expanduser().resolve()
        if not manifest_path.is_file():
            raise CollectionError(f"formal qualification evaluator manifest is missing: {manifest_path}")
        observed_manifest_sha = connector.digest(manifest_path)
        if observed_manifest_sha != manifest_sha:
            raise CollectionError("formal qualification evaluator manifest hash mismatch")
        if evaluation.get("static_manifest_sha256") != observed_manifest_sha:
            raise CollectionError("formal qualification result is not bound to the evaluator manifest")
        reevaluation_sha = binding.get("reevaluation_sha256")
        if not isinstance(reevaluation_sha, str) or len(reevaluation_sha) != 64:
            raise CollectionError("formal qualification lacks a reevaluation hash")
        if connector.canonical_digest(evaluation) != reevaluation_sha:
            raise CollectionError("formal qualification reevaluation hash does not bind result")
        checked = connector.validate_evaluation(evaluation, manifest_path)
        if checked.get("matrix_complete") is not True or checked.get("T1_numerical") is not True:
            raise CollectionError("authoritative qualification evidence does not pass matrix/T1")
        if checked.get("artifact_bindings_verified") is not True or checked.get("binding_ready") is not True:
            raise CollectionError("authoritative qualification artifact bindings are not verified")
        if checked.get("missing") or checked.get("failures"):
            raise CollectionError("authoritative qualification evidence has missing cells or failures")
        if checked.get("cell_indices") != list(range(15)):
            raise CollectionError("authoritative qualification evidence does not cover all 15 cells")
        declared_checks = binding.get("checks")
        if not isinstance(declared_checks, Mapping) or any(value is not True for value in declared_checks.values()):
            raise CollectionError("formal qualification tick checks are not all true")
        if checked.get("checks") != {key: value is True for key, value in declared_checks.items()}:
            raise CollectionError("formal qualification tick checks differ from authoritative evidence")
        evidence_verified = True
        evidence_contract = {
            "authoritative_verifier": "f4_tallwall120_production_connector.validate_evaluation",
            "manifest_path": str(manifest_path),
            "manifest_sha256": observed_manifest_sha,
            "reevaluation_sha256": reevaluation_sha,
            "cell_count": checked.get("cell_count"),
            "cell_indices": checked.get("cell_indices"),
            "artifact_bindings_verified": True,
            "binding_ready": True,
        }
    return {
        "family": summary.get("family", binding.get("family", FAMILY)),
        "scope_id": summary.get("scope_id", binding.get("scope_id", SCOPE_ID)),
        "matrix_complete": True,
        "T1_numerical": True,
        "promotion_status": summary.get("promotion_status"),
        "evidence_verified": evidence_verified,
        "evidence_contract": evidence_contract,
    }


def _validate_design(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if payload.get("schema") != PRODUCTION_DESIGN_SCHEMA:
        raise CollectionError("production design schema is not core.production_design.v1")
    if payload.get("family") != FAMILY or payload.get("scope_id") != SCOPE_ID:
        raise CollectionError("production design family/scope identity mismatch")
    if payload.get("case_count") != EXPECTED_CASE_COUNT:
        raise CollectionError("production design denominator is not 32")
    rows = payload.get("cases")
    if not isinstance(rows, list) or len(rows) != EXPECTED_CASE_COUNT:
        raise CollectionError("production design does not contain 32 cases")
    by_index: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or isinstance(row.get("index"), bool):
            raise CollectionError("production design contains a malformed case")
        index = row.get("index")
        if not isinstance(index, int) or index in by_index:
            raise CollectionError("production design indices are not unique")
        if not 0 <= index < EXPECTED_CASE_COUNT:
            raise CollectionError("production design index is outside 0..31")
        if row.get("family") != FAMILY or row.get("qualification_only") is not False:
            raise CollectionError(f"production design case {index} is not a production F4 case")
        if row.get("stage") != "production" or row.get("qualification_inheritance") is not False:
            raise CollectionError(f"production design case {index} has a qualification stage/inheritance")
        if row.get("container_height_m") != HEIGHT_M:
            raise CollectionError(f"production design case {index} is not the 1.2 m wall")
        split = row.get("split")
        if split not in EXPECTED_SPLITS:
            raise CollectionError(f"production design case {index} has an invalid split")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise CollectionError(f"production design case {index} has no case_id")
        by_index[index] = dict(row)
    if sorted(by_index) != list(range(EXPECTED_CASE_COUNT)):
        raise CollectionError("production design indices do not cover 0..31")
    counts = Counter(row["split"] for row in by_index.values())
    if dict(counts) != EXPECTED_SPLITS:
        raise CollectionError(f"production design split counts changed: {dict(counts)}")
    # The connector owns the complete fixed scalar registration.  Importing it
    # here keeps this collector from duplicating its 32-point identity rules.
    try:
        from scripts.f4_tallwall120_production_connector import validate_production_design
        validate_production_design(payload)
    except Exception as exc:  # connector has its own versioned error type
        if isinstance(exc, CollectionError):
            raise
        raise CollectionError(f"production design fixed registration rejected: {exc}") from exc
    return [by_index[index] for index in range(EXPECTED_CASE_COUNT)], {
        "case_count": EXPECTED_CASE_COUNT,
        "split_counts": dict(sorted(counts.items())),
        "scope_id": SCOPE_ID,
        "height_m": HEIGHT_M,
        "revision_id": payload.get("revision_id"),
    }


def _validate_batch(payload: Mapping[str, Any], *, design_ref: Mapping[str, Any],
                    qualification_ref: Mapping[str, Any], design_rows: Sequence[Mapping[str, Any]],
                    root: Path, parent: Path | None,
                    batch_ref: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    if payload.get("schema") != PRODUCTION_BATCH_SCHEMA:
        raise CollectionError("production batch schema is not tallwall120 v1")
    if payload.get("registered_denominator") != EXPECTED_CASE_COUNT:
        raise CollectionError("production batch denominator is not 32")
    if payload.get("production_design_sha256") not in {
        design_ref.get("sha256"), design_ref.get("canonical_sha256")
    }:
        raise CollectionError("production batch is not bound to this production design")
    if payload.get("qualification_receipt_sha256") != qualification_ref.get("sha256"):
        raise CollectionError("production batch is not bound to this qualification receipt")
    rows = payload.get("prepared", [])
    if not isinstance(rows, list):
        raise CollectionError("production batch prepared entries are not a list")
    result: dict[int, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, Mapping) or isinstance(item.get("index"), bool):
            raise CollectionError("production batch contains a malformed prepared entry")
        index = item.get("index")
        if not isinstance(index, int) or index in result or not 0 <= index < EXPECTED_CASE_COUNT:
            raise CollectionError("production batch prepared index is invalid or duplicated")
        expected = design_rows[index]
        if item.get("case_id") != expected.get("case_id"):
            raise CollectionError(f"prepared entry {index} case identity differs from design")
        prepared_value = _find_value(item, "prepared", "prepared_path", "prepared_json")
        if prepared_value is None:
            raise CollectionError(f"prepared entry {index} has no prepared path")
        prepared_value = _as_path_ref(
            prepared_value, path_key="prepared",
            hash_key=item.get("prepared_sha256"))
        prepared, ref, is_file = _load_json_ref(
            prepared_value, root, parent=parent, role=f"case {index} prepared",
            require_declared=True)
        if not is_file:
            raise CollectionError(f"case {index} prepared binding must be a file")
        result[index] = {"payload": prepared, "ref": ref, "batch_ref": dict(batch_ref)}
    return result


def _config_from_prepared(prepared: Mapping[str, Any]) -> Mapping[str, Any]:
    config = prepared.get("config", prepared)
    if not isinstance(config, Mapping):
        raise CollectionError("prepared record has no config mapping")
    return config


def _validate_prepared(index: int, design: Mapping[str, Any], prepared: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, str]:
    config = _config_from_prepared(prepared)
    checks = {
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "case_id": design["case_id"],
        "stage": "production",
        "qualification_claim": "none",
        "qualification_only": False,
        "qualification_inheritance": False,
        "container_height_m": HEIGHT_M,
    }
    for key, expected in checks.items():
        if config.get(key) != expected:
            raise CollectionError(f"case {index} prepared {key} mismatch")
    if config.get("split") != design.get("split"):
        raise CollectionError(f"case {index} prepared split differs from fixed design split")
    bounds = config.get("wall_bounds")
    if not isinstance(bounds, Mapping) or bounds.get("zmax") != HEIGHT_M:
        raise CollectionError(f"case {index} prepared wall height is not 1.2 m")
    physical = config.get("physical_case_id")
    lineage = config.get("lineage_group_id")
    if not isinstance(physical, str) or not physical or not isinstance(lineage, str) or not lineage:
        raise CollectionError(f"case {index} prepared record lacks explicit physical/lineage identity")
    if config.get("physical_geometry_changed") is not True:
        raise CollectionError(f"case {index} does not bind the changed tall-wall geometry")
    return config, physical, lineage


def _load_optional_ref(row: Mapping[str, Any], root: Path, parent: Path | None,
                       *, names: Sequence[str], role: str,
                       require_declared: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    value = _find_value(row, *names)
    if value is None:
        return None, None, False
    payload, ref, is_file = _load_json_ref(value, root, parent=parent, role=role,
                                           require_declared=require_declared)
    return payload, ref, is_file


def _validate_execution_receipt(execution: Mapping[str, Any], refs: Mapping[str, Mapping[str, Any]],
                                index: int) -> None:
    if execution.get("schema") not in {"core.verified_archive.v1", "core.execution_receipt.v1"}:
        raise CollectionError(f"case {index} execution receipt schema is unsupported")
    if execution.get("execution_status") != "succeeded":
        raise CollectionError(f"case {index} execution receipt is not succeeded")
    outputs = execution.get("outputs")
    if not isinstance(outputs, list):
        raise CollectionError(f"case {index} execution receipt has no output index")
    by_path = {
        str(item.get("path")): item.get("sha256")
        for item in outputs if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    for name, ref in refs.items():
        expected = ref.get("sha256")
        basename = Path(ref["path"]).name
        candidates = {name, f"product/{basename}", basename}
        if not any(by_path.get(candidate) == expected for candidate in candidates):
            raise CollectionError(f"case {index} execution receipt does not bind {basename}")


def _load_products(products: Any, root: Path, source_parent: Path | None) -> tuple[list[Mapping[str, Any]], Path | None]:
    if products is None:
        return [], source_parent
    if isinstance(products, (str, Path)):
        target = _resolve_path(products, root, source_parent, "case product index")
        payload = _read_json(target, "case product index")
        return _product_rows(payload), target.parent
    else:
        payload = products
    return _product_rows(payload), source_parent


def _trajectory_ref(row: Mapping[str, Any], result: Mapping[str, Any] | None,
                    audit: Mapping[str, Any] | None, root: Path, parent: Path | None,
                    index: int, *, hash_file: bool = True) -> tuple[dict[str, Any] | None, bool]:
    value = _find_value(row, "trajectory", "trajectory_h5", "hdf5",
                        "trajectory_artifact", "hdf5_artifact")
    if value is None and isinstance(result, Mapping):
        conversion = result.get("conversion")
        if isinstance(conversion, Mapping):
            value = {"path": conversion.get("hdf5"), "sha256": conversion.get("sha256")}
    if value is None and isinstance(audit, Mapping):
        conversion = audit.get("conversion")
        if isinstance(conversion, Mapping):
            value = {"path": conversion.get("hdf5"), "sha256": conversion.get("sha256")}
    if value is None:
        return None, False
    if isinstance(value, Mapping) and value.get("path") is None:
        raise CollectionError(f"case {index} trajectory binding has no path")
    if isinstance(value, Mapping):
        path_value, declared = value.get("path"), value.get("sha256")
    else:
        path_value, declared = value, None
    target = _resolve_path(path_value, root, parent, f"case {index} trajectory")
    if hash_file:
        return _ref(target, root, role=f"case {index} trajectory", declared=declared,
                    require_declared=True), True
    if not isinstance(declared, str) or len(declared) != 64:
        raise CollectionError(f"case {index} trajectory requires a declared SHA-256")
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise CollectionError(f"case {index} trajectory is outside data_root") from exc
    # The authoritative connector performs the single physical HDF5 hash for
    # a formal candidate.  Retain the declared digest here so diagnostic
    # metadata remains portable without reading the file twice.
    return {"path": relative, "sha256": declared, "bytes": target.stat().st_size,
            "role": f"case {index} trajectory"}, True


def _absolute_ref(ref: Mapping[str, Any], root: Path, role: str) -> dict[str, Any]:
    """Convert a collector-relative artifact reference for the connector."""
    target = _resolve_path(ref.get("path"), root, None, role)
    return {"path": str(target), "sha256": ref.get("sha256")}


def _relative_authoritative_ref(ref: Mapping[str, Any], root: Path, role: str) -> dict[str, Any]:
    """Convert a connector absolute reference back to the portable report."""
    path_value = ref.get("path")
    expected = ref.get("sha256")
    if not isinstance(path_value, str) or not isinstance(expected, str) or len(expected) != 64:
        raise CollectionError(f"authoritative {role} binding is malformed")
    target = Path(path_value).expanduser().resolve()
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise CollectionError(f"authoritative {role} escapes data_root: {target}") from exc
    return {"path": relative, "sha256": expected, "bytes": target.stat().st_size,
            "role": role}


def _verify_authoritative_production_case(
    *, index: int, design: Mapping[str, Any], audit_ref: Mapping[str, Any],
    result_ref: Mapping[str, Any], observations_ref: Mapping[str, Any],
    trajectory_ref: Mapping[str, Any], execution_ref: Mapping[str, Any],
    audit: Mapping[str, Any], root: Path, execution_complete: bool,
    full_particle_axis: bool,
) -> dict[str, dict[str, Any]]:
    """Run the connector's complete receipt-linked production audit once.

    This is called only for a formal candidate whose three scientific gates
    and metadata completion flags already pass.  The trajectory reference is
    therefore handed to the authoritative verifier before the collector
    computes an HDF5 digest of its own; the verifier's returned references are
    reused in the final report.
    """
    from scripts import f4_tallwall120_production_connector as connector

    case_id = design["case_id"]
    receipt = {
        "schema": "core.case_audit.v1",
        "case_id": case_id,
        "audit_artifact": _absolute_ref(audit_ref, root, f"case {index} audit"),
        "result_artifact": _absolute_ref(result_ref, root, f"case {index} result"),
        "observations_artifact": _absolute_ref(
            observations_ref, root, f"case {index} observations"),
        "trajectory_artifact": _absolute_ref(
            trajectory_ref, root, f"case {index} trajectory"),
        "execution_receipt": _absolute_ref(
            execution_ref, root, f"case {index} execution receipt"),
        "full_temporal_scan": execution_complete,
        "full_particle_axis": full_particle_axis,
        "hard_integrity_pass": audit.get("hard_integrity_pass") is True,
        "source_mass_gate_pass": audit.get("source_mass_gate_pass") is True,
        "event_window_complete": audit.get("event_window_complete") is True,
    }
    try:
        verified = connector.verify_bound_audits(
            {"cases": [dict(design)]}, {case_id: receipt})
    except Exception as exc:
        raise CollectionError(
            f"case {index} failed authoritative production audit verification: {exc}"
        ) from exc
    return verified[case_id]["artifacts"]


def _case_record(index: int, design: Mapping[str, Any], prepared_entry: Mapping[str, Any] | None,
                 product: Mapping[str, Any] | None, *, root: Path, source_parent: Path | None,
                 qualification_ref: Mapping[str, Any], design_ref: Mapping[str, Any],
                 batch_ref: Mapping[str, Any], strict_audit: bool = False
                 ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    case_id = design["case_id"]
    product = product or {}
    base = {
        "index": index, "case_id": case_id, "family": FAMILY,
        "split": design["split"], "physical_case_id": None,
        "lineage_group_id": None, "denominator_included": True,
        "qualification_only": False, "status": "not_prepared" if prepared_entry is None else "prepared_pending",
        "execution_complete": False, "scientific_status": "unknown",
        "failure_category": None, "reader_eligible": False,
        "authoritative_audit_verified": False,
        "reasons": [],
    }
    # A qualification product is visible in the accounting report but never
    # gets a production design slot or a reader row.
    if _qualification_marker(product):
        base.update(status="excluded_qualification", denominator_included=False,
                    qualification_only=True,
                    reasons=["qualification_only product excluded from production denominator"])
        return base, None
    if product.get("case_id", case_id) != case_id:
        base.update(status="invalid", reasons=["product case identity differs from design"])
        return base, None
    if product.get("split") is not None and product.get("split") != design["split"]:
        base.update(status="invalid", reasons=["product split differs from fixed design split"])
        return base, None
    if prepared_entry is None:
        if str(product.get("status", "")).lower() in {"failed", "error"}:
            base.update(status="failed", failure_category=product.get("failure_category", "execution_failed"),
                        reasons=["execution failed before a prepared production input was bound"])
        return base, None
    try:
        prepared = prepared_entry["payload"]
        config, physical, lineage = _validate_prepared(index, design, prepared)
        base.update(physical_case_id=physical, lineage_group_id=lineage)
    except CollectionError as exc:
        base.update(status="invalid", reasons=[str(exc)])
        return base, None

    audit, audit_ref, audit_file = _load_optional_ref(
        product, root, source_parent,
        names=("audit", "audit_artifact", "audit_path"), role=f"case {index} audit",
        require_declared=True)
    result, result_ref, _ = _load_optional_ref(
        product, root, source_parent,
        names=("result", "result_artifact", "result_path"), role=f"case {index} result",
        require_declared=True)
    observations, observations_ref, _ = _load_optional_ref(
        product, root, source_parent,
        names=("observations", "observations_artifact", "observations_path"),
        role=f"case {index} observations", require_declared=True)
    execution, execution_ref, _ = _load_optional_ref(
        product, root, source_parent,
        names=("execution", "execution_receipt", "archive_receipt", "native_execution_receipt"),
        role=f"case {index} execution receipt", require_declared=True)
    if audit is None:
        base.update(status="pending_audit", reasons=["no hash-bound per-case audit is available"])
        return base, None
    if audit.get("case_id") != case_id:
        base.update(status="invalid", reasons=["audit case identity differs from design"])
        return base, None
    execution_bound = execution is not None
    execution_complete = _marker(audit, "execution_complete", "requested_horizon_reached")
    if execution_complete is None and isinstance(audit.get("structural"), Mapping):
        execution_complete = audit["structural"].get("full_temporal_scan")
    if not isinstance(execution_complete, bool):
        execution_complete = False
    hard = audit.get("hard_integrity_pass")
    mass = audit.get("source_mass_gate_pass")
    event = audit.get("event_window_complete")
    explicit_scientific = (hard is True and mass is True and event is True)
    if not all(isinstance(value, bool) for value in (hard, mass, event)):
        scientific_status = "unknown"
    else:
        scientific_status = "passed" if explicit_scientific else "failed"
    failure = product.get("failure_category")
    if failure is None and not execution_complete:
        failure = "incomplete_execution"
    if failure is None and scientific_status == "failed":
        if hard is not True:
            failure = "hard_integrity"
        elif mass is not True:
            failure = "source_mass_gate"
        elif event is not True:
            failure = "event_window_incomplete"
        else:
            failure = "scientific_audit_failed"
    structural = audit.get("structural")
    full_axis = audit.get("full_particle_axis")
    if isinstance(structural, Mapping):
        full_axis = structural.get("full_scan", structural.get("full_particle_axis", full_axis))
    strict_candidate = bool(
        strict_audit and execution_complete and explicit_scientific
        and full_axis is True and execution is not None
        and audit_ref is not None and result_ref is not None
        and observations_ref is not None
    )
    trajectory, trajectory_file = _trajectory_ref(
        product, result, audit, root, source_parent, index,
        hash_file=not strict_candidate)
    if trajectory is None:
        base.update(status="failed" if not execution_complete else "incomplete_product",
                    execution_complete=execution_complete, scientific_status=scientific_status,
                    failure_category=failure or "missing_trajectory",
                    reasons=["per-case audit is present but no hash-bound trajectory is available"])
        return base, None
    authoritative_artifacts = None
    if strict_candidate:
        try:
            authoritative_artifacts = _verify_authoritative_production_case(
                index=index, design=design, audit_ref=audit_ref, result_ref=result_ref,
                observations_ref=observations_ref, trajectory_ref=trajectory,
                execution_ref=execution_ref, audit=audit, root=root,
                execution_complete=execution_complete, full_particle_axis=bool(full_axis))
        except CollectionError as exc:
            base.update(status="invalid", reader_eligible=False,
                        execution_complete=execution_complete,
                        scientific_status=scientific_status,
                        failure_category="authoritative_audit_rejected",
                        reasons=[str(exc)])
            return base, None
        # Reuse the verifier's already hashed artifact references.  This keeps
        # formal promotion from hashing a multi-gigabyte trajectory twice.
        audit_ref = _relative_authoritative_ref(
            authoritative_artifacts["audit"], root, f"case {index} audit")
        result_ref = _relative_authoritative_ref(
            authoritative_artifacts["result"], root, f"case {index} result")
        observations_ref = _relative_authoritative_ref(
            authoritative_artifacts["observations"], root, f"case {index} observations")
        trajectory = _relative_authoritative_ref(
            authoritative_artifacts["trajectory"], root, f"case {index} trajectory")
        execution_ref = _relative_authoritative_ref(
            authoritative_artifacts["execution_receipt"], root,
            f"case {index} execution receipt")
        base["authoritative_audit_verified"] = True

    if execution is not None:
        try:
            execution_refs = {"audit": audit_ref, "trajectory": trajectory}
            if result_ref is not None:
                execution_refs["result"] = result_ref
            if observations_ref is not None:
                execution_refs["observations"] = observations_ref
            _validate_execution_receipt(execution, execution_refs, index)
        except CollectionError as exc:
            base.update(status="invalid", reader_eligible=False,
                        reasons=[str(exc)])
            return base, None
    # Audit evidence must explicitly cover a full particle axis before the
    # product is exposed to the reader.  This check is metadata-only; the
    # public Core reader performs its own HDF5 shape checks on first access.
    full_axis = audit.get("full_particle_axis")
    if isinstance(structural, Mapping):
        full_axis = structural.get("full_scan", structural.get("full_particle_axis", full_axis))
    if full_axis is not True:
        base.update(status="failed" if not execution_complete else "incomplete_product",
                    execution_complete=execution_complete, scientific_status=scientific_status,
                    failure_category=failure or "audit_missing_full_particle_axis",
                    reasons=["audit does not bind a full particle-axis scan"])
        return base, None
    status = "completed" if execution_complete and explicit_scientific else "failed"
    base.update(status=status, execution_complete=execution_complete,
                scientific_status=scientific_status, failure_category=failure,
                reader_eligible=bool(execution_complete),
                execution_receipt_bound=execution_bound,
                trajectory=trajectory, audit=audit_ref, result=result_ref,
                observations=observations_ref, execution=execution_ref,
                prepared=prepared_entry["ref"])
    try:
        known = known_inputs_from_cfd_config(
            config, family=FAMILY, scope_id=config.get("scope_id"),
            data_root=root, source_parent=source_parent)
    except Exception as exc:
        base.update(status="invalid", reader_eligible=False,
                    reasons=[f"public known-input construction failed: {exc}"])
        return base, None
    reader = {
        "case_id": case_id,
        "physical_case_id": physical,
        "lineage_group_id": lineage,
        "family": FAMILY,
        "split": design["split"],
        "scope_id": config["scope_id"],
        "hdf5": trajectory["path"],
        "sha256": trajectory["sha256"],
        "bytes": trajectory["bytes"],
        "known_inputs": known.as_dict(),
        "known_inputs_sha256": contract_hash(known),
        "qualification_case": False,
        "evaluation_role": "production" if explicit_scientific else "production_failed",
        "production_status": status,
        "scientific_status": scientific_status,
        "failure_category": failure,
        "provenance": {
            "source_schema": SCHEMA,
            "production_index": index,
            "production_design": design_ref,
            "batch_manifest": batch_ref,
            "qualification": qualification_ref,
            "prepared": prepared_entry["ref"],
            "audit": audit_ref,
            "result": result_ref,
            "observations": observations_ref,
            "execution": execution_ref,
            "stage": "production",
            "qualification_only": False,
        },
    }
    return base, reader


def _manifest_with_cases(cases: list[dict[str, Any]], *, dataset_id: str,
                         source_sha: str, formal_release: bool) -> dict[str, Any] | None:
    if not cases:
        return None
    payload = {
        "schema": DATASET_SCHEMA,
        "dataset_id": dataset_id,
        "formal_release": bool(formal_release),
        "source_schema": SCHEMA,
        "source_manifest_sha256": source_sha,
        "cases": cases,
    }
    try:
        validate_manifest(payload)
    except ValueError as exc:
        raise CollectionError(f"reader manifest physical/lineage validation failed: {exc}") from exc
    return payload


def collect_f4_production(
    production_design: str | Path | Mapping[str, Any],
    batch_manifest: str | Path | Mapping[str, Any]
    | Sequence[str | Path | Mapping[str, Any]],
    qualification_receipt: str | Path | Mapping[str, Any],
    data_root: str | Path,
    *,
    products: str | Path | Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    formal_release_requested: bool = False,
    expected_case_count: int = EXPECTED_CASE_COUNT,
) -> dict[str, Any]:
    """Collect a fixed F4 production denominator without writing shared state."""
    if expected_case_count != EXPECTED_CASE_COUNT:
        raise CollectionError("F4 tallwall120 collector is fixed to a 32-case denominator")
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise CollectionError(f"data_root is not a directory: {root}")

    def load_source(value: Any, role: str) -> tuple[dict[str, Any], dict[str, Any], bool, Path | None]:
        if isinstance(value, (str, Path)):
            target = _resolve_path(value, root, None, role)
            payload = _read_json(target, role)
            if role == "qualification receipt":
                _require_qualification_receipt_schema(payload)
            binding = _ref(target, root, role=role)
            binding["canonical_sha256"] = canonical_sha256(payload)
            return payload, binding, True, target.parent
        if not isinstance(value, Mapping):
            raise CollectionError(f"{role} must be a JSON path or object")
        if role == "qualification receipt":
            _require_qualification_receipt_schema(value)
        payload = copy.deepcopy(dict(value))
        return payload, {"path": "<inline>", "sha256": canonical_sha256(payload), "role": role}, False, None

    design, design_ref, design_file, design_parent = load_source(production_design, "production design")
    if isinstance(batch_manifest, Mapping) and isinstance(batch_manifest.get("batches"), list):
        batch_sources = batch_manifest["batches"]
    elif isinstance(batch_manifest, Sequence) and not isinstance(batch_manifest, (str, bytes, Path)):
        batch_sources = list(batch_manifest)
    else:
        batch_sources = [batch_manifest]
    if not batch_sources:
        raise CollectionError("at least one production batch manifest is required")
    loaded_batches = [
        load_source(source, f"production batch {index}")
        for index, source in enumerate(batch_sources)
    ]
    qualification, qualification_ref, qualification_file, qualification_parent = load_source(
        qualification_receipt, "qualification receipt")
    design_rows, design_summary = _validate_design(design)
    qualification_summary = _validate_qualification(
        qualification, formal=bool(formal_release_requested))
    if qualification_summary["family"] != FAMILY or qualification_summary["scope_id"] != SCOPE_ID:
        raise CollectionError("qualification receipt family/scope does not bind tallwall120")
    prepared_by_index: dict[int, dict[str, Any]] = {}
    batch_refs: list[dict[str, Any]] = []
    batch_files = True
    for batch_index, (batch, batch_ref, batch_file, batch_parent) in enumerate(loaded_batches):
        if batch_parent is None:
            batch_parent = design_parent
        batch_entries = _validate_batch(
            batch, design_ref=design_ref, qualification_ref=qualification_ref,
            design_rows=design_rows, root=root, parent=batch_parent,
            batch_ref=batch_ref)
        duplicate = sorted(set(prepared_by_index).intersection(batch_entries))
        if duplicate:
            raise CollectionError(
                f"production batches overlap prepared indices: {duplicate}")
        prepared_by_index.update(batch_entries)
        batch_refs.append(batch_ref)
        batch_files = batch_files and batch_file

    product_parent = (loaded_batches[0][3] or design_parent)
    product_rows, product_parent = _load_products(products, root, product_parent)
    by_case: dict[str, Mapping[str, Any]] = {}
    excluded_products: list[dict[str, Any]] = []
    design_ids = {row["case_id"] for row in design_rows}
    for product in product_rows:
        case_id = product.get("case_id", product.get("prepared_case_id"))
        if not isinstance(case_id, str) or not case_id:
            raise CollectionError("case product row has no case_id")
        if case_id not in design_ids:
            if _qualification_marker(product):
                excluded_products.append({"case_id": case_id, "reason": "qualification_only"})
                continue
            raise CollectionError(f"unknown non-qualification product case: {case_id}")
        if case_id in by_case:
            raise CollectionError(f"duplicate product row for case: {case_id}")
        by_case[case_id] = product

    records: list[dict[str, Any]] = []
    reader_cases: list[dict[str, Any]] = []
    for index, design_row in enumerate(design_rows):
        product = by_case.get(design_row["case_id"])
        prepared_entry = prepared_by_index.get(index)
        record, reader = _case_record(
            index, design_row, prepared_entry, product, root=root,
            source_parent=product_parent, qualification_ref=qualification_ref,
            design_ref=design_ref,
            batch_ref=(prepared_entry or {}).get("batch_ref", batch_refs[0]),
            strict_audit=bool(formal_release_requested))
        records.append(record)
        if reader is not None and record.get("reader_eligible"):
            reader_cases.append(reader)

    status_counts = Counter(row["status"] for row in records)
    split_counts = Counter(row["split"] for row in records if row.get("denominator_included"))
    execution_complete_count = sum(bool(row.get("execution_complete")) for row in records)
    passed_count = sum(row.get("scientific_status") == "passed" and row.get("execution_complete") is True for row in records)
    authoritative_audit_count = sum(
        row.get("authoritative_audit_verified") is True for row in records)
    failed_count = sum(row.get("status") == "failed" for row in records)
    pending_count = sum(row.get("status") in {"not_prepared", "prepared_pending", "pending_audit", "incomplete_product"} for row in records)
    invalid_count = sum(row.get("status") == "invalid" for row in records)
    execution_bound_count = sum(
        row.get("execution_complete") is True and row.get("execution_receipt_bound") is True
        for row in records)
    hold_reasons: list[str] = []
    if len(records) != EXPECTED_CASE_COUNT:
        hold_reasons.append("registered 32-case denominator was not enumerated")
    if dict(split_counts) != EXPECTED_SPLITS:
        hold_reasons.append(f"fixed split denominator changed: {dict(split_counts)}")
    if execution_complete_count != EXPECTED_CASE_COUNT:
        hold_reasons.append(f"only {execution_complete_count}/32 cases reached the requested execution horizon")
    if passed_count != EXPECTED_CASE_COUNT:
        hold_reasons.append(f"only {passed_count}/32 cases passed hard scientific audit gates")
    if failed_count or pending_count or invalid_count:
        hold_reasons.append(
            f"case outcomes include failed={failed_count}, pending={pending_count}, invalid={invalid_count}")
    if len(reader_cases) != EXPECTED_CASE_COUNT:
        hold_reasons.append(f"only {len(reader_cases)}/32 cases have reader-eligible terminal products")
    if execution_bound_count != EXPECTED_CASE_COUNT:
        hold_reasons.append(
            f"only {execution_bound_count}/32 completed cases have bound native execution receipts")
    if formal_release_requested and authoritative_audit_count != passed_count:
        hold_reasons.append(
            f"only {authoritative_audit_count}/{passed_count} passed cases have authoritative connector audit verification")
    if not design_file or not batch_files or not qualification_file:
        hold_reasons.append("formal release requires file-bound design, batch, and qualification artifacts")
    if not formal_release_requested:
        hold_reasons.append("formal release was not requested")
    if formal_release_requested and qualification_summary.get("evidence_verified") is not True:
        hold_reasons.append("qualification evidence was not revalidated by the authoritative connector")
    formal_eligible = not hold_reasons
    source_bindings = {"batch": batch_refs[0]} if len(batch_refs) == 1 else {"batches": batch_refs}
    source_sha = canonical_sha256({
        "design": design_ref, **source_bindings,
        "qualification": qualification_ref,
    })
    reader_manifest = _manifest_with_cases(
        reader_cases, dataset_id="F4_tallwall120_production_reader_v1",
        source_sha=source_sha, formal_release=formal_eligible)
    training_manifest = copy.deepcopy(reader_manifest) if formal_eligible else None
    if training_manifest is not None:
        training_manifest["dataset_id"] = "F4_tallwall120_production_training_v1"
    return {
        "schema": SCHEMA,
        "collector_version": 1,
        "collected_at_utc": utc_now(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "production_design": design_ref,
        "production_batch": batch_refs[0] if len(batch_refs) == 1 else None,
        "production_batches": batch_refs,
        "production_batch_count": len(batch_refs),
        "qualification_receipt": qualification_ref,
        "qualification_summary": qualification_summary,
        "qualification_evidence_verified": qualification_summary.get("evidence_verified") is True,
        "design_summary": design_summary,
        "registered_case_count": EXPECTED_CASE_COUNT,
        "fixed_split_counts": dict(sorted(EXPECTED_SPLITS.items())),
        "observed_split_counts": dict(sorted(split_counts.items())),
        "prepared_case_count": len(prepared_by_index),
        "execution_complete_count": execution_complete_count,
        "scientifically_passed_case_count": passed_count,
        "authoritative_audit_verified_case_count": authoritative_audit_count,
        "failed_case_count": failed_count,
        "pending_case_count": pending_count,
        "invalid_case_count": invalid_count,
        "reader_case_count": len(reader_cases),
        "execution_receipt_bound_case_count": execution_bound_count,
        "qualification_excluded_product_count": len(excluded_products),
        "status_counts": dict(sorted(status_counts.items())),
        "failure_denominator": {
            "included_case_count": EXPECTED_CASE_COUNT,
            "failed_case_count": failed_count,
            "pending_case_count": pending_count,
            "fixed_splits": True,
        },
        "cases": records,
        "excluded_products": excluded_products,
        "formal_release_requested": bool(formal_release_requested),
        "formal_eligible": formal_eligible,
        "hold_reasons": sorted(set(hold_reasons)),
        "reader_manifest": reader_manifest,
        "training_manifest": training_manifest,
        "central_registry_written": False,
        "ledger_written": False,
        "gpu_started": False,
    }


def _load_manifest_value(value: Any, root: Path) -> dict[str, Any]:
    if isinstance(value, (str, Path)):
        target = _resolve_path(value, root, None, "family dataset manifest")
        return _read_json(target, "family dataset manifest")
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    raise CollectionError("family dataset source must be a path or object")


def assemble_multifamily_manifest(
    manifests: Sequence[str | Path | Mapping[str, Any]],
    data_root: str | Path,
    *,
    expected_case_counts: Mapping[str, int] | None = None,
    required_families: Sequence[str] = ("F1", "F2", "F4"),
    formal_release_requested: bool = False,
) -> dict[str, Any]:
    """Prepare a merged reader manifest while retaining formal hold reasons."""
    root = Path(data_root).expanduser().resolve()
    expected = dict(expected_case_counts or {family: EXPECTED_CASE_COUNT for family in required_families})
    all_cases: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    excluded_qualification: list[str] = []
    hold_reasons: list[str] = []
    for source in manifests:
        payload = _load_manifest_value(source, root)
        if payload.get("schema") == SCHEMA:
            nested = payload.get("reader_manifest")
            if not isinstance(nested, Mapping):
                source_status.append({"schema": SCHEMA, "formal_release": False, "case_count": 0})
                hold_reasons.append("F4 collection has no reader manifest")
                continue
            payload = copy.deepcopy(dict(nested))
        if payload.get("schema") not in {DATASET_SCHEMA, "core.dataset.v2"}:
            raise CollectionError("multi-family assembly accepts only canonical Core dataset manifests")
        rows = payload.get("cases")
        if not isinstance(rows, list):
            raise CollectionError("canonical family manifest has no cases list")
        source_status.append({"schema": payload.get("schema"),
                              "formal_release": payload.get("formal_release") is True,
                              "case_count": len(rows)})
        if payload.get("formal_release") is not True:
            hold_reasons.append(f"source {payload.get('dataset_id')} is not formally released")
        for row in rows:
            if not isinstance(row, Mapping):
                raise CollectionError("canonical family manifest contains a non-object case")
            if row.get("split") == "qualification" or row.get("qualification_case") is True:
                excluded_qualification.append(str(row.get("case_id")))
                continue
            if row.get("qualification_only") is True:
                excluded_qualification.append(str(row.get("case_id")))
                continue
            all_cases.append(copy.deepcopy(dict(row)))
    counts = Counter(row.get("family") for row in all_cases)
    for family in required_families:
        if counts.get(family, 0) != expected.get(family, EXPECTED_CASE_COUNT):
            hold_reasons.append(
                f"family {family} has {counts.get(family, 0)} reader cases; "
                f"requires {expected.get(family, EXPECTED_CASE_COUNT)}")
    if len(set(row.get("case_id") for row in all_cases)) != len(all_cases):
        raise CollectionError("multi-family assembly contains duplicate case_id")
    merged: dict[str, Any] | None = None
    if all_cases:
        merged = {
            "schema": DATASET_SCHEMA,
            "dataset_id": "core_multifamily_training_v1",
            "formal_release": False,
            "source_schema": ASSEMBLY_SCHEMA,
            "cases": all_cases,
        }
        try:
            validate_manifest(merged)
        except ValueError as exc:
            hold_reasons.append(f"merged physical/lineage manifest is invalid: {exc}")
            merged = None
    else:
        hold_reasons.append("no non-qualification family reader cases are available")
    if not manifests:
        hold_reasons.append("no family manifests supplied")
    formal = bool(formal_release_requested and not hold_reasons and merged is not None)
    if merged is not None:
        merged["formal_release"] = formal
        merged["assembly"] = {
            "schema": ASSEMBLY_SCHEMA,
            "required_families": list(required_families),
            "expected_case_counts": expected,
            "observed_case_counts": dict(sorted(counts.items())),
            "qualification_excluded_case_ids": sorted(excluded_qualification),
            "source_status": source_status,
            "formal_eligible": formal,
        }
    return {
        "schema": ASSEMBLY_SCHEMA,
        "collector_version": 1,
        "collected_at_utc": utc_now(),
        "formal_release_requested": bool(formal_release_requested),
        "formal_eligible": formal,
        "hold_reasons": sorted(set(hold_reasons)),
        "family_case_counts": dict(sorted(counts.items())),
        "qualification_excluded_case_ids": sorted(excluded_qualification),
        "manifest": merged,
        "source_status": source_status,
        "central_registry_written": False,
        "ledger_written": False,
    }


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"collector output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-design", type=Path, required=True)
    parser.add_argument("--batch-manifest", type=Path, action="append", required=True,
                        help="one or more hash-bound production batch manifests")
    parser.add_argument("--qualification-receipt", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--products", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-formal-release", action="store_true")
    args = parser.parse_args(argv)
    report = collect_f4_production(
        args.production_design,
        args.batch_manifest[0] if len(args.batch_manifest) == 1 else args.batch_manifest,
        args.qualification_receipt,
        args.data_root, products=args.products,
        formal_release_requested=args.request_formal_release)
    write_json(args.output, report)
    print(json.dumps({key: report[key] for key in (
        "schema", "registered_case_count", "prepared_case_count",
        "execution_complete_count", "failed_case_count", "pending_case_count",
        "reader_case_count", "formal_eligible", "hold_reasons")}, sort_keys=True))
    return 0 if report["formal_eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
