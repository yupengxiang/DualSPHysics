#!/usr/bin/env python3
"""Build a conservative, source-bound CURRENT336 lineage audit.

This pass is deliberately metadata-only.  It reads CURRENT336, the small
owner/receipt JSON files, and the existing raw-anchor plans.  It never opens a
trajectory HDF5 or a Part_*.bi4 array and it never hashes a large raw file.

The output is a development audit, not a qualification result.  A physical
group is formed only from an evidence-backed semantic binding with numerical,
case, owner, window, and recovery fields removed from the key.  Missing
semantic evidence stays in a conservative family unknown group, with
``split_safe=false``.  A receipt's ``status=completed`` is insufficient for a
GenCase completion claim when its finish evidence is absent.  Solver Run.out
is resolved only from the receipt's explicit output root/argv; no glob,
``latest`` selection, or neighbour fallback is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds02.stage2.current336-effective-lineage.v19-source-closure"
CARD_SCHEMA = "ds02.stage2.family-card.v19-development"
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_SMALL_JSON_BYTES = 16 * 1024 * 1024
MAX_SMALL_HASH_BYTES = 16 * 1024 * 1024

MECHANISMS = {
    "F1": {
        "mechanism": "eccentric lower-head / gravity release around a finite obstacle",
        "tasks": ["initial fluid cohort mass/COM", "obstacle interaction", "open-top outflow and return diagnostics"],
        "observables": [("mass", "kg"), ("COM", "m"), ("velocity", "m/s"), ("time", "s")],
    },
    "F2": {
        "mechanism": "prescribed rotating offset cup with receiver/aperture transport",
        "tasks": ["receiver-volume first passage", "finite aperture downward crossing", "residence and gross/net flux with censoring"],
        "observables": [("mass", "kg"), ("first_arrival_time", "s"), ("residence_mass_time", "kg*s"), ("flux", "kg/s")],
    },
    "F3": {
        "mechanism": "two-axis prescribed acceleration and sloshing response",
        "tasks": ["initial fluid cohort", "forced COM/front response", "time-windowed acceleration response"],
        "observables": [("COM/front", "m"), ("velocity", "m/s"), ("kinetic_energy", "J"), ("time", "s")],
    },
    "F4": {
        "mechanism": "finite drop impact into a finite pool",
        "tasks": ["drop/pool source cohorts", "first contact and rebound censoring", "mass-weighted front and COM"],
        "observables": [("mass", "kg"), ("COM/front", "m"), ("impact_time", "s"), ("velocity", "m/s")],
    },
    "F5": {
        "mechanism": "compact runup with prescribed forcing and recovery window",
        "tasks": ["runup/front measurement", "mass distribution", "recovery and tail censoring"],
        "observables": [("front/runup", "m"), ("mass", "kg"), ("velocity", "m/s"), ("time", "s")],
    },
    "F6": {
        "mechanism": "free six-degree-of-freedom rigid release with fluid coupling",
        "tasks": ["fluid observer", "rigid pose/SE(3) telemetry when explicitly encoded", "linear/angular velocity"],
        "observables": [("pose", "m, quaternion"), ("linear_velocity", "m/s"), ("angular_velocity", "rad/s"), ("fluid mass", "kg")],
    },
    "F7": {
        "mechanism": "finite wet-base tank with prescribed quintic moving obstacle",
        "tasks": ["moving-obstacle exchange", "left/right mass split", "front/flux and neutral-tail residence"],
        "observables": [("mass", "kg"), ("front", "m"), ("flux", "kg/s"), ("time", "s")],
    },
}


class LineageV19Error(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def sha256_small(path: Path | str, *, max_bytes: int = MAX_SMALL_HASH_BYTES) -> str:
    path = Path(path)
    size = path.stat().st_size
    if size > max_bytes:
        raise LineageV19Error(f"refusing large content hash in metadata audit: {path} ({size} bytes)")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_small_json(path: Path | str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_SMALL_JSON_BYTES:
        raise LineageV19Error(f"refusing large JSON source: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise LineageV19Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise LineageV19Error(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()
    except ValueError:
        return str(path)


def _as_path(binding: Mapping[str, Any] | None) -> Path | None:
    if not isinstance(binding, Mapping) or not isinstance(binding.get("path"), str):
        return None
    # CURRENT paths are absolute.  Avoid ``Path.resolve()`` here: it performs
    # component-by-component realpath lookups on the large spinning dataset
    # filesystem and this metadata pass must remain bounded.  The source
    # digest/stat checks below do not require symlink canonicalisation.
    value = Path(str(binding["path"])).expanduser()
    return value if value.is_absolute() else Path.cwd() / value


def classify_binding(binding: Mapping[str, Any] | None) -> dict[str, Any]:
    """Classify a CURRENT role without rehashing its underlying source."""
    if not isinstance(binding, Mapping):
        return {"status": "MISSING_BINDING", "path_exists": False, "digest": None}
    path = _as_path(binding)
    expected = binding.get("sha256") or binding.get("producer_declared_sha256")
    catalog_digest = binding.get("recomputed_sha256")
    if expected is None and catalog_digest is not None:
        expected = catalog_digest
    exists = bool(path and path.is_file())
    if not expected:
        status = "MISSING_DIGEST"
    elif not exists:
        status = "MISSING_PATH"
    elif binding.get("recomputed_sha256") is None:
        status = "PRODUCER_DECLARED_ONLY"
    elif str(binding.get("recomputed_sha256")) != str(expected):
        status = "DIGEST_MISMATCH"
    else:
        status = "EXACT_CATALOG_DIGEST"
    return {
        "status": status,
        "path": str(path) if path else None,
        "path_exists": exists,
        "expected_sha256": expected,
        "recomputed_sha256": catalog_digest,
        "original_uri": binding.get("path"),
    }


def _receipt_finish_status(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Separate launch evidence from complete producer evidence.

    Some historical adapter receipts say ``completed`` but have no finish
    timestamp, command, output root, or after-run hash map.  Those are kept as
    launch/adapter evidence and never upgraded by the status string alone.
    """
    if not isinstance(receipt, Mapping):
        return {"status": "RECEIPT_UNAVAILABLE", "complete": False, "missing": ["receipt"]}
    required = ("started_at_utc", "finished_at_utc", "command", "output_root", "returncode", "status")
    missing = [key for key in required if key not in receipt or receipt.get(key) in (None, "")]
    has_after_hashes = "input_hashes_after_run" in receipt
    is_success = receipt.get("status") in {"completed", "success", "ok"} and receipt.get("returncode", 0) == 0
    if not missing and is_success and (has_after_hashes or receipt.get("schema", "").endswith("execution-receipt.v1")):
        return {"status": "COMPLETE_FINISH_EVIDENCE", "complete": True, "missing": [], "has_after_hashes": has_after_hashes}
    if "started_at_utc" not in receipt and "command" not in receipt:
        return {"status": "RECEIPT_SCHEMA_UNKNOWN", "complete": False, "missing": missing}
    return {
        "status": "LAUNCH_ONLY_OR_INCOMPLETE_FINISH",
        "complete": False,
        "missing": missing + ([] if has_after_hashes else ["input_hashes_after_run"]),
        "reported_status": receipt.get("status"),
        "reported_returncode": receipt.get("returncode"),
    }


def receipt_finish_status(path: Path | str) -> dict[str, Any]:
    try:
        return _receipt_finish_status(load_small_json(path))
    except (FileNotFoundError, LineageV19Error, json.JSONDecodeError) as exc:
        return {"status": "RECEIPT_READ_FAILED", "complete": False, "error": str(exc)}


def _argv(receipt: Mapping[str, Any]) -> list[str]:
    value = receipt.get("command")
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def resolve_run_out(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve only explicit output paths in a solver receipt.

    The command's output argument is authoritative.  ``output_root/Run.out``
    is accepted only as the receipt's own root.  A nested ``solver_output``
    candidate is accepted only when that exact directory occurs in argv.  No
    recursive search or ``latest`` selection is performed.
    """
    if not isinstance(receipt, Mapping):
        return {"status": "RECEIPT_UNAVAILABLE", "candidates": []}
    output_root = receipt.get("output_root")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(output_root, str) and output_root:
        root = Path(output_root).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        candidates.append({"path": root / "Run.out", "reason": "receipt_output_root"})
    for arg in _argv(receipt):
        if "solver_output" not in arg and not arg.endswith("Run.out"):
            continue
        p = Path(arg).expanduser()
        candidate = p if p.name == "Run.out" else p / "Run.out"
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if str(candidate) not in seen:
            candidates.append({"path": candidate, "reason": "explicit_command_argv"})
            seen.add(str(candidate))
    existing = [item for item in candidates if item["path"].is_file()]
    if len(existing) == 1:
        item = existing[0]
        size = item["path"].stat().st_size
        # Run.out is useful as an explicitly addressed producer artifact, but
        # this 336-row closure pass does not rehash every output text file.
        # Parent source guards may supply/verify its SHA in the actual replay.
        return {"status": "EXACT_EXPLICIT_RUN_OUT", "candidates": [{**item, "path": str(item["path"])}],
                "run_out_path": str(item["path"]), "bytes": size,
                "sha256": None, "hash_status": "PARENT_GUARD_REQUIRED"}
    if len(existing) > 1:
        return {"status": "AMBIGUOUS_EXPLICIT_RUN_OUT", "candidates": [{**item, "path": str(item["path"])} for item in existing]}
    return {"status": "MISSING_EXPLICIT_RUN_OUT", "candidates": [{**item, "path": str(item["path"])} for item in candidates]}


_DROP_KEY_TERMS = (
    "hash", "sha", "path", "uri", "source", "owner", "case_id", "physical_case_id",
    "family_id", "resolution", "solver", "event_window", "window", "recovery", "runtime",
    "alias", "receipt", "claim", "approval", "q_i", "q_n", "q_e",
)
_NUMERICAL_KEY_TERMS = (
    "dp", "particle", "density_dt", "kernel", "step_algorithm", "verlet", "cfl", "time_out",
    "time_max", "dt_ini", "dt_min", "dt_fixed", "save", "threads", "gpu", "cuda", "output",
    "visco", "shifting", "rhop", "coefdt", "ftpause",
)


def _drop_key(key: str) -> bool:
    normal = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(term in normal for term in _DROP_KEY_TERMS) or any(term in normal for term in _NUMERICAL_KEY_TERMS)


def _semantic_value(value: Any, *, key: str = "") -> Any:
    if _drop_key(key):
        return None
    if isinstance(value, Mapping):
        kept = {}
        for raw_key, item in value.items():
            name = str(raw_key)
            if _drop_key(name):
                continue
            normalized = _semantic_value(item, key=name)
            if normalized is not None:
                kept[name] = normalized
        return kept or None
    if isinstance(value, list):
        values = [_semantic_value(item, key=key) for item in value]
        return [item for item in values if item is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def physical_binding(owner: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(owner, Mapping):
        return None, "owner_metadata_unavailable"
    candidate = owner.get("physical_binding")
    if not isinstance(candidate, Mapping):
        # A few historical owners expose the same semantic fields at the top
        # level.  Only use them when all core fields are present; otherwise
        # remain in the conservative unknown group.
        if all(key in owner for key in ("geometry", "initial_state", "mechanism_id")):
            candidate = owner
        else:
            return None, "physical_binding_missing_or_legacy_incomplete"
    required = ("geometry", "initial_state", "mechanism_id")
    if not all(key in candidate for key in required):
        return None, "physical_binding_missing_core_semantics"
    semantic = _semantic_value(candidate)
    if not isinstance(semantic, Mapping) or not semantic:
        return None, "physical_binding_semantics_empty"
    # Controls/parameters are optional in old metadata, but absence means the
    # resulting group is a development observation only, never split-safe.
    return dict(semantic), "physical_binding_supported"


def effective_physical_key(family: str, owner: Mapping[str, Any] | None) -> dict[str, Any]:
    semantic, reason = physical_binding(owner)
    if semantic is None:
        return {
            "key": f"{family}:UNKNOWN_CONSERVATIVE_GROUP",
            "status": "PROVISIONAL_UNKNOWN",
            "split_safe": False,
            "reason": reason,
            "semantic_payload": None,
        }
    # Family is deliberately retained as the conservative boundary while
    # cross-family control-template equivalence remains unreviewed.
    digest = canonical_sha(semantic)
    return {
        "key": f"{family}:physical:{digest}",
        "status": "SOURCE_SUPPORTED_DEVELOPMENT_GROUP",
        "split_safe": False,
        "reason": "physical/control/geometry payload observed; recovery/window/numerical transfer remains unknown",
        "semantic_payload": semantic,
    }


def _load_owner(case: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    binding = case.get("source_bindings", {}).get("owner_metadata")
    path = _as_path(binding if isinstance(binding, Mapping) else None)
    if path is None or not path.is_file():
        return None, str(path) if path else None
    try:
        return load_small_json(path), str(path)
    except (OSError, ValueError, json.JSONDecodeError, LineageV19Error):
        return None, str(path)


def validate_selection_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    # Do not flag a well-formed ``latest_glob: false`` field merely because
    # the field name documents the forbidden mode.  Inspect true flags and
    # human-readable values instead.
    values: list[str] = []
    true_flags: set[str] = set()
    for key, value in policy.items():
        normal_key = str(key).lower()
        if isinstance(value, bool):
            if value:
                true_flags.add(normal_key)
        elif isinstance(value, (str, int, float)):
            values.append(str(value).lower())
    text = " ".join(values)
    terms = ("latest", "glob", "arbitrary", "fixed legacy", "legacy list", "neighbor")
    banned = [term for term in terms if term in text or any(term.replace(" ", "_") in flag for flag in true_flags)]
    source = str(policy.get("source", "")).lower()
    exact = bool(
        policy.get("source_exact_current_row")
        or policy.get("exact_current_row")
        or policy.get("current_row_binding")
        or ("exact current" in source and "physical_case_id" in source)
    )
    return {"valid": not banned and exact, "banned_terms": banned, "exact_current_row": exact}


def _case_source_closure(case: Mapping[str, Any]) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    for role in ("manifest", "xmf", "trajectory", "conversion_report"):
        binding = case.get(role)
        roles[role] = classify_binding(binding if isinstance(binding, Mapping) else None)
    source_bindings = case.get("source_bindings")
    if isinstance(source_bindings, Mapping):
        for role, binding in source_bindings.items():
            roles[str(role)] = classify_binding(binding if isinstance(binding, Mapping) else None)
    receipt_details = {}
    for role in ("gencase_receipt", "solver_receipt"):
        binding = source_bindings.get(role) if isinstance(source_bindings, Mapping) else None
        path = _as_path(binding if isinstance(binding, Mapping) else None)
        if path:
            receipt_details[role] = receipt_finish_status(path)
        else:
            receipt_details[role] = {"status": "RECEIPT_UNAVAILABLE", "complete": False}
    solver_binding = source_bindings.get("solver_receipt") if isinstance(source_bindings, Mapping) else None
    solver_path = _as_path(solver_binding if isinstance(solver_binding, Mapping) else None)
    run_out = {"status": "RECEIPT_UNAVAILABLE", "candidates": []}
    if solver_path and solver_path.is_file():
        try:
            run_out = resolve_run_out(load_small_json(solver_path))
        except (OSError, ValueError, json.JSONDecodeError, LineageV19Error) as exc:
            run_out = {"status": "SOLVER_RECEIPT_READ_FAILED", "error": str(exc), "candidates": []}
    counts = Counter(item.get("status") for item in roles.values())
    if counts.get("DIGEST_MISMATCH", 0):
        closure_status = "REJECT_DIGEST_MISMATCH"
    elif counts.get("MISSING_PATH", 0) or counts.get("MISSING_DIGEST", 0):
        closure_status = "PENDING_SOURCE_ROLE"
    elif counts.get("PRODUCER_DECLARED_ONLY", 0):
        closure_status = "CONTENT_PENDING_PARENT_GUARD"
    else:
        closure_status = "METADATA_ROLE_DIGESTS_PRESENT"
    return {
        "roles": roles,
        "role_status_counts": dict(counts),
        "receipts": receipt_details,
        "solver_run_out": run_out,
        "closure_status": closure_status,
        "content_hash_policy": "CURRENT/catalog digests are carried; trajectory/BI4 producer-only content is not rehashed in this audit",
    }


def _plan_info(plan_path: Path, output_root: Path) -> dict[str, Any]:
    if not plan_path.is_file():
        return {"status": "PLAN_MISSING", "path": _relative(plan_path, output_root)}
    try:
        plan = load_small_json(plan_path)
    except Exception as exc:
        return {"status": "PLAN_READ_FAILED", "path": _relative(plan_path, output_root), "error": str(exc)}
    policy = plan.get("selection_policy") if isinstance(plan.get("selection_policy"), Mapping) else {}
    validation = validate_selection_policy(policy)
    return {
        "status": "PLAN_POLICY_ACCEPTED" if validation["valid"] else "PLAN_POLICY_REJECTED",
        "path": _relative(plan_path, output_root),
        "sha256": sha256_small(plan_path),
        "selection_policy": policy,
        "selection_policy_validation": validation,
        "execution_status": plan.get("status"),
        "unknown_scope": plan.get("unknown_scope", plan.get("limitations", [])),
    }


def _variation_dimensions(case: Mapping[str, Any], owner: Mapping[str, Any] | None) -> dict[str, Any]:
    result = {
        "resolution": case.get("known_numeric_physical_parameters", {}).get("dp_m") if isinstance(case.get("known_numeric_physical_parameters"), Mapping) else None,
        "particle_count": case.get("particles"),
        "frame_count": case.get("frames"),
        "time_window_s": case.get("actual_time_window_s"),
        "recovery": "UNKNOWN_PENDING_EXPLICIT_RESTART_OR_RECOVERY_EVIDENCE",
    }
    if isinstance(owner, Mapping):
        result["owner_resolution"] = owner.get("resolution")
        result["owner_solver_parameters_present"] = isinstance(owner.get("solver_parameters"), Mapping)
        result["source_status"] = owner.get("status") or owner.get("owner_status")
    return result


def _source_card(family: str, rows: Sequence[Mapping[str, Any]], output_root: Path,
                 plan: Mapping[str, Any], groups: Mapping[str, int]) -> dict[str, Any]:
    closure_counts = Counter(row["source_closure"]["closure_status"] for row in rows)
    gencase_counts = Counter(row["source_closure"]["receipts"]["gencase_receipt"]["status"] for row in rows)
    solver_counts = Counter(row["source_closure"]["receipts"]["solver_receipt"]["status"] for row in rows)
    run_counts = Counter(row["source_closure"]["solver_run_out"]["status"] for row in rows)
    unknown_groups = sum(1 for row in rows if row["physical_group"]["status"] == "PROVISIONAL_UNKNOWN")
    mechanism = MECHANISMS[family]
    card = {
        "schema": CARD_SCHEMA,
        "status": "DEVELOPMENT_ONLY; PROVISIONAL; QUALIFICATION_UNKNOWN",
        "family_id": family,
        "case_count": len(rows),
        "physical_mechanism": mechanism["mechanism"],
        "task_subsets": [{"task": task, "status": "SOURCE_BOUND_DEVELOPMENT"} for task in mechanism["tasks"]],
        "observer_contract": [{"name": name, "unit": unit, "status": "REQUIRES_TYPED_OR_NATIVE_EVIDENCE"} for name, unit in mechanism["observables"]],
        "raw_anchor": {
            "plan": plan,
            "status": "REQUESTABLE_METADATA_CLOSURE_ONLY; RAW_TYPED_COMPARE_PENDING",
            "hidden": False,
            "arbitrary_latest_or_glob": False,
        },
        "source_closure": {
            "case_status_counts": dict(closure_counts),
            "gencase_receipt_finish_counts": dict(gencase_counts),
            "solver_receipt_finish_counts": dict(solver_counts),
            "explicit_run_out_counts": dict(run_counts),
            "producer_declared_raw_content_requires_parent_guard": True,
        },
        "effective_condition": {
            "physical": "semantic owner/physical_binding payload only; no owner/case hash identity",
            "control": "source control/motion roles and physical binding retained; continuous curve equivalence is per-source and remains UNKNOWN unless explicitly bound",
            "geometry": "generated XML/definition roles retained; open/closed/receiver semantics require source-bound geometry parser",
            "initial_state": "CURRENT identity and owner source cohort retained; native typed mass/type/MK compare pending",
            "parameter_support": "finite observed CURRENT support only",
            "resolution": "variation dimension, never physical identity",
            "window": "variation dimension; cross-window equivalence UNKNOWN",
            "recovery": "UNKNOWN; no restart/recovery evidence is inferred from completion receipt",
        },
        "development_split": {
            "group_count": len(groups),
            "physical_groups": dict(groups),
            "unknown_group_case_count": unknown_groups,
            "split_safe": False,
            "policy": "hold out whole source-supported physical connected components; conservative family unknown group for incomplete evidence",
            "owner_case_hashes": "provenance only; excluded from physical group key",
        },
        "qualification": UNKNOWN,
        "unknown_scope": [
            "raw Part_*.bi4 to typed per-frame reconstruction and producer tree comparison",
            "receiver/aperture/destination and moving-frame event semantics",
            "cross-resolution/recovery/window transfer and prospective split safety",
            "reference calibration and QI/QN/QE",
        ],
    }
    card["sha256"] = canonical_sha(card)
    return card


def build(current_path: Path | str, output_dir: Path | str, *, plan_root: Path | str | None = None) -> dict[str, Any]:
    current_file = Path(current_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    current = load_small_json(current_file)
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise LineageV19Error("exact CURRENT336 case list is required")
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise LineageV19Error("unexpected CURRENT schema")
    if output.exists():
        raise LineageV19Error(f"refusing to overwrite output directory: {output}")
    plan_root = Path(plan_root or current_file.parent / "lineage" / "v14" / "raw-anchor-plans").expanduser().resolve()
    all_rows: list[dict[str, Any]] = []
    family_rows: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILIES}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping) or case.get("family_id") not in family_rows:
            raise LineageV19Error(f"invalid family at CURRENT row {index}")
        family = str(case["family_id"])
        owner, owner_path = _load_owner(case)
        row = {
            "case_index": index,
            "family_id": family,
            "physical_case_id": case.get("physical_case_id"),
            "runtime_case_alias": case.get("runtime_case_alias"),
            "source_closure": _case_source_closure(case),
            "physical_group": effective_physical_key(family, owner),
            "owner_metadata": {"path": owner_path, "read": owner is not None},
            "variation_dimensions": _variation_dimensions(case, owner),
            "identity": {
                "physical_case_id": case.get("physical_case_id"),
                "runtime_case_alias": case.get("runtime_case_alias"),
                "identity_key": case.get("header", {}).get("identity_key") if isinstance(case.get("header"), Mapping) else None,
                "identity_policy": "CURRENT row identity is exact; alias/provenance is retained and never silently rewritten",
            },
        }
        all_rows.append(row)
        family_rows[family].append(row)
    if any(len(rows) != 48 for rows in family_rows.values()):
        raise LineageV19Error({family: len(rows) for family, rows in family_rows.items()})

    cards: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        rows = family_rows[family]
        groups = Counter(row["physical_group"]["key"] for row in rows)
        plan = _plan_info(plan_root / f"{family}-raw-anchor-plan-v1.json", output)
        cards[family] = _source_card(family, rows, output, plan, groups)
    report = {
        "schema": SCHEMA,
        "status": "DEVELOPMENT_ONLY; SEMANTIC_CLOSURE_PARTIAL; QUALIFICATION_UNKNOWN",
        "catalog_binding": {
            "current_path": _relative(current_file, output),
            "current_schema": current.get("schema"),
            "catalog_case_count": len(cases),
            "catalog_sha256": current.get("source_catalog_sha256"),
            "current_json_sha256": sha256_small(current_file),
            "total_hdf5_bytes_declared": current.get("total_hdf5_bytes"),
        },
        "read_scope": {
            "hdf5_opened": False,
            "bi4_opened": False,
            "large_source_rehashed": False,
            "metadata_json_max_bytes": MAX_SMALL_JSON_BYTES,
            "small_source_json_and_stat_only": True,
        },
        "selection_policy": {
            "source": "exact CURRENT row and physical_case_id/identity binding",
            "forbidden": ["latest glob", "arbitrary Run.out", "fixed legacy case list", "neighbour fallback", "silent alias rewrite"],
            "raw_anchor_plan_validation": {family: cards[family]["raw_anchor"]["plan"]["selection_policy_validation"] for family in FAMILIES},
        },
        "family_cards": {},
        "case_source_links": all_rows,
        "split_policy": {
            "key_semantics": "family + canonical physical geometry/initial/control/mechanism payload after removing case/owner/source/hash/numerical/window/recovery fields",
            "unknown_semantics": "same-family UNKNOWN_CONSERVATIVE_GROUP; split_safe=false",
            "numerical_dimensions": ["dp", "particle_count", "solver_parameters", "frame_count", "time_window_s"],
            "recovery_and_window": "never split-safe without explicit connected evidence",
            "cross_family_templates": "not reviewed; family remains a conservative boundary",
            "qualification": UNKNOWN,
        },
        "counterexample_contract": [
            {"id": "C35", "case": "nested solver_output/Run.out", "expected": "explicit receipt argv candidate is accepted; neighbour fallback is rejected"},
            {"id": "C36", "case": "completed GenCase status with missing finish evidence", "expected": "LAUNCH_ONLY_OR_INCOMPLETE_FINISH"},
            {"id": "C37", "case": "same semantic payload with different opaque owner hash", "expected": "same effective physical key"},
            {"id": "C39", "case": "producer-declared H5/BI4 digest without recomputed catalog digest", "expected": "CONTENT_PENDING_PARENT_GUARD"},
            {"id": "C40", "case": "latest/glob/fixed legacy selection", "expected": "selection policy rejected"},
        ],
        "qualification": UNKNOWN,
        "model_invoked": False,
        "cfd_invoked": False,
        "limitations": [
            "Cards are substantive development contracts and source closure evidence; they do not grant QI/QN/QE.",
            "A raw anchor plan or a typed receipt is not native raw-to-label reconstruction.",
            "Producer-declared trajectory/BI4 hashes remain pending parent full-content guard.",
        ],
    }
    for family in FAMILIES:
        card_path = output / f"{family}-family-card-v19-development.json"
        _write_new(card_path, cards[family])
        report["family_cards"][family] = {"path": card_path.name, "sha256": cards[family]["sha256"], "status": cards[family]["status"]}
    report["sha256"] = canonical_sha(report)
    report_path = output / "CURRENT336-effective-lineage-audit-v19-source-closure.json"
    _write_new(report_path, report)
    return {"report": str(report_path), "cards": {family: str(output / f"{family}-family-card-v19-development.json") for family in FAMILIES}, "case_count": len(cases)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.current, args.output_dir, plan_root=args.plan_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
