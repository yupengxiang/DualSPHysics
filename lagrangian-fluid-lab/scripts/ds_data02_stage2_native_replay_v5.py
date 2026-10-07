#!/usr/bin/env python3
"""Source-bound preparation for a native Stage 2 replay.

This module is deliberately a metadata-only companion to the v4 operator.
It binds one real CURRENT row to its manifest, XML/control, conversion and
scan evidence without discovering a trajectory by globbing or reading an
arbitrary ``Run.out``.  The selected F2-S1 case is prepared for a later,
explicitly approved initial-frame I/O slot; this module never performs that
read by default.

The lineage audit is conservative.  It records physical-condition and source
hashes when a manifest declares them, groups missing evidence within a family,
and labels every group ``PROVISIONAL_REVIEW_ONLY``.  Numerical/XML variants
are not declared split-safe from this metadata pass.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_consumers_v4 import (  # noqa: E402
    BindingError,
    Current336Catalog,
    CurrentCase,
    canonical_sha256,
    load_current_catalog,
)


NATIVE_REPLAY_SCHEMA = "ds02.stage2.native-replay-bundle.v5"
LINEAGE_AUDIT_SCHEMA = "ds02.stage2.current336-lineage-audit.v1"
INITIAL_FRAME_REQUEST_SCHEMA = "ds02.stage2.initial-frame-request.v1"
MAX_SMALL_BINDING_BYTES = 64 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class NativeReplayBindingError(BindingError):
    """A source-bound native replay dependency is missing or inconsistent."""


def read_json(path: Path | str) -> Any:
    def reject_constant(value: str) -> Any:
        raise NativeReplayBindingError(f"non-finite JSON constant {value!r}: {path}")

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _portable_path(path: Path) -> dict[str, Any]:
    """Represent an absolute path through a stable root alias and relpath."""
    roots = (
        ("DS_DATA_02", Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")),
        ("STAGE2_WORKTREE", Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")),
        ("INTEGRATION_WORKTREE", Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")),
        ("PROJECT_REPO", Path("/home/jade/Projects/DualSPHysics")),
    )
    resolved = path.expanduser().resolve()
    matches: list[tuple[str, Path, Path]] = []
    for alias, root in roots:
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        matches.append((alias, root, relative))
    if matches:
        alias, root, relative = max(matches, key=lambda item: len(str(item[1])))
        return {"root_alias": alias, "relative_path": relative.as_posix(),
                "portable": True}
    return {"root_alias": None, "relative_path": None, "portable": False,
            "absolute_path_required": True}


def _path_ref(path: Path, *, role: str, expected_hash: str | None = None,
              max_bytes: int = MAX_SMALL_BINDING_BYTES) -> dict[str, Any]:
    if not path.is_file():
        raise NativeReplayBindingError(f"{role}: unavailable source file: {path}")
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise NativeReplayBindingError(
            f"{role}: refusing an unbounded/large read ({stat.st_size} bytes): {path}")
    actual = sha256(path)
    if expected_hash and actual != expected_hash:
        raise NativeReplayBindingError(
            f"{role}: source hash differs (expected {expected_hash}, got {actual})")
    return {
        "role": role,
        "path": str(path.resolve()),
        "portable_path": _portable_path(path),
        "sha256": actual,
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "read_only": True,
    }


def _trajectory_ref(case: CurrentCase) -> dict[str, Any]:
    """Bind trajectory metadata without hashing or opening HDF5."""
    spec = case.row.get("trajectory")
    if not isinstance(spec, Mapping):
        raise NativeReplayBindingError(f"{case.physical_case_id}: trajectory binding is missing")
    path = case.path(spec)
    if path.suffix.lower() not in (".h5", ".hdf5"):
        raise NativeReplayBindingError(f"{case.physical_case_id}: trajectory is not HDF5: {path}")
    if not path.is_file():
        raise NativeReplayBindingError(f"{case.physical_case_id}: trajectory is unavailable: {path}")
    stat = path.stat()
    expected_bytes = spec.get("bytes")
    expected_mtime = spec.get("mtime_ns")
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise NativeReplayBindingError(f"{case.physical_case_id}: HDF5 byte count differs from CURRENT")
    if expected_mtime is not None and int(expected_mtime) != stat.st_mtime_ns:
        raise NativeReplayBindingError(f"{case.physical_case_id}: HDF5 mtime differs from CURRENT")
    producer_hash = spec.get("producer_declared_sha256")
    if not isinstance(producer_hash, str) or not _HEX64.fullmatch(producer_hash):
        raise NativeReplayBindingError(f"{case.physical_case_id}: HDF5 producer hash is incomplete")
    return {
        "role": "current_bound_trajectory_hdf5",
        "path": str(path.resolve()),
        "portable_path": _portable_path(path),
        "sha256": None,
        "producer_declared_sha256": producer_hash,
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "read_only": True,
        "read_status": "NOT_READ_PENDING_APPROVED_IO_SLOT",
    }


def _bind_spec(case: CurrentCase, role: str, spec: Mapping[str, Any] | str,
               *, allow_hdf5: bool = False) -> dict[str, Any]:
    raw = spec if isinstance(spec, str) else spec.get("path")
    if not raw:
        raise NativeReplayBindingError(f"{case.physical_case_id}: {role} path is missing")
    path = case.path(str(raw))
    expected = None
    if isinstance(spec, Mapping):
        expected = spec.get("recomputed_sha256") or spec.get("sha256")
    if path.suffix.lower() in (".h5", ".hdf5"):
        if not allow_hdf5:
            raise NativeReplayBindingError(f"{role}: HDF5 may only use _trajectory_ref")
        return _trajectory_ref(case)
    return _path_ref(path, role=role, expected_hash=str(expected) if expected else None)


def _safe_manifest_id(case: CurrentCase, manifest: Mapping[str, Any]) -> str | None:
    manifest_id = manifest.get("physical_case_id")
    expected = case.row.get("manifest_physical_case_id") or case.physical_case_id
    if manifest_id is not None and manifest_id != expected:
        raise NativeReplayBindingError(
            f"{case.physical_case_id}: manifest physical_case_id {manifest_id!r} "
            f"does not match CURRENT binding {expected!r}")
    if manifest.get("family_id") is not None and manifest.get("family_id") != case.family_id:
        raise NativeReplayBindingError(f"{case.physical_case_id}: manifest family differs from CURRENT")
    return str(manifest_id) if manifest_id is not None else None


def _manifest_and_bindings(case: CurrentCase) -> tuple[Mapping[str, Any], dict[str, Any]]:
    manifest_spec = case.row.get("manifest")
    if not isinstance(manifest_spec, Mapping):
        raise NativeReplayBindingError(f"{case.physical_case_id}: manifest binding is missing")
    manifest_binding = _bind_spec(case, "CURRENT manifest", manifest_spec)
    manifest = read_json(manifest_binding["path"])
    if not isinstance(manifest, Mapping):
        raise NativeReplayBindingError(f"{case.physical_case_id}: manifest is not an object")
    manifest_id = _safe_manifest_id(case, manifest)
    if not isinstance(manifest.get("schema"), str) or not manifest["schema"]:
        raise NativeReplayBindingError(f"{case.physical_case_id}: manifest schema is missing")

    small: dict[str, Any] = {"manifest": manifest_binding}
    for name in ("xmf", "conversion_report"):
        spec = case.row.get(name)
        if isinstance(spec, Mapping):
            small[name] = _bind_spec(case, f"CURRENT {name}", spec)

    source_bindings = case.row.get("source_bindings")
    bound_source: dict[str, Any] = {}
    if isinstance(source_bindings, Mapping):
        for name, spec in sorted(source_bindings.items()):
            if isinstance(spec, Mapping):
                bound_source[name] = _bind_spec(case, f"CURRENT source_bindings.{name}", spec)
    small["current_source_bindings"] = bound_source

    # The manifest has its own provenance links.  They are retained as roles,
    # even where two links name the same bytes, because scope is evidence.
    manifest_source: dict[str, Any] = {}
    for name in ("generated_xml", "typed_receipt", "native_receipt", "owner_metadata",
                 "conversion_report", "xdmf"):
        raw = manifest.get(name)
        if isinstance(raw, str):
            try:
                manifest_source[name] = _bind_spec(case, f"manifest.{name}", raw)
            except NativeReplayBindingError as error:
                manifest_source[name] = {"status": "UNAVAILABLE", "error": str(error),
                                         "declared_path": raw}
    small["manifest_source_bindings"] = manifest_source
    return manifest, {"manifest_id": manifest_id, "small_files": small}


def _declared_xml_files(case: CurrentCase, xml_binding: Mapping[str, Any]) -> dict[str, Any]:
    """Bind explicit XML ``<file name=...>`` references; never glob."""
    xml_path = Path(str(xml_binding["path"]))
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as error:
        raise NativeReplayBindingError(f"{case.physical_case_id}: generated XML is malformed") from error
    declared: list[dict[str, Any]] = []
    for element in root.iter():
        # ``<varnum name="VResId">`` is an XML variable, not an input file.
        # Only the explicit file element is a dependency; this keeps the
        # binding strict without inventing a path for a variable name.
        if element.tag != "file":
            continue
        name = element.attrib.get("name")
        if not name:
            continue
        candidate = (xml_path.parent / name).resolve()
        if candidate.is_file():
            item = _path_ref(candidate, role=f"generated_xml_declared_file:{name}")
            item["xml_tag"] = element.tag
            declared.append(item)
        else:
            declared.append({"role": "generated_xml_declared_file", "name": name,
                             "xml_tag": element.tag, "status": "UNAVAILABLE",
                             "portable_path": _portable_path(candidate),
                             "path": str(candidate)})
    return {
        "xml_sha256": xml_binding["sha256"],
        "root_tag": root.tag,
        "declared_files": declared,
        "motion_file_count": len(declared),
    }


def _json_binding_payload(binding: Mapping[str, Any]) -> Mapping[str, Any] | None:
    path = binding.get("path")
    if not isinstance(path, str) or not path.endswith(".json"):
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, NativeReplayBindingError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _first_json_binding(bindings: Mapping[str, Any], *names: str) -> Mapping[str, Any] | None:
    for name in names:
        value = bindings.get(name)
        if isinstance(value, Mapping) and value.get("sha256"):
            payload = _json_binding_payload(value)
            if payload is not None:
                return payload
    return None


def _source_scope_record(case: CurrentCase, manifest: Mapping[str, Any],
                         conversion: Mapping[str, Any] | None,
                         owner: Mapping[str, Any] | None) -> dict[str, Any]:
    source_provenance = conversion.get("source_provenance", {}) if isinstance(conversion, Mapping) else {}
    owner_provenance = owner.get("provenance", {}) if isinstance(owner, Mapping) else {}
    return {
        "physical_case_id": case.physical_case_id,
        "manifest_physical_case_id": manifest.get("physical_case_id"),
        "manifest_case_id": manifest.get("case_id"),
        "manifest_physical_condition_sha256": manifest.get("physical_condition_sha256"),
        "manifest_canonical_source_physical_condition_sha256": manifest.get(
            "canonical_source_physical_condition_sha256"),
        "manifest_actual_converter_legacy_scope_sha256": manifest.get(
            "actual_converter_legacy_scope_sha256"),
        "owner_physical_condition_sha256": owner.get("physical_condition_sha256") if owner else None,
        "owner_plan_physical_condition_sha256": owner.get("source_plan_physical_condition_sha256") if owner else None,
        "owner_lineage_group_id": owner.get("lineage_group_id") if owner else None,
        "control_family_id": (owner.get("control_family_id") if owner else None),
        "geometry_family_id": (owner.get("geometry_family_id") if owner else None),
        "conversion_control_sha256": source_provenance.get("control_sha256"),
        "conversion_control_reference_sha256": source_provenance.get("control_reference_sha256"),
        "conversion_geometry_sha256": source_provenance.get("geometry_sha256"),
        "owner_source_motion_sha256": owner_provenance.get("source_motion_sha256") if owner else None,
        "hdf5_scope": {
            "producer_declared_sha256": case.row.get("trajectory", {}).get("producer_declared_sha256"),
            "semantics": "artifact identity only; not a physical-condition hash",
            "equality_claim": "NOT_ASSERTED",
        },
        "scope_equality_claim": "NOT_ASSERTED",
    }


def _lineage_key(case: CurrentCase, manifest: Mapping[str, Any]) -> tuple[str, str]:
    """Choose a conservative provisional group key.

    A declared canonical physical-condition hash can connect resolution and
    rerun variants.  When it is absent, all rows in a family share one
    conservative unknown group; case IDs and XML hashes are never treated as
    proof of split safety.
    """
    candidate = manifest.get("canonical_source_physical_condition_sha256")
    if not isinstance(candidate, str) or not _HEX64.fullmatch(candidate):
        candidate = manifest.get("physical_condition_sha256")
    if not isinstance(candidate, str) or not _HEX64.fullmatch(candidate):
        return f"PROVISIONAL_UNKNOWN_FAMILY:{case.family_id}", "UNKNOWN_FAMILY_EVIDENCE"
    return f"PROVISIONAL_PHYSICAL:{case.family_id}:{candidate}", "DECLARED_PHYSICAL_HASH"


def audit_current_lineage(catalog: Current336Catalog) -> dict[str, Any]:
    """Read all 336 manifest JSONs and report conservative lineage evidence."""
    family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    row_records: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    field_counts: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for case in catalog.cases():
        manifest_spec = case.row.get("manifest")
        manifest: Mapping[str, Any] = {}
        manifest_binding: Mapping[str, Any] | None = None
        if isinstance(manifest_spec, Mapping):
            try:
                manifest_binding = _bind_spec(case, "lineage manifest", manifest_spec)
                loaded = read_json(manifest_binding["path"])
                if isinstance(loaded, Mapping):
                    manifest = loaded
                    _safe_manifest_id(case, manifest)
            except NativeReplayBindingError as error:
                unavailable.append({"physical_case_id": case.physical_case_id, "reason": str(error)})
        else:
            unavailable.append({"physical_case_id": case.physical_case_id,
                                "reason": "CURRENT manifest binding missing"})

        key, evidence = _lineage_key(case, manifest)
        # These are presence counters rather than a claim that a field is
        # semantically comparable across families.
        for field in ("physical_condition_sha256", "canonical_source_physical_condition_sha256",
                      "actual_converter_legacy_scope_sha256", "case_id", "actual_geometry",
                      "physical_window_s", "expected_frames", "resolution", "recovery",
                      "control_family_id", "geometry_family_id", "numerical_hash", "xml_hash"):
            field_counts[case.family_id][field]["present" if manifest.get(field) is not None else "unknown"] += 1
        record = {
            "physical_case_id": case.physical_case_id,
            "family_id": case.family_id,
            "manifest_case_id": manifest.get("case_id"),
            "lineage_group": key,
            "evidence": evidence,
            "role": "DEVELOPMENT",
            "hidden_test": False,
            "split_safe": False,
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "manifest_sha256": manifest_binding.get("sha256") if manifest_binding else None,
            "known_numeric_physical_parameters": case.row.get("known_numeric_physical_parameters", {}),
        }
        row_records.append(record)
        family_rows[case.family_id].append(record)

    families: dict[str, Any] = {}
    for family, records in sorted(family_rows.items()):
        groups = Counter(record["lineage_group"] for record in records)
        unknown_examples = [record["physical_case_id"] for record in records
                            if record["evidence"] == "UNKNOWN_FAMILY_EVIDENCE"][:8]
        families[family] = {
            "rows": len(records),
            "provisional_groups": dict(sorted(groups.items())),
            "unknown_group_examples": unknown_examples,
            "field_presence": {
                field: dict(sorted(counts.items()))
                for field, counts in sorted(field_counts[family].items())
            },
            "known_numeric_parameter_examples": [record["known_numeric_physical_parameters"]
                                                  for record in records
                                                  if record["known_numeric_physical_parameters"]][:4],
            "control_template_status": "UNKNOWN_UNLESS_EXPLICITLY_BOUND",
            "resolution_recovery_status": "PROVISIONAL_FIELD_PRESENCE_ONLY",
            "split_safe": False,
        }
    return {
        "schema": LINEAGE_AUDIT_SCHEMA,
        "current_manifest_sha256": catalog.sha256,
        "rows": len(row_records),
        "families": families,
        "cases": row_records,
        "unavailable_manifest_rows": unavailable,
        "unknown_policy": "same-family conservative group; UNKNOWN remains development-only",
        "cross_numerical_xml_variant_policy": (
            "requires independently bound canonical physical-condition/control/geometry evidence; "
            "case_id or XML hash alone is insufficient"),
        "split_safety": "PROVISIONAL_REVIEW_ONLY",
        "hidden_test": False,
        "qualification_status": "UNKNOWN",
    }


def initial_frame_request(case: CurrentCase, *, particle_stop: int = 16384,
                          requested_fields: Sequence[str] | None = None) -> dict[str, Any]:
    """Create a bounded I/O request without opening the trajectory."""
    if isinstance(particle_stop, bool) or not isinstance(particle_stop, int) or particle_stop < 1:
        raise NativeReplayBindingError("particle_stop must be a positive integer")
    particle_stop = min(particle_stop, int(case.row["particles"]))
    fields = tuple(requested_fields or (
        "particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass",
        "time", "valid", "type", "position", "velocity", "mass"))
    allowed = {"particle_id", "particle_zone", "initial_type", "initial_mk", "initial_mass",
               "time", "valid", "type", "position", "velocity", "mass"}
    if not fields or any(field not in allowed for field in fields):
        raise NativeReplayBindingError("initial-frame fields contain an unsupported name")
    # dtype sizes are the real CURRENT header values; this estimate is only a
    # scheduler bound and is not a data result.
    dtype_bytes = {"particle_id": 4, "particle_zone": 2, "initial_type": 1,
                   "initial_mk": 2, "initial_mass": 4, "time": 8, "valid": 1,
                   "type": 1, "position": 12, "velocity": 12, "mass": 4}
    estimated = sum(dtype_bytes[field] * (1 if field == "time" else particle_stop)
                    for field in fields)
    return {
        "schema": INITIAL_FRAME_REQUEST_SCHEMA,
        "physical_case_id": case.physical_case_id,
        "family_id": case.family_id,
        "current_manifest_sha256": case.catalog.sha256,
        "current_case_row_sha256": case.row_sha256,
        "trajectory": _trajectory_ref(case),
        "frame_range": [0, 1],
        "particle_range": [0, particle_stop],
        "fields": list(fields),
        "estimated_bytes": estimated,
        "scope": "bounded initial-frame identity/units/mass check; sample unless particle_stop equals particles",
        "approval": "PENDING_PARENT_STAGE2GUARD_IO_SLOT",
        "read_status": "NOT_READ",
        "model_invoked": False,
        "qualification_status": "UNKNOWN",
    }


def read_initial_frame(case: CurrentCase, *, io_slot_approved: bool = False,
                       frame_stop: int = 1, particle_stop: int = 16384,
                       fields: Sequence[str] | None = None) -> dict[str, Any]:
    """Read a bounded initial frame only after an explicit parent grant.

    The grant is intentionally an argument rather than an ambient environment
    variable, so a metadata-only probe cannot accidentally consume a science
    slot.  Validation remains separate from label qualification.
    """
    if not io_slot_approved:
        raise NativeReplayBindingError(
            "initial-frame HDF5 read requires an explicit parent stage2guard I/O slot")
    from ds_data02_stage2_consumers_v4 import read_case_window  # local import keeps metadata probe light

    if frame_stop != 1:
        raise NativeReplayBindingError("initial-frame interface accepts frame_stop=1 only")
    result = read_case_window(case, frame_start=0, frame_stop=frame_stop,
                              particle_start=0, particle_stop=particle_stop,
                              fields=fields or ("particle_id", "particle_zone", "initial_type",
                                                 "initial_mk", "initial_mass", "time", "valid",
                                                 "type", "position", "velocity", "mass"))
    ids = result["particle_id"]
    zones = result["particle_zone"]
    if len(ids) != len(set(zip(zones.tolist(), ids.tolist()))):
        raise NativeReplayBindingError("initial-frame sample has duplicate (Zone,Idp) identities")
    if not all(math.isfinite(float(value)) for value in result["initial_mass"]):
        raise NativeReplayBindingError("initial-frame sample has non-finite initial mass")
    return {
        "schema": "ds02.stage2.initial-frame-observation.v1",
        "physical_case_id": case.physical_case_id,
        "frame": 0,
        "particle_count": len(ids),
        "particle_range": [0, particle_stop],
        "fields": sorted(result.keys()),
        "validation": {"identity_key": "(Zone,Idp)", "unique_identity": True,
                        "initial_mass_finite": True},
        "read_status": "READ_AFTER_APPROVED_IO_SLOT",
        "qualification_status": "UNKNOWN",
        "model_invoked": False,
    }


FIRST_PASSAGE_STATUSES = (
    "observed",
    "right_censored",
    "failed_before_observation",
    "initially_inside",
    "ambiguous_multiple_crossing",
)


def _finite_scalar(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise NativeReplayBindingError(f"{name} must be a finite number")
    return float(value)


def _saved_brackets(value: Any) -> list[list[float]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise NativeReplayBindingError("saved_brackets must be a list of [t0,t1] pairs")
    brackets: list[list[float]] = []
    for index, pair in enumerate(value):
        if not isinstance(pair, Sequence) or len(pair) != 2:
            raise NativeReplayBindingError(f"saved_brackets[{index}] must contain two times")
        left, right = _finite_scalar(pair[0], f"saved_brackets[{index}][0]"), _finite_scalar(pair[1], f"saved_brackets[{index}][1]")
        if not right > left:
            raise NativeReplayBindingError(f"saved_brackets[{index}] must be strictly increasing")
        brackets.append([left, right])
    return brackets


def classify_first_passage(*, initially_inside: bool = False,
                           saved_brackets: Sequence[Sequence[float]] | None = None,
                           crossing_times_s: Sequence[float] | None = None,
                           failed_before_observation: bool = False,
                           ambiguous_multiple_crossing: bool = False,
                           event_time_s: float | None = None,
                           hidden_recross_status: str = "UNRESOLVED") -> dict[str, Any]:
    """Return an explicit first-passage state with no binary censor collapse.

    ``saved_brackets`` are always retained.  A non-observed state has no
    numeric event time; callers must not encode censoring as zero.  The
    ambiguous state is used when more than one crossing candidate belongs to
    the first saved interval or an independent audit says that ordering is
    unresolved.  Crossings in later intervals remain a separate repeated
    crossing observation and do not silently rewrite first passage.
    """
    if not isinstance(initially_inside, bool) or not isinstance(failed_before_observation, bool):
        raise NativeReplayBindingError("first-passage flags must be booleans")
    brackets = _saved_brackets(saved_brackets)
    crossing_times = [] if crossing_times_s is None else [
        _finite_scalar(value, "crossing_times_s") for value in crossing_times_s
    ]
    if any(not isinstance(value, bool) for value in [ambiguous_multiple_crossing]):
        raise NativeReplayBindingError("ambiguous_multiple_crossing must be boolean")
    if hidden_recross_status not in ("UNRESOLVED", "AUDITED_NONE", "AUDITED_PRESENT"):
        raise NativeReplayBindingError("unsupported hidden_recross_status")
    if initially_inside:
        status = "initially_inside"
    elif ambiguous_multiple_crossing or len(crossing_times) > 1 and not brackets:
        status = "ambiguous_multiple_crossing"
    elif crossing_times:
        status = "observed"
    elif failed_before_observation:
        status = "failed_before_observation"
    else:
        status = "right_censored"

    if status == "observed":
        if event_time_s is None:
            raise NativeReplayBindingError("observed first passage requires event_time_s")
        event_time = _finite_scalar(event_time_s, "event_time_s")
        if not brackets:
            raise NativeReplayBindingError("observed first passage requires its saved bracket")
        if not (brackets[0][0] <= event_time <= brackets[0][1]):
            raise NativeReplayBindingError("event_time_s is outside the first saved bracket")
    else:
        if event_time_s is not None:
            raise NativeReplayBindingError(f"{status} must not carry a numeric event time")
        event_time = None
    return {
        "status": status,
        "event_time_s": event_time,
        "event_time_interval_s": brackets[0] if brackets else None,
        "saved_brackets": brackets,
        "crossing_candidate_times_s": crossing_times,
        "hidden_recross_status": hidden_recross_status,
        "first_passage_numeric_observed": status == "observed",
    }


def _flatten_numbers(value: Any, name: str) -> list[float]:
    if isinstance(value, bool):
        raise NativeReplayBindingError(f"{name} contains a boolean")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise NativeReplayBindingError(f"{name} contains a non-finite value")
        return [float(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        flattened: list[float] = []
        for item in value:
            flattened.extend(_flatten_numbers(item, name))
        return flattened
    raise NativeReplayBindingError(f"{name} must be a finite numeric array")


def _binding_digest_map(bindings: Any, name: str) -> dict[str, str]:
    if not isinstance(bindings, Mapping):
        raise NativeReplayBindingError(f"{name}.bindings is required")
    result: dict[str, str] = {}
    for key, value in bindings.items():
        if not isinstance(key, str) or not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise NativeReplayBindingError(f"{name}.bindings.{key} must be a SHA-256 digest")
        result[key] = value
    return result


def _event_identity(record: Mapping[str, Any], name: str) -> tuple[str, int, int]:
    event_id = record.get("event_id")
    zone, idp = record.get("zone"), record.get("idp")
    if (not isinstance(event_id, str) or not event_id
            or isinstance(zone, bool) or not isinstance(zone, int)
            or isinstance(idp, bool) or not isinstance(idp, int)):
        raise NativeReplayBindingError(f"{name} requires event_id and typed (zone,idp)")
    return event_id, zone, idp


def evaluate_manual_predictions(reference: Mapping[str, Any],
                                prediction: Mapping[str, Any]) -> dict[str, Any]:
    """Score manually supplied macro/event predictions without a model.

    The reference and prediction carry the same source/config/catalog digests
    and typed event identities.  Initial project budgets are explicit here:
    position 2%, mass fractions 3 percentage points, event time 1%, with the
    time/output budget consuming at most one quarter of each total.  A fixed
    nonzero reference scale is mandatory for continuous observables.  Passing
    this report is a development observable check and leaves Q-I/Q-N/Q-E
    UNKNOWN.
    """
    if not isinstance(reference, Mapping) or reference.get("schema") != (
            "ds02.stage2.manual-observation-reference.v1"):
        raise NativeReplayBindingError("unsupported manual observation reference schema")
    if not isinstance(prediction, Mapping) or prediction.get("schema") != (
            "ds02.stage2.manual-observation-predictions.v1"):
        raise NativeReplayBindingError("unsupported manual observation prediction schema")
    expected_bindings = _binding_digest_map(reference.get("bindings"), "reference")
    actual_bindings = _binding_digest_map(prediction.get("bindings"), "prediction")
    binding_checks = []
    for key, expected in sorted(expected_bindings.items()):
        actual = actual_bindings.get(key)
        passed = actual == expected
        binding_checks.append({"name": f"binding.{key}", "status": "PASS" if passed else "FAIL",
                               "expected": expected, "actual": actual})
    failures = [item["name"] for item in binding_checks if item["status"] != "PASS"]

    reference_macros = reference.get("macros", {})
    prediction_macros = prediction.get("macros", {})
    if not isinstance(reference_macros, Mapping) or not isinstance(prediction_macros, Mapping):
        raise NativeReplayBindingError("manual observations require macro mappings")
    macro_checks: list[dict[str, Any]] = []
    total_tolerance_by_kind = {"position": 0.02, "velocity": 0.05,
                               "kinetic_energy": 0.05, "mass_fraction": 0.03,
                               "net_flux_fraction": 0.03}
    for name, spec in sorted(reference_macros.items()):
        if not isinstance(spec, Mapping):
            raise NativeReplayBindingError(f"reference macro {name} is not an object")
        kind = spec.get("kind")
        if kind not in total_tolerance_by_kind:
            raise NativeReplayBindingError(f"reference macro {name} has unsupported kind")
        scale = _finite_scalar(spec.get("reference_scale"), f"reference macro {name}.reference_scale")
        if scale <= 0:
            raise NativeReplayBindingError(f"reference macro {name} requires a fixed nonzero scale")
        reference_values = _flatten_numbers(spec.get("values"), f"reference macro {name}.values")
        predicted_values = _flatten_numbers(prediction_macros.get(name), f"prediction macro {name}")
        if len(reference_values) != len(predicted_values) or not reference_values:
            raise NativeReplayBindingError(f"macro {name} reference/prediction shape differs")
        total_tolerance = float(spec.get("total_tolerance", total_tolerance_by_kind[kind]))
        if not math.isfinite(total_tolerance) or total_tolerance <= 0:
            raise NativeReplayBindingError(f"macro {name}.total_tolerance must be positive")
        budget_fraction = float(spec.get("budget_fraction", 0.25))
        if not math.isfinite(budget_fraction) or not (0 < budget_fraction <= 0.25):
            raise NativeReplayBindingError(f"macro {name}.budget_fraction must be in (0,0.25]")
        errors = [abs(actual - expected) for actual, expected in zip(predicted_values, reference_values)]
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors)) / scale
        maximum = max(errors) / scale
        limit = total_tolerance * budget_fraction
        passed = rmse <= limit and maximum <= total_tolerance
        check = {"name": f"macro.{name}", "status": "PASS" if passed else "FAIL",
                 "kind": kind, "rmse_normalized": rmse, "max_normalized": maximum,
                 "reference_scale": scale, "total_tolerance": total_tolerance,
                 "budget_fraction": budget_fraction, "budget_limit": limit}
        macro_checks.append(check)
        if not passed:
            failures.append(check["name"])

    reference_events = reference.get("events", [])
    prediction_events = prediction.get("events", [])
    if not isinstance(reference_events, list) or not isinstance(prediction_events, list):
        raise NativeReplayBindingError("manual observations require event lists")
    expected_by_id: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    actual_by_id: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    for index, record in enumerate(reference_events):
        if not isinstance(record, Mapping):
            raise NativeReplayBindingError(f"reference event {index} is not an object")
        identity = _event_identity(record, f"reference event {index}")
        if identity in expected_by_id:
            raise NativeReplayBindingError(f"duplicate reference event identity {identity}")
        if record.get("status") not in FIRST_PASSAGE_STATUSES:
            raise NativeReplayBindingError(f"reference event {index} has unsupported status")
        expected_by_id[identity] = record
    for index, record in enumerate(prediction_events):
        if not isinstance(record, Mapping):
            raise NativeReplayBindingError(f"prediction event {index} is not an object")
        identity = _event_identity(record, f"prediction event {index}")
        if identity in actual_by_id:
            raise NativeReplayBindingError(f"duplicate prediction event identity {identity}")
        if record.get("status") not in FIRST_PASSAGE_STATUSES:
            raise NativeReplayBindingError(f"prediction event {index} has unsupported status")
        actual_by_id[identity] = record
    if set(expected_by_id) != set(actual_by_id):
        failures.append("event.identity_axis")
    event_checks: list[dict[str, Any]] = []
    for identity in sorted(set(expected_by_id) | set(actual_by_id)):
        expected, actual = expected_by_id.get(identity), actual_by_id.get(identity)
        if expected is None or actual is None:
            event_checks.append({"name": f"event.{identity}.identity", "status": "FAIL"})
            continue
        status_equal = expected.get("status") == actual.get("status")
        event_check: dict[str, Any] = {"name": f"event.{identity}",
                                        "status": "PASS" if status_equal else "FAIL",
                                        "expected_status": expected.get("status"),
                                        "actual_status": actual.get("status"),
                                        "saved_brackets_retained": actual.get("saved_brackets", [])}
        if not status_equal:
            failures.append(event_check["name"] + ".status")
        status = expected.get("status")
        if status == "observed" and status_equal:
            feature_time = _finite_scalar(expected.get("feature_time_s"), f"event {identity}.feature_time_s")
            if feature_time <= 0:
                raise NativeReplayBindingError(f"event {identity} needs a positive feature_time_s")
            expected_time = _finite_scalar(expected.get("event_time_s"), f"event {identity}.reference_time")
            actual_time = _finite_scalar(actual.get("event_time_s"), f"event {identity}.prediction_time")
            total_fraction = float(expected.get("event_time_tolerance_fraction", 0.01))
            budget_fraction = float(expected.get("budget_fraction", 0.25))
            if not (0 < total_fraction and 0 < budget_fraction <= 0.25):
                raise NativeReplayBindingError(f"event {identity} has invalid tolerance budget")
            relative_error = abs(actual_time - expected_time) / feature_time
            allowed = total_fraction * budget_fraction
            event_check.update(relative_time_error=relative_error,
                               event_time_tolerance_fraction=total_fraction,
                               budget_fraction=budget_fraction,
                               budget_limit=allowed)
            if relative_error > allowed:
                event_check["status"] = "FAIL"
                failures.append(event_check["name"] + ".time")
        elif status != "observed" and actual.get("event_time_s") is not None:
            event_check["status"] = "FAIL"
            event_check["reason"] = "non_observed_event_has_numeric_time"
            failures.append(event_check["name"] + ".numeric_censor")
        event_checks.append(event_check)

    return {
        "schema": "ds02.stage2.manual-observation-evaluation.v1",
        "status": "PASS_DEVELOPMENT_OBSERVABLES" if not failures else "FAIL_DEVELOPMENT_OBSERVABLES",
        "failures": sorted(set(failures)),
        "binding_checks": binding_checks,
        "macro_checks": macro_checks,
        "event_checks": event_checks,
        "event_statuses": list(FIRST_PASSAGE_STATUSES),
        "project_budget_reference": {
            "position": "2% normalized total target; max error reported separately",
            "mass_fraction": "3 percentage points absolute total target",
            "event_time": "1% of fixed nonzero feature time total target",
            "time_and_output_budget": "each checked budget is at most one quarter of its total target",
        },
        "model_invoked": False,
        "hidden_test": False,
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
        "scope": "manual prediction scoring for registered observables; no model or scientific qualification",
    }


def _load_conversion_and_owner(bindings: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None,
                                                                      Mapping[str, Any] | None]:
    small = bindings.get("small_files", {})
    source = small.get("manifest_source_bindings", {})
    current_source = small.get("current_source_bindings", {})
    conversion = _first_json_binding(source, "conversion_report")
    owner = _first_json_binding(source, "owner_metadata")
    if conversion is None:
        conversion = _first_json_binding(current_source, "conversion_report")
    if owner is None:
        owner = _first_json_binding(current_source, "owner_metadata")
    return conversion, owner


def _validate_scan_sidecar(case: CurrentCase, scan_binding: Mapping[str, Any],
                           scan: Mapping[str, Any]) -> dict[str, Any]:
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise NativeReplayBindingError(f"{case.physical_case_id}: unsupported scientific scan schema")
    if scan.get("physical_case_id") != case.physical_case_id:
        raise NativeReplayBindingError(f"{case.physical_case_id}: scientific scan case identity differs")
    scan_path = case.catalog.mapper.resolve(str(scan.get("trajectory", "")))
    current_path = case.trajectory_path()
    if scan_path != current_path:
        raise NativeReplayBindingError(f"{case.physical_case_id}: scientific scan trajectory differs from CURRENT")
    trajectory = case.row["trajectory"]
    if scan.get("source_bytes") != trajectory.get("bytes") or scan.get("source_mtime_ns") != trajectory.get("mtime_ns"):
        raise NativeReplayBindingError(f"{case.physical_case_id}: scientific scan source stat differs from CURRENT")
    if not scan.get("full_saved_timeline_scanned"):
        raise NativeReplayBindingError(f"{case.physical_case_id}: scientific scan is not full saved timeline")
    return {
        "binding": dict(scan_binding),
        "schema": scan.get("schema"),
        "physical_case_id": scan.get("physical_case_id"),
        "frames": scan.get("frames"),
        "particles": scan.get("particles"),
        "full_saved_timeline_scanned": True,
        "scan_status": scan.get("scan_status"),
        "raw_native_alignment": scan.get("raw_native_alignment", "UNKNOWN"),
        "QI_dynamics": scan.get("QI_dynamics", "UNKNOWN"),
        "QN": scan.get("QN", "UNKNOWN"),
        "QE": scan.get("QE", "UNKNOWN"),
        "qualification_status": "UNKNOWN",
    }


def _native_exclusion_record(case: CurrentCase, conversion: Mapping[str, Any] | None,
                             source_bindings: Mapping[str, Any]) -> dict[str, Any]:
    """Expose exclusion evidence without treating RunPARTs as an exclusion ledger."""
    candidates = []
    raw = case.row.get("raw_root")
    if isinstance(raw, Mapping) and raw.get("path"):
        data_root = case.path(str(raw["path"]))
        runparts = data_root.parent / "RunPARTs.csv"
        if runparts.is_file():
            candidates.append(_path_ref(runparts, role="native_runtime_RunPARTs.csv"))
    report_ledger = None
    if isinstance(conversion, Mapping):
        typed_identity = conversion.get("typed_identity")
        if isinstance(typed_identity, Mapping):
            report_ledger = typed_identity.get("initial_exclusion_ledger")
    # CURRENT F2-S1 has no exact native-exclusion-ledger.json.  Never borrow
    # the F2H10V2 ledger, even though it has the same family and dimensions.
    return {
        "schema": "ds02.stage2.native-exclusion-binding.v1",
        "physical_case_id": case.physical_case_id,
        "status": "UNAVAILABLE_EXACT_CASE",
        "sidecar_path": None,
        "candidate_policy": "cross-case native-exclusion ledgers are rejected",
        "runtime_accounting": candidates,
        "conversion_initial_exclusion_ledger": report_ledger,
        "semantics": "RunPARTs.csv and conversion initial ledger are evidence only; no native exclusion sidecar is asserted",
        "qualification_status": "UNKNOWN",
    }


def build_native_replay_bundle(catalog: Current336Catalog, config: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the configured real case and produce a portable internal bundle."""
    if config.get("schema") != "ds02.stage2.native-replay-request.v5":
        raise NativeReplayBindingError("unsupported native replay request schema")
    case_id = config.get("physical_case_id")
    if not isinstance(case_id, str) or not case_id:
        raise NativeReplayBindingError("native replay request requires physical_case_id")
    case = catalog.case(case_id)
    expected_catalog = config.get("current_manifest_sha256")
    if expected_catalog and expected_catalog != catalog.sha256:
        raise NativeReplayBindingError("native replay request CURRENT hash differs")
    manifest, bindings = _manifest_and_bindings(case)
    small = bindings["small_files"]
    generated = small["current_source_bindings"].get("generated_xml")
    if not isinstance(generated, Mapping):
        raise NativeReplayBindingError(f"{case_id}: generated XML binding is missing")
    xml_control = _declared_xml_files(case, generated)
    conversion, owner = _load_conversion_and_owner(bindings)

    scan_cfg = config.get("scientific_scan")
    if not isinstance(scan_cfg, Mapping):
        raise NativeReplayBindingError("scientific_scan binding is required")
    scan_path = scan_cfg.get("path")
    if not isinstance(scan_path, str):
        raise NativeReplayBindingError("scientific_scan.path is required")
    scan_binding = _bind_spec(case, "F2-S1 scientific scan", {"path": scan_path,
                                                              "sha256": scan_cfg.get("sha256")})
    scan = read_json(scan_binding["path"])
    if not isinstance(scan, Mapping):
        raise NativeReplayBindingError("scientific scan sidecar is not an object")
    scan_record = _validate_scan_sidecar(case, scan_binding, scan)

    lineage = audit_current_lineage(catalog)
    initial = initial_frame_request(case,
                                    particle_stop=int(config.get("initial_frame", {}).get("particle_stop", 16384)))
    source_scopes = _source_scope_record(case, manifest, conversion, owner)
    exclusion = _native_exclusion_record(case, conversion,
                                         small.get("current_source_bindings", {}))
    return {
        "schema": NATIVE_REPLAY_SCHEMA,
        "request_schema": config["schema"],
        "current_manifest_sha256": catalog.sha256,
        "current_source_catalog_sha256": catalog.payload.get("source_catalog_sha256"),
        "physical_case_id": case.physical_case_id,
        "family_id": case.family_id,
        "manifest_case_id": manifest.get("case_id"),
        "case_row_sha256": case.row_sha256,
        "source_identity_scopes": source_scopes,
        "trajectory": _trajectory_ref(case),
        "manifest": manifest,
        "bound_dependencies": {
            "small_files": small,
            "generated_xml_control": xml_control,
            "scientific_scan": scan_record,
            "native_exclusion": exclusion,
        },
        "initial_frame": initial,
        "observation_definition": config.get("observation_definition", {}),
        "first_passage_statuses": list(FIRST_PASSAGE_STATUSES),
        "manual_evaluator": {
            "schema": "ds02.stage2.manual-observation-evaluation.v1",
            "entrypoint": "evaluate_manual_predictions(reference, prediction)",
            "scores": ["typed identity binding", "macro RMSE/max error", "mass fraction error",
                        "event status", "event time error", "saved bracket retention"],
            "qualification_status": "UNKNOWN",
        },
        "tolerance_calibration": config.get("tolerance_calibration", {}),
        "qualification_boundary": config.get("qualification_boundary", {}),
        "lineage_audit": lineage,
        "resource_plan": config.get("resource_plan", {}),
        "role": "DEVELOPMENT",
        "hidden_test": False,
        "model_invoked": False,
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
        "read_scope_status": "METADATA_ONLY_PENDING_PARENT_IO_SLOT",
    }


def _dump_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_current_catalog(args.catalog)
    request = read_json(args.request)
    if not isinstance(request, Mapping):
        raise NativeReplayBindingError("request is not an object")
    bundle = build_native_replay_bundle(catalog, request)
    _dump_json(args.output, bundle)
    print(json.dumps({"schema": NATIVE_REPLAY_SCHEMA,
                      "output": str(args.output.resolve()),
                      "output_sha256": sha256(args.output),
                      "physical_case_id": bundle["physical_case_id"],
                      "lineage_rows": bundle["lineage_audit"]["rows"],
                      "read_scope_status": bundle["read_scope_status"],
                      "quality": bundle["quality"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
