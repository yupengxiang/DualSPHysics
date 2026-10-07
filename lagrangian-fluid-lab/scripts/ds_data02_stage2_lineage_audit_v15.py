#!/usr/bin/env python3
"""Audit effective source conditions for CURRENT336.

The v13 audit records the per-case XML and metadata closure.  This version
adds the execution evidence that is needed to reason about a *condition*:
the exact solver command, semantic CLI flags, GenCase input/output relation,
and the content and time coverage of motion or acceleration assets.  Paths,
case names, particle counts, ``dp``, save windows, and other discretisation
choices are deliberately kept out of the effective-condition key.

Only CURRENT336 and small source files are read.  Trajectory HDF5 files are
stat'ed and never opened or hashed.  The result is a development audit.  It
does not make a qualification or split-safety claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import ds_data02_stage2_lineage_audit_v13 as v13


AUDIT_SCHEMA = "ds02.stage2.current336-effective-lineage-audit.v15"
CARD_SCHEMA = "ds02.stage2.family-card.v15"
DEFAULT_CURRENT = v13.DEFAULT_CURRENT
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/lineage/v15"
DEPENDENCY_INDEX = Path(__file__).resolve().parents[1] / (
    "campaigns/ds-data-02/stage2/replay/v13/READER_DEPENDENCY_LICENSE_INDEX_v13.json"
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
H5_SUFFIXES = {".h5", ".hdf5"}
ASSET_SUFFIXES = {".dat", ".csv"}


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and len(value) <= 48 and all(
        isinstance(item, (str, int, float, bool)) or item is None for item in value
    ):
        return value
    return None


_IDENTITY_WORDS = {
    "case_id", "physical_case_id", "runtime_case_alias", "manifest_physical_case_id",
    "runtime_id", "run_id", "request_id", "scope_id", "candidate_id",
}
_NUMERICAL_WORDS = {
    "dp", "resolution", "particle", "particles", "count", "frame", "frames",
    "save", "output", "window", "tout", "tmax", "time_max", "time_out",
    "runtime", "threads", "gpu", "batch", "chunk", "stride", "sample",
}


def _key_has_word(key: str, words: set[str]) -> bool:
    lower = re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)).lower()
    tokens = set(re.split(r"[^a-z0-9]+", lower))
    return bool(tokens & words) or any(
        lower.startswith(word + "_") or lower.endswith("_" + word)
        for word in words
    )


def _scrub_physical(value: Any, *, key: str = "", drop_paths: bool = True) -> Any:
    """Remove run identity and numerical/discrete details from a binding."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(raw_key)
            lower = name.lower()
            if lower in _IDENTITY_WORDS or _key_has_word(name, _IDENTITY_WORDS):
                continue
            if drop_paths and (lower.endswith("_path") or lower in {"path", "raw_bi4_root", "output_root"}):
                continue
            if "sha256" in lower:
                continue
            if _key_has_word(name, _NUMERICAL_WORDS):
                # A physical duration/amplitude is meaningful, while a saved
                # window or a discretisation token is not.
                if not lower.endswith(("duration_s", "active_window_s", "hold_start_s")):
                    continue
            cleaned = _scrub_physical(item, key=name, drop_paths=drop_paths)
            if cleaned is not None:
                result[name] = cleaned
        return result
    if isinstance(value, list):
        return [_scrub_physical(item, key=key, drop_paths=drop_paths) for item in value]
    if isinstance(value, tuple):
        return [_scrub_physical(item, key=key, drop_paths=drop_paths) for item in value]
    return _scalar(value)


def _scrub_xml_nodes(nodes: Any) -> Any:
    """Keep continuous XML geometry/control semantics without dp/lattice attrs."""
    if not isinstance(nodes, list):
        return []
    result: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        attrs = {}
        for key, value in sorted((node.get("attrs") or {}).items()):
            lower = str(key).lower()
            if lower in {"dp", "layers", "layer", "count", "n", "np", "mk", "mkfluid"}:
                # MK is a material label in the owner binding; an XML draw
                # token is kept only through the element text below.
                continue
            if _key_has_word(str(key), {"resolution", "particle", "sample", "save"}):
                continue
            attrs[str(key)] = value
        item: dict[str, Any] = {"tag": node.get("tag"), "attrs": attrs}
        if isinstance(node.get("text"), str) and node["text"].strip():
            item["text"] = node["text"].strip()
        result.append(item)
    return result


def _owner_physical_payload(owner: Mapping[str, Any], case: Mapping[str, Any], xml: Mapping[str, Any]) -> dict[str, Any]:
    """Extract physical evidence without treating an owner filename as physics."""
    candidates: dict[str, Any] = {}
    for key in (
        "physical_binding", "source_canonical_physical_binding", "source_plan_binding",
        "continuum_geometry", "geometry", "initial_state", "parameters",
        "parameter_tuple", "source_parameter_tuple", "controls", "gravity_m_s2",
        "density_kg_m3", "mass_policy", "mechanism_id", "geometry_family_id",
        "control_family_id",
    ):
        if key in owner:
            candidates[key] = owner[key]
    # A few owners put the actual binding below a source/physical-binding
    # object.  The named walk is intentionally bounded and never includes IDs.
    if not candidates.get("physical_binding"):
        for key in ("physical_binding", "canonical_physical_binding", "source_canonical_physical_binding"):
            nested = owner.get("physical_binding", {}) if key == "physical_binding" else owner.get(key)
            if isinstance(nested, Mapping):
                candidates[key] = nested
    catalog_numeric = case.get("known_numeric_physical_parameters", {})
    if isinstance(catalog_numeric, Mapping):
        candidates["catalog_continuous_parameters"] = {
            str(key): value for key, value in catalog_numeric.items()
            if not _key_has_word(str(key), _NUMERICAL_WORDS)
            and isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    candidates["xml_geometry_nodes"] = _scrub_xml_nodes(xml.get("geometry_nodes", []))
    candidates["xml_control_class"] = xml.get("control_class")
    return _scrub_physical(candidates)


def _selected_hashes(owner: Mapping[str, Any]) -> dict[str, list[str]]:
    selected = owner.get("selected_values", {})
    if not isinstance(selected, Mapping):
        return {}
    names = {
        "physical_condition_sha256", "source_physical_condition_sha256",
        "source_plan_physical_condition_sha256", "canonical_physical_binding_sha256",
        "source_plan_sha256", "source_definition_sha256", "base_asset_sha256",
    }
    return {
        key: sorted({str(item) for item in selected.get(key, []) if isinstance(item, str) and HASH_RE.fullmatch(item)})
        for key in sorted(names)
    }


def _numeric_parameters(case: Mapping[str, Any]) -> dict[str, Any]:
    value = case.get("known_numeric_physical_parameters", {})
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item for key, item in sorted(value.items())
        if isinstance(item, (int, float)) and not isinstance(item, bool)
        and not _key_has_word(str(key), _NUMERICAL_WORDS)
    }


def _command_input_path(command: list[str], receipt: Mapping[str, Any]) -> str | None:
    output_root = str(receipt.get("output_root", ""))
    for token in command[1:]:
        if not isinstance(token, str) or token.startswith("-"):
            continue
        if output_root and token.startswith(output_root):
            continue
        if token.endswith((".xml", ".dat", ".csv", ".json", ".bi4")):
            continue
        if "/" in token:
            return token
    return None


def _cli_value(token: str) -> tuple[str, str | None] | None:
    if not isinstance(token, str) or not token.startswith("-"):
        return None
    body = token[1:]
    if ":" in body:
        key, value = body.split(":", 1)
        return key.lower(), value
    return body.lower(), None


def parse_solver_command(receipt: Mapping[str, Any]) -> dict[str, Any]:
    command = receipt.get("command", [])
    if not isinstance(command, list) or not command:
        command = []
    flags: list[dict[str, Any]] = []
    semantic: list[dict[str, Any]] = []
    numeric: dict[str, float] = {}
    ignored = {"gpu", "tmax", "tout", "ompthreads", "threads", "cpu", "device"}
    for token in command[1:]:
        parsed = _cli_value(token)
        if parsed is None:
            continue
        key, value = parsed
        item = {"key": key, "value": value}
        flags.append(item)
        if key in {"tmax", "tout"}:
            number = _finite_float(value)
            if number is not None:
                numeric[f"{key}_s"] = number
        if key not in ignored:
            semantic.append(item)
    prepared = _command_input_path([str(item) for item in command], receipt)
    return {
        "command": [str(item) for item in command],
        "command_sha256": digest([str(item) for item in command]),
        "prepared_input_path": prepared,
        "cli_overrides": flags,
        "semantic_cli_overrides": semantic,
        "solver_tmax_s": numeric.get("tmax_s"),
        "solver_tout_s": numeric.get("tout_s"),
        "ignored_for_effective_condition": sorted(ignored),
        "status": "EXACT_RECEIPT_COMMAND_RECORDED",
    }


def _is_asset(path: str, family: str) -> bool:
    name = Path(path).name.lower()
    if Path(path).suffix.lower() not in ASSET_SUFFIXES:
        return False
    if family == "F3":
        return name == "casesloshingaccdata.csv" or "acc" in name
    return "motion" in name


def _asset_candidates(receipt: Mapping[str, Any], family: str, prepared: str | None) -> list[dict[str, Any]]:
    hashes = receipt.get("input_hashes_at_launch", {})
    if not isinstance(hashes, Mapping):
        return []
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    prepared_prefix = str(prepared or "")
    for raw_path, raw_hash in hashes.items():
        path = str(raw_path)
        declared = str(raw_hash)
        if not _is_asset(path, family):
            continue
        key = (path, declared)
        unique[key] = {
            "path": path,
            "declared_sha256": declared,
            "case_local": bool(prepared_prefix and path.startswith(prepared_prefix)),
        }
    values = list(unique.values())
    local = [item for item in values if item["case_local"]]
    return local or values


def _split_values(line: str) -> list[str]:
    if ";" in line:
        return [item.strip() for item in line.split(";")]
    if "\t" in line:
        return [item.strip() for item in line.split("\t")]
    return [item for item in re.split(r"\s+", line.strip()) if item]


def parse_control_asset(path: Path | str, *, declared_sha256: str | None = None,
                        solver_tmax_s: float | None = None,
                        receipt_status: str | None = None,
                        launch_hash_supported: bool = False,
                        finish_hash_supported: bool = False) -> dict[str, Any]:
    """Read a small motion/acceleration table and report explicit coverage."""
    path = Path(path)
    record: dict[str, Any] = {
        "path": str(path),
        "declared_sha256": declared_sha256,
        "receipt_status": receipt_status,
        "launch_hash_supported": launch_hash_supported,
        "finish_hash_supported": finish_hash_supported,
    }
    if not path.is_file():
        record.update({"status": "MISSING_FILE", "content_sha256": None})
        return record
    actual = sha256(path)
    record["content_sha256"] = actual
    record["bytes"] = path.stat().st_size
    record["content_hash_status"] = "HASH_MATCH" if actual == declared_sha256 else "HASH_MISMATCH"
    comments: list[str] = []
    header: list[str] | None = None
    times: list[float] = []
    first_values: list[float] | None = None
    last_values: list[float] | None = None
    malformed = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                text = line.strip()
                if not text:
                    continue
                if text.startswith("#"):
                    if len(comments) < 12:
                        comments.append(text)
                    header_text = text.lstrip("#").strip()
                    if header_text.lower().startswith("time") and (";" in header_text or "\t" in header_text):
                        header = _split_values(header_text)
                    elif "columns:" in header_text.lower():
                        candidate = header_text.split(":", 1)[1].strip()
                        if candidate:
                            header = _split_values(candidate)
                    continue
                fields = _split_values(text)
                if not fields:
                    continue
                time = _finite_float(fields[0])
                values = [_finite_float(item) for item in fields[1:]]
                if time is None or not values or any(item is None for item in values):
                    malformed += 1
                    continue
                times.append(time)
                numeric_values = [float(item) for item in values if item is not None]
                if first_values is None:
                    first_values = numeric_values
                last_values = numeric_values
    except OSError as error:
        record.update({"status": "READ_ERROR", "error": str(error)})
        return record
    deltas = [right - left for left, right in zip(times, times[1:])]
    strictly_increasing = bool(times) and all(delta > 0 for delta in deltas)
    coverage = [times[0], times[-1]] if times else None
    if solver_tmax_s is None or coverage is None:
        coverage_status = "SOLVER_TMAX_UNKNOWN_OR_ASSET_EMPTY"
    elif coverage[1] + 1e-12 >= solver_tmax_s:
        coverage_status = "COVERS_SOLVER_TMAX"
    else:
        coverage_status = "CONTROL_ASSET_END_BEFORE_SOLVER_TMAX"
    units: dict[str, str] = {"time": "s"}
    lower_header = [str(item).lower() for item in (header or [])]
    if any("degree" in item for item in lower_header) or any("angle(deg" in item for item in comments):
        units["value"] = "degrees"
    if any("linearacc" in item for item in lower_header):
        units.update({"LinearAcc*": "m/s^2", "AngularAcc*": "rad/s^2"})
    record.update({
        "status": "PARSED_MONOTONIC_TABLE" if strictly_increasing and not malformed else "PARSED_WITH_WARNINGS",
        "header": header,
        "comments": comments,
        "row_count": len(times),
        "malformed_row_count": malformed,
        "time_coverage_s": coverage,
        "strictly_increasing_time": strictly_increasing,
        "dt_range_s": [min(deltas), max(deltas)] if deltas else None,
        "first_value_columns": first_values,
        "last_value_columns": last_values,
        "units": units,
        "solver_tmax_s": solver_tmax_s,
        "coverage_status": coverage_status,
    })
    return record


def inspect_control_assets(case: Mapping[str, Any], solver: Mapping[str, Any], command: Mapping[str, Any]) -> dict[str, Any]:
    family = str(case.get("family_id"))
    candidates = _asset_candidates(solver, family, command.get("prepared_input_path"))
    launch = solver.get("input_hashes_at_launch", {})
    finish = solver.get("input_hashes_after_run", {})
    assets: list[dict[str, Any]] = []
    for candidate in candidates:
        path = str(candidate["path"])
        declared = str(candidate["declared_sha256"])
        asset = parse_control_asset(
            path,
            declared_sha256=declared,
            solver_tmax_s=command.get("solver_tmax_s"),
            receipt_status=solver.get("status"),
            launch_hash_supported=declared in (set(launch.values()) if isinstance(launch, Mapping) else set()),
            finish_hash_supported=declared in (set(finish.values()) if isinstance(finish, Mapping) else set()),
        )
        asset["case_local"] = bool(candidate.get("case_local"))
        assets.append(asset)
    distinct_hashes = sorted({str(item.get("content_sha256")) for item in assets if item.get("content_sha256")})
    if not candidates:
        status = "NO_EXTERNAL_MOTION_OR_ACCELERATION_ASSET_DECLARED"
    elif any(item.get("content_hash_status") != "HASH_MATCH" for item in assets):
        status = "CONTROL_ASSET_HASH_MISMATCH"
    elif any(item.get("status") in {"MISSING_FILE", "READ_ERROR"} for item in assets):
        status = "CONTROL_ASSET_UNAVAILABLE"
    else:
        status = "HASH_MATCH_AND_PARSED"
    primary = [item for item in assets if item.get("case_local")]
    if len(primary) != 1 and len(assets) == 1:
        primary = assets
    # The solver input path is the authoritative choice when a receipt also
    # records a shared source or an unrelated endpoint asset.
    selected = primary[0] if len(primary) == 1 else None
    return {
        "family": family,
        "asset_kind": "acceleration_table" if family == "F3" else "motion_table" if family in {"F2", "F5", "F7"} else "none",
        "candidate_count": len(candidates),
        "assets": assets,
        "distinct_content_sha256": distinct_hashes,
        "selected": selected,
        "selection_status": "CASE_LOCAL_SOLVER_INPUT_SELECTED" if selected else "AMBIGUOUS_OR_NO_EXTERNAL_ASSET",
        "status": status,
    }


def build_condition_keys(physical_payload: Mapping[str, Any], xml: Mapping[str, Any],
                        command: Mapping[str, Any], asset: Mapping[str, Any]) -> dict[str, Any]:
    """Create the condition keys from source evidence.

    Case names, paths, dp/particle details, and save-window flags must not
    reach either key.  This pure boundary is also used by manufactured tests.
    """
    physical_key_payload = _scrub_physical(physical_payload)
    if not isinstance(physical_key_payload, Mapping):
        physical_key_payload = {}
    physical_key = digest(physical_key_payload)
    selected_asset = asset.get("selected") if isinstance(asset, Mapping) else None
    selected_asset = selected_asset if isinstance(selected_asset, Mapping) else {}
    control_key_payload = {
        "xml_control_class": xml.get("control_class"),
        "xml_control_nodes": _scrub_xml_nodes(xml.get("control_nodes", [])),
        "semantic_cli_overrides": command.get("semantic_cli_overrides", []),
        "control_asset_sha256": selected_asset.get("content_sha256"),
        "control_asset_kind": asset.get("asset_kind"),
        "control_asset_time_coverage_s": selected_asset.get("time_coverage_s"),
        "control_asset_header": selected_asset.get("header"),
    }
    control_key = digest(control_key_payload)
    return {
        "physical_key_sha256": physical_key,
        "physical_key_payload": physical_key_payload,
        "control_key_sha256": control_key,
        "control_key_payload": control_key_payload,
        "effective_key_sha256": digest({"physical_condition_key": physical_key, "control_key": control_key}),
    }


def _physical_key_payload(physical_payload: Mapping[str, Any], *,
                          owner_hashes: Mapping[str, Any] | None = None,
                          manifest_hashes: Iterable[str] = ()) -> dict[str, Any]:
    """Return continuous physical evidence while retaining opaque provenance.

    Canonical owner/manifest hashes are identifiers until their semantics are
    independently audited.  They are deliberately returned as a separate
    provenance object and cannot split the physical key.  The arguments are
    accepted here so callers must make the exclusion explicit.
    """
    del owner_hashes, manifest_hashes
    return {"physical_evidence": physical_payload}


def _run_out_summary(solver: Mapping[str, Any]) -> dict[str, Any]:
    """Bind Run.out to the exact output directory in the recorded command.

    Stage1 receipts use ``output_root`` for the attempt directory while the
    solver command's output argument is ``output_root/solver_output``.  The
    command is the source of truth; this helper never searches a sibling or
    uses a latest/glob fallback.
    """
    output_root = solver.get("output_root")
    command = solver.get("command", [])
    command = [str(item) for item in command] if isinstance(command, list) else []
    prepared = _command_input_path(command, solver)
    output_argument: str | None = None
    if prepared and command.count(prepared) == 1:
        input_position = command.index(prepared)
        for token in command[input_position + 1:]:
            if token and not token.startswith("-"):
                output_argument = token
                break
    if output_argument is None:
        # DualSPHysics' native command contract has two positional path
        # arguments: prepared input prefix followed by solver output dir.
        # Select the latter from this exact command, even when both paths sit
        # below the receipt's attempt output_root.
        positional_paths = [
            token for token in command[1:]
            if token and not token.startswith("-") and ("/" in token or "\\" in token)
        ]
        if len(positional_paths) >= 2:
            output_argument = positional_paths[-1]
    # Some producer receipts expose the positional output explicitly.  These
    # names are still receipt fields, never inferred directory names.
    if output_argument is None:
        for key in ("solver_output_root", "command_output_root", "output_path"):
            value = solver.get(key)
            if isinstance(value, str) and value:
                output_argument = value
                break
    if output_argument is None:
        return {
            "status": "NO_RECEIPT_COMMAND_OUTPUT_ARGUMENT",
            "path": None,
            "command_output_path": None,
            "output_root": output_root,
            "searched_glob": False,
        }
    output_dir = Path(output_argument).expanduser()
    expected = output_dir / "Run.out"
    record = {
        "path": str(expected),
        "command_output_path": str(output_dir),
        "output_root": output_root,
        "source": "receipt.command_exact_output_argument",
        "searched_glob": False,
    }
    if expected.is_file():
        record.update({"status": "FOUND_AT_RECEIPT_COMMAND_OUTPUT", "sha256": sha256(expected)})
    else:
        record["status"] = "MISSING_AT_RECEIPT_COMMAND_OUTPUT"
    return record


def _receipt_hash_status(receipt: Mapping[str, Any], expected_hash: str | None) -> dict[str, Any]:
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    launch_ok = bool(expected_hash and isinstance(launch, Mapping) and expected_hash in launch.values())
    finish_ok = bool(expected_hash and isinstance(finish, Mapping) and expected_hash in finish.values())
    status = receipt.get("status")
    if launch_ok and finish_ok:
        evidence_status = "COMPLETE_LAUNCH_AND_FINISH_HASH_SUPPORT"
    elif launch_ok and status in {"running", "started", None}:
        evidence_status = "INCOMPLETE_RUNNING_NO_FINISH_HASH_SUPPORT"
    elif launch_ok:
        evidence_status = "INCOMPLETE_NO_FINISH_HASH_SUPPORT"
    else:
        evidence_status = "MISSING_GENERATED_XML_HASH_SUPPORT"
    return {
        "status": evidence_status,
        "receipt_status": status,
        "returncode": receipt.get("returncode"),
        "launch_hash_supported": launch_ok,
        "finish_hash_supported": finish_ok,
        "input_hash_count_launch": len(launch) if isinstance(launch, Mapping) else None,
        "input_hash_count_finish": len(finish) if isinstance(finish, Mapping) else None,
    }


def _gencase_evidence(case: Mapping[str, Any], xml_path: Path, xml_sha: str,
                      gencase: Mapping[str, Any]) -> dict[str, Any]:
    launch = gencase.get("input_hashes_at_launch", {})
    finish = gencase.get("input_hashes_after_run", {})
    def input_assets(mapping: Any) -> list[dict[str, Any]]:
        result = []
        if not isinstance(mapping, Mapping):
            return result
        for raw_path, raw_hash in sorted(mapping.items()):
            path = Path(str(raw_path))
            if path.suffix.lower() != ".xml" or not ("def" in path.name.lower() or "definition" in str(path).lower()):
                continue
            result.append({"path": str(path), "declared_sha256": str(raw_hash), "exists": path.is_file(),
                           "content_sha256": sha256(path) if path.is_file() else None,
                           "hash_matches_receipt": path.is_file() and sha256(path) == str(raw_hash)})
        return result
    output_root = Path(str(gencase.get("output_root", "")))
    output_in_root = False
    if xml_path.is_file():
        try:
            output_in_root = xml_path.resolve().is_relative_to(output_root.resolve())
        except (OSError, ValueError):
            output_in_root = False
    output_status = "GENCASE_OUTPUT_XML_HASH_MATCH" if xml_path.is_file() and sha256(xml_path) == xml_sha and output_in_root else "GENCASE_OUTPUT_XML_UNBOUND"
    input_launch = input_assets(launch)
    input_finish = input_assets(finish)
    launch_complete = bool(input_launch) and all(
        item["hash_matches_receipt"] for item in input_launch
    )
    finish_complete = bool(input_finish) and all(
        item["hash_matches_receipt"] for item in input_finish
    )
    launch_assets = {(item["path"], item["declared_sha256"]) for item in input_launch}
    finish_assets = {(item["path"], item["declared_sha256"]) for item in input_finish}
    same_asset_set = bool(launch_assets) and launch_assets == finish_assets
    complete = launch_complete and finish_complete and same_asset_set
    if complete:
        support_status = "COMPLETE_LAUNCH_AND_FINISH_DEFINITION_HASH_SUPPORT"
    elif launch_complete and not input_finish:
        support_status = "LAUNCH_ONLY_NO_FINISH_DEFINITION_HASH_SUPPORT"
    elif launch_complete and finish_complete and not same_asset_set:
        support_status = "LAUNCH_FINISH_DEFINITION_SET_CHANGED"
    elif input_launch or input_finish:
        support_status = "INCOMPLETE_DEFINITION_HASH_SUPPORT"
    else:
        support_status = "NO_DEFINITION_HASH_SUPPORT"
    return {
        "receipt_status": gencase.get("status"),
        "returncode": gencase.get("returncode"),
        "output_root": str(output_root),
        "generated_xml": {
            "path": str(xml_path),
            "catalog_sha256": xml_sha,
            "output_status": output_status,
            "is_under_declared_output_root": output_in_root,
        },
        "input_definition_assets_at_launch": input_launch,
        "input_definition_assets_at_finish": input_finish,
        "input_definition_hash_support_complete": complete,
        "input_definition_hash_support_status": support_status,
        "input_definition_hash_support": {
            "launch_complete": launch_complete,
            "finish_complete": finish_complete,
            "same_asset_set": same_asset_set,
            "finish_map_present": bool(finish),
        },
        "generated_xml_is_output_not_expected_input": True,
        "interpretation": "GenCase Def/geometry input and generated XML output are separate evidence scopes",
    }


def _owner_and_manifest(case: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source = case.get("source_bindings", {})
    owner_binding = source.get("owner_metadata", {})
    manifest_binding = case.get("manifest", {})
    owner_path = Path(str(owner_binding.get("path", ""))).expanduser()
    manifest_path = Path(str(manifest_binding.get("path", ""))).expanduser()
    owner = v13.owner_summary(owner_path) if owner_path.is_file() else {"selected_values": {}, "top_level_keys": []}
    manifest = v13.manifest_summary(manifest_path) if manifest_path.is_file() else {}
    return owner, manifest


def _source_file_status(case: Mapping[str, Any]) -> dict[str, Any]:
    source = case.get("source_bindings", {})
    result: dict[str, Any] = {}
    selected: dict[str, Any] = dict(source) if isinstance(source, Mapping) else {}
    # Manifest is consumed for identity/provenance.  XMF, conversion reports,
    # initial CSVs, and trajectory payloads are intentionally outside this
    # minimal lineage read path unless a future worker binds them explicitly.
    if isinstance(case.get("manifest"), Mapping):
        selected["manifest"] = case["manifest"]
    for role, item in sorted(selected.items()):
        if not isinstance(item, Mapping):
            continue
        path = Path(str(item.get("path", ""))).expanduser()
        expected = item.get("sha256") or item.get("recomputed_sha256")
        if path.suffix.lower() in H5_SUFFIXES:
            result[role] = {"path": str(path), "status": "H5_STAT_ONLY_CONTENT_NOT_READ", "bytes": path.stat().st_size if path.is_file() else None}
            continue
        actual = sha256(path) if path.is_file() else None
        result[role] = {"path": str(path), "declared_sha256": expected, "actual_sha256": actual,
                        "status": "HASH_MATCH" if actual and actual == expected else "HASH_MISMATCH_OR_MISSING"}
    return result


def audit_case(index: int, case: Mapping[str, Any]) -> dict[str, Any]:
    source = case.get("source_bindings", {})
    xml_binding = source.get("generated_xml", {})
    xml_path = Path(str(xml_binding.get("path", ""))).expanduser()
    xml = v13.parse_xml(xml_path)
    xml_sha = str(xml_binding.get("sha256") or xml_binding.get("recomputed_sha256") or "")
    owner, manifest = _owner_and_manifest(case)
    solver_binding = source.get("solver_receipt", {})
    gencase_binding = source.get("gencase_receipt", {})
    solver_path = Path(str(solver_binding.get("path", ""))).expanduser()
    gencase_path = Path(str(gencase_binding.get("path", ""))).expanduser()
    solver = _load_json(solver_path) if solver_path.is_file() else {}
    gencase = _load_json(gencase_path) if gencase_path.is_file() else {}
    command = parse_solver_command(solver)
    asset = inspect_control_assets(case, solver, command)
    receipt_xml = _receipt_hash_status(solver, xml_sha)
    gencase_evidence = _gencase_evidence(case, xml_path, xml_sha, gencase)
    physical_payload = _owner_physical_payload(owner, case, xml)
    owner_hashes = _selected_hashes(owner)
    manifest_hashes = sorted({str(manifest[key]) for key in (
        "physical_condition_sha256", "actual_converter_physical_condition_sha256",
        "canonical_physical_binding_sha256")
        if isinstance(manifest.get(key), str) and HASH_RE.fullmatch(manifest[key])})
    physical_key_payload = _physical_key_payload(
        physical_payload,
        owner_hashes=owner_hashes,
        manifest_hashes=manifest_hashes,
    )
    keys = build_condition_keys(physical_key_payload, xml, command, asset)
    physical_key = keys["physical_key_sha256"]
    control_key = keys["control_key_sha256"]
    effective_key = keys["effective_key_sha256"]
    gencase_support = gencase_evidence.get("input_definition_hash_support_complete")
    source_status = "SMALL_SOURCE_HASH_CLOSURE_COMPLETE"
    if not xml_path.is_file() or not gencase_path.is_file() or not solver_path.is_file():
        source_status = "SMALL_SOURCE_HASH_CLOSURE_INCOMPLETE"
    if not gencase_support:
        source_status += "; GENCASE_INPUT_DEF_SUPPORT_INCOMPLETE_OR_UNDECLARED"
    if receipt_xml.get("status") != "COMPLETE_LAUNCH_AND_FINISH_HASH_SUPPORT":
        source_status += "; SOLVER_RECEIPT_FINISH_SUPPORT_INCOMPLETE"
    run_out = _run_out_summary(solver)
    source_status += "; RUN_OUT_NOT_USED_AS_DISCOVERY" if run_out["status"] != "FOUND_AT_RECEIPT_COMMAND_OUTPUT" else "; RUN_OUT_EXACT_RECEIPT_OUTPUT_RECORDED"
    selected_values = owner.get("selected_values", {}) if isinstance(owner, Mapping) else {}
    mechanisms = {key: values[:12] for key, values in selected_values.items()
                  if key in {"mechanism_id", "geometry_family_id", "control_family_id", "motion_reader"}}
    return {
        "case_index": index,
        "family_id": case.get("family_id"),
        "physical_case_id": case.get("physical_case_id"),
        "runtime_case_alias": case.get("runtime_case_alias"),
        "manifest_physical_case_id": case.get("manifest_physical_case_id"),
        "frames": case.get("frames"),
        "particles": case.get("particles"),
        "actual_time_window_s": case.get("actual_time_window_s"),
        "header": v13._header_summary(case),
        "known_numeric_physical_parameters": _numeric_parameters(case),
        "identity": {
            "key": case.get("header", {}).get("identity_key"),
            "coordinate_frame": case.get("header", {}).get("coordinate_frame"),
            "accepted_alias_evidence": case.get("accepted_alias_evidence"),
            "status": "CURRENT_IDENTITY_AND_ALIAS_SCOPES_PRESERVED_SEPARATELY",
        },
        "mechanism": mechanisms,
        "source_hash_evidence": _source_file_status(case),
        "catalog_source_index": {
            "trajectory": case.get("trajectory"),
            "raw_root": case.get("raw_root"),
            "xmf": case.get("xmf"),
            "conversion_report": case.get("conversion_report"),
        },
        "execution": {
            "solver_receipt_path": str(solver_path),
            "solver_receipt_sha256": solver_binding.get("sha256"),
            "solver_status": solver.get("status"),
            "solver_returncode": solver.get("returncode"),
            "command": command,
            "run_out": run_out,
            "generated_xml_hash_support": receipt_xml,
            "gencase": gencase_evidence,
        },
        "control": {
            "class": xml.get("control_class"),
            "xml_signature_sha256": xml.get("control_signature_sha256"),
            "effective_control_key_sha256": control_key,
            "asset": asset,
            "semantic_cli_overrides": command.get("semantic_cli_overrides", []),
            "status": "SOURCE_BOUND_RECEIPT_COMMAND_AND_ASSET_PARSED" if asset.get("status") in {"HASH_MATCH_AND_PARSED", "NO_EXTERNAL_MOTION_OR_ACCELERATION_ASSET_DECLARED"} else "CONTROL_EVIDENCE_INCOMPLETE",
        },
        "geometry": {
            "xml_signature_sha256": xml.get("geometry_signature_sha256"),
            "continuous_xml_nodes": _scrub_xml_nodes(xml.get("geometry_nodes", [])),
            "status": "CONTINUOUS_GEOMETRY_RETAINED; DISCRETE_XML_DETAILS_EXCLUDED_FROM_KEY",
        },
        "physical_condition": {
            "effective_physical_key_sha256": physical_key,
            "key_payload": physical_key_payload,
            "owner_condition_hashes": owner_hashes,
            "manifest_condition_hashes": manifest_hashes,
            "opaque_provenance": {
                "owner_canonical_condition_hashes": sorted(owner_hashes.get("physical_condition_sha256", [])),
                "owner_canonical_binding_hashes": sorted(owner_hashes.get("canonical_physical_binding_sha256", [])),
                "manifest_condition_hashes": manifest_hashes,
                "excluded_from_continuous_physical_key": True,
                "semantic_review_status": "UNKNOWN_OPAQUE_HASH_SEMANTICS",
            },
            "status": "SOURCE_RELATION_PROVISIONAL; OPAQUE_HASHES_EXCLUDED; PHYSICAL_EQUIVALENCE_REQUIRES_SEMANTIC_REVIEW",
        },
        "effective_condition": {
            "key_sha256": effective_key,
            "physical_key_sha256": physical_key,
            "control_key_sha256": control_key,
            "excludes": ["case IDs", "dp/resolution", "particle counts", "discrete lattice/sample tokens", "saved frame/output window", "paths and mtimes"],
            "status": "OBSERVED_RECEIPT_AND_SOURCE_KEY; NOT_SPLIT_SAFE",
        },
        "resolution_and_window": {
            "dp_values_observed": xml.get("definition_dp_values", []),
            "particles": case.get("particles"),
            "frames": case.get("frames"),
            "saved_time_window_s": case.get("actual_time_window_s"),
            "excluded_from_effective_key": True,
        },
        "lineage": {
            "conservative_family_group": f"family:{case.get('family_id')}",
            "recovery": "UNKNOWN_NO_EXPLICIT_RECOVERY_EQUIVALENCE",
            "status": "EFFECTIVE_KEYS_ARE_PROVISIONAL; UNKNOWN_RELATIONS_REMAIN_CONSERVATIVELY_GROUPED",
        },
        "replay": {
            "trajectory_h5_content_read_by_audit": False,
            "source_status": source_status,
            "h5_status": "H5_STAT_ONLY_CONTENT_NOT_READ",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "development_only": True,
    }


FAMILY_TASKS: dict[str, dict[str, Any]] = {
    "F1": {
        "mechanism": "gravity release around eccentric/dual obstacle and lower-head bypass",
        "task": "source-bound gravity release and downstream return; receiver/path semantics remain to be reviewed",
        "observables": [{"name": "fluid mass", "unit": "kg"}, {"name": "position", "unit": "m"}, {"name": "velocity", "unit": "m/s"}, {"name": "event time", "unit": "s"}],
    },
    "F2": {
        "mechanism": "prescribed rotation of a liquid-filled cup with offset receiver/tray",
        "task": "first arrival, residence, endpoint/net flux, and moving-frame source/receiver observations",
        "observables": [{"name": "mass", "unit": "kg"}, {"name": "position", "unit": "m"}, {"name": "velocity", "unit": "m/s"}, {"name": "motion angle", "unit": "degrees"}, {"name": "event time", "unit": "s"}],
    },
    "F3": {
        "mechanism": "finite tank sloshing under linear/angular acceleration forcing",
        "task": "fixed-tank exchange and open-top diagnostic under a source-bound acceleration table",
        "observables": [{"name": "mass", "unit": "kg"}, {"name": "position", "unit": "m"}, {"name": "velocity", "unit": "m/s"}, {"name": "linear acceleration", "unit": "m/s^2"}, {"name": "angular acceleration", "unit": "rad/s^2"}, {"name": "event time", "unit": "s"}],
    },
    "F4": {
        "mechanism": "falling drop impact on a finite pool",
        "task": "first pool contact, spread/rebound, and finite-window residence",
        "observables": [{"name": "mass", "unit": "kg"}, {"name": "position", "unit": "m"}, {"name": "velocity", "unit": "m/s"}, {"name": "event time", "unit": "s"}],
    },
    "F5": {
        "mechanism": "runup under a prescribed file-motion asset",
        "task": "source/receiver runup and return with asset coverage explicitly compared with solver tmax",
        "observables": [{"name": "mass", "unit": "kg"}, {"name": "position", "unit": "m"}, {"name": "velocity", "unit": "m/s"}, {"name": "motion table value", "unit": "source-defined/UNKNOWN"}, {"name": "event time", "unit": "s"}],
    },
    "F6": {
        "mechanism": "free six degree of freedom rigid angular release in a finite tank",
        "task": "pose, linear/angular velocity, kinetic energy, and fluid interaction with rigid mass kept separate",
        "observables": [{"name": "fluid mass", "unit": "kg"}, {"name": "rigid body mass", "unit": "kg"}, {"name": "pose", "unit": "m/quaternion"}, {"name": "linear velocity", "unit": "m/s"}, {"name": "angular velocity", "unit": "rad/s"}, {"name": "event time", "unit": "s"}],
    },
    "F7": {
        "mechanism": "prescribed moving paddle exchange in a finite open-top tank",
        "task": "source/destination mass exchange under a piecewise-linear prescribed motion",
        "observables": [{"name": "mass", "unit": "kg"}, {"name": "position", "unit": "m"}, {"name": "velocity", "unit": "m/s"}, {"name": "motion angle", "unit": "degrees"}, {"name": "event time", "unit": "s"}],
    },
}


def _dependency_evidence() -> dict[str, Any]:
    if not DEPENDENCY_INDEX.is_file():
        return {"status": "MISSING_DEPENDENCY_INDEX", "path": str(DEPENDENCY_INDEX)}
    value = _load_json(DEPENDENCY_INDEX)
    return {"path": str(DEPENDENCY_INDEX), "sha256": sha256(DEPENDENCY_INDEX),
            "schema": value.get("schema"), "license_scope": value.get("license_scope"),
            "status": value.get("status"), "dependencies": value.get("dependencies"),
            "source_access": value.get("source_access")}


def _family_card(family: str, cases: list[dict[str, Any]], *, audit_name: str,
                 dependency: Mapping[str, Any]) -> dict[str, Any]:
    groups = Counter(case["effective_condition"]["key_sha256"] for case in cases)
    controls = Counter(case["control"]["class"] for case in cases)
    assets = Counter()
    coverage = Counter()
    runout = Counter(case["execution"]["run_out"]["status"] for case in cases)
    solver_status = Counter(str(case["execution"].get("solver_status")) for case in cases)
    gencase_support = Counter(bool(case["execution"]["gencase"].get("input_definition_hash_support_complete")) for case in cases)
    solver_xml_status = Counter(case["execution"]["generated_xml_hash_support"]["status"] for case in cases)
    incomplete_solver_finish = [
        {
            "case_index": case["case_index"],
            "physical_case_id": case.get("physical_case_id"),
            "solver_status": case["execution"].get("solver_status"),
            "hash_status": case["execution"]["generated_xml_hash_support"].get("status"),
            "launch_hash_supported": case["execution"]["generated_xml_hash_support"].get("launch_hash_supported"),
            "finish_hash_supported": case["execution"]["generated_xml_hash_support"].get("finish_hash_supported"),
            "receipt_path": case["execution"].get("solver_receipt_path"),
        }
        for case in cases
        if case["execution"]["generated_xml_hash_support"].get("status") != "COMPLETE_LAUNCH_AND_FINISH_HASH_SUPPORT"
    ]
    for case in cases:
        selected = case["control"]["asset"].get("selected") or {}
        if selected.get("content_sha256"):
            assets[str(selected["content_sha256"])] += 1
        if selected.get("coverage_status"):
            coverage[str(selected["coverage_status"])] += 1
    task = FAMILY_TASKS.get(family, {"mechanism": "UNKNOWN", "task": "UNKNOWN", "observables": []})
    return {
        "schema": CARD_SCHEMA,
        "family_id": family,
        "case_count": len(cases),
        "status": "DEVELOPMENT_ONLY_EFFECTIVE_EVIDENCE; QUALIFICATION_UNKNOWN",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "evidence_index": audit_name,
        "mechanism_and_task": task,
        "observed_effective_conditions": {
            "provisional_group_count": len(groups),
            "group_size_histogram": dict(sorted(Counter(groups.values()).items())),
            "group_keys": sorted(groups),
            "group_key_excludes": ["case IDs", "dp/resolution", "particle counts", "discrete lattice/sample tokens", "saved output windows", "paths/mtimes"],
            "interpretation": "same key is an observed source relation only; different keys do not prove physical difference when provenance is incomplete",
        },
        "control_and_receipt_evidence": {
            "control_class_counts": dict(sorted(controls.items())),
            "control_asset_sha_counts": dict(sorted(assets.items())),
            "asset_coverage_status_counts": dict(sorted(coverage.items())),
            "solver_status_counts": dict(sorted(solver_status.items())),
            "solver_generated_xml_hash_status_counts": dict(sorted(solver_xml_status.items())),
            "incomplete_solver_finish_cases": incomplete_solver_finish,
            "gencase_definition_input_support_counts": {str(key): value for key, value in sorted(gencase_support.items())},
            "run_out_exact_receipt_output_counts": dict(sorted(runout.items())),
            "run_out_discovery": "only the exact output directory argument in receipt.command was checked; no output_root fallback or glob/latest lookup",
        },
        "replay_anchors": {
            "completed_solver_receipts": sum(case["execution"].get("solver_status") == "completed" for case in cases),
            "completed_gencase_receipts": sum(case["execution"]["gencase"].get("receipt_status") == "completed" for case in cases),
            "source_receipt_paths_retained_per_case": True,
            "trajectory_h5_content_read_by_audit": False,
            "known_full_replay_anchor": {
                "scope": "F2-S1 full 401-frame development replay only",
                "path": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_CONSUMER_V15_FULL401_REPLAY/v15-full401-root-001/v15-full401-report.json",
                "sha256": "962325067fc40166895cd26dd2db3cc538f86576807ef3f779101cd134e6374d",
                "source_binding": "CURRENT/HDF5/initial CSV/XML/motion hashes are recorded in the report",
                "qualification_transfer": "NONE; QI/QN/QE remain UNKNOWN",
            },
        },
        "observations_and_units": task.get("observables", []),
        "missing_failure_and_unknown": [
            "Run.out is bound only from the exact receipt.command output argument; output_root and arbitrary legacy siblings are not accepted",
            "running/incomplete solver receipts retain launch evidence but do not receive finish support",
            "GenCase Def/geometry input hash support is reported separately from generated XML output hash",
            "short motion assets are marked CONTROL_ASSET_END_BEFORE_SOLVER_TMAX and are not padded or extrapolated",
            "recovery/restart equivalence, output-window comparability, and unknown source relations remain UNKNOWN",
            "HDF5 content hash/read and scientific labels are outside this small-source audit",
        ],
        "dependency_and_license_access": dict(dependency),
        "lineage": {
            "conservative_group": f"family:{family}",
            "split_status": "PROVISIONAL_ONLY; NOT_SPLIT_SAFE",
            "unknown_policy": "unresolved links remain conservatively within the family for leakage review; no qualification credit",
        },
        "closure": {
            "physical_condition": "continuous XML/owner geometry and initial-state evidence retained; case/resolution/discrete keys excluded",
            "control": "exact solver command semantic flags plus actual asset content SHA and coverage retained",
            "source": "CURRENT and small source closure only; H5 stat-only",
            "qualification": "all QI/QN/QE UNKNOWN",
        },
        "physical_case_ids": [case["physical_case_id"] for case in cases],
    }


def _raw_to_typed_to_label_plan(current_path: Path,
                                audited: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe the real offline closure without reading trajectory payloads."""
    inventory: list[dict[str, Any]] = []
    for case in audited:
        index = int(case["case_index"])
        # CURRENT is the authority for these paths and producer declarations;
        # only the small entries already consumed by the audit are hashed.
        inventory.append({
            "case_index": index,
            "family_id": case.get("family_id"),
            "physical_case_id": case.get("physical_case_id"),
            "read_small_sources": {
                role: {
                    "path": item.get("path"),
                    "sha256": item.get("actual_sha256") or item.get("declared_sha256"),
                    "status": item.get("status"),
                }
                for role, item in sorted(case.get("source_hash_evidence", {}).items())
                if role in {"generated_xml", "gencase_receipt", "solver_receipt", "owner_metadata", "manifest"}
            },
            "control_assets_read": [
                {
                    "path": item.get("path"),
                    "sha256": item.get("content_sha256"),
                    "status": item.get("status"),
                }
                for item in case.get("control", {}).get("asset", {}).get("assets", [])
            ],
            "native_raw_anchor": {
                **(case.get("catalog_source_index", {}).get("raw_root", {})
                   if isinstance(case.get("catalog_source_index"), Mapping) else {}),
                "status": "CURRENT_RAW_ROOT_NOT_OPENED_BY_LINEAGE_AUDIT",
                "source_role": "case.raw_root",
            },
        })
        # Do not copy the HDF5 path into a claimed input set.  It is retained
        # below as a producer declaration only, so a guard cannot mistake this
        # metadata plan for a raw/typed replay.
        source_index = case.get("catalog_source_index", {})
        trajectory = source_index.get("trajectory", {}) if isinstance(source_index, Mapping) else {}
        conversion = source_index.get("conversion_report", {}) if isinstance(source_index, Mapping) else {}
        inventory[-1]["typed_trajectory"] = {
            **(trajectory if isinstance(trajectory, Mapping) else {}),
            "status": "PRODUCER_DECLARED_STAT_ONLY_NOT_READ",
            "content_sha256": None,
            "qualification": "UNKNOWN",
        }
        inventory[-1]["conversion_report"] = {
            **(conversion if isinstance(conversion, Mapping) else {}),
            "status": "CURRENT_INDEX_ONLY_NOT_READ_BY_MINIMAL_AUDIT",
        }
    return {
        "schema": "ds02.stage2.raw-to-typed-to-label-offline-plan.v15",
        "status": "DEVELOPMENT_ONLY_RAW_TO_TYPED_TO_LABEL_INCOMPLETE",
        "current_catalog": {
            "path": str(current_path.resolve()),
            "sha256": sha256(current_path),
            "role": "identity_and_source_index",
        },
        "scope": {
            "audited_case_count": len(audited),
            "typed_hdf5_opened": False,
            "native_raw_opened": False,
            "label_operator_invoked": False,
            "model_invoked": False,
        },
        "source_inventory": inventory,
        "required_before_offline_replay": [
            "CURRENT-bound native raw PartOut/RunPARTs source paths and content hashes",
            "reproducible raw-to-typed converter executable/source, schema contract, and receipt",
            "typed HDF5 producer content SHA and stat overlay bound to the copied path",
            "valid-mask/identity/order adapter from typed fields to label operator",
            "source-bound receiver/halfspace label operator receipt and evaluator profile",
            "OS-level open trace proving the copied replay did not read original paths",
        ],
        "known_not_closed": [
            "raw_to_typed_reconstruction_receipt",
            "raw_to_typed_field_semantics_and_invalid_mask_proof",
            "typed_to_label_source_bound_execution_receipt",
            "raw_to_label_end_to_end_replay_receipt",
            "qualification_and_split_safe_lineage",
        ],
        "preparation_entrypoint": {
            "command": [
                str(Path(sys.executable).resolve()),
                str(Path(__file__).resolve()),
                "--current",
                str(current_path.resolve()),
                "--output-dir",
                "{new_empty_output_dir}",
            ],
            "next_parent_guard_action": "bind exact raw/native/converter source closure, then run converter and label consumer in one new attempt",
            "large_h5_read": "PARENT_IO_SLOT_REQUIRED",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_audit(current_path: Path, case_indices: Iterable[int] | None = None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = _load_json(current_path)
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise ValueError("CURRENT catalog must contain exactly 336 cases")
    if case_indices is None:
        selected_indices = list(range(len(rows)))
    else:
        selected_indices = sorted(set(case_indices))
        if not selected_indices or any(index < 0 or index >= len(rows) for index in selected_indices):
            raise ValueError("case indices must be non-empty integers in CURRENT336")
    audited = [audit_case(index, rows[index]) for index in selected_indices]
    by_effective: dict[str, list[int]] = defaultdict(list)
    for case in audited:
        by_effective[case["effective_condition"]["key_sha256"]].append(case["case_index"])
    for case in audited:
        key = case["effective_condition"]["key_sha256"]
        case["lineage"]["effective_group_case_indices"] = by_effective[key]
        case["lineage"]["effective_group_size"] = len(by_effective[key])
        case["lineage"]["shared_source_relation"] = "SHARED_EFFECTIVE_KEY_OBSERVED" if len(by_effective[key]) > 1 else "SINGLE_OBSERVED_KEY"
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in audited:
        by_family[str(case["family_id"])].append(case)
    dependency = _dependency_evidence()
    cards = {
        family: _family_card(family, cases, audit_name="CURRENT336-effective-lineage-audit-v15.json", dependency=dependency)
        for family, cases in sorted(by_family.items())
    }
    family_summary = {}
    for family, cases in sorted(by_family.items()):
        family_summary[family] = {
            "family_id": family,
            "case_count": len(cases),
            "case_indices": [case["case_index"] for case in cases],
            "effective_condition_group_count": len({case["effective_condition"]["key_sha256"] for case in cases}),
            "control_asset_status": dict(Counter(case["control"]["asset"]["status"] for case in cases)),
            "solver_status": dict(Counter(str(case["execution"].get("solver_status")) for case in cases)),
            "run_out_status": dict(Counter(case["execution"]["run_out"]["status"] for case in cases)),
            "split_status": "PROVISIONAL_NOT_SPLIT_SAFE",
        }
    audit: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "catalog_path": str(current_path.resolve()),
        "catalog_sha256": sha256(current_path),
        "catalog_schema": current.get("schema"),
        "catalog_case_count": len(rows),
        "case_count": len(audited),
        "audited_case_indices": selected_indices,
        "audit_scope": "CURRENT336_FULL" if len(audited) == len(rows) else "CURRENT336_SELECTED_CASES",
        "family_count": len(by_family),
        "review_status": "EFFECTIVE_SOURCE_CONDITION_KEYS_RECORDED; SEMANTIC_CLOSURE_AND_SPLIT_SAFETY_PENDING",
        "source_scope": "CURRENT336 plus selected-case small XML/manifest/receipt/owner/control assets; XMF/conversion/initial CSV and HDF5 are not read by this minimal audit",
        "rules": {
            "receipt": "solver command and CLI overrides are read only from the CURRENT-bound solver receipt; no latest glob or fixed legacy list",
            "run_out": "only the exact output directory argument in the CURRENT-bound solver receipt command is checked; missing Run.out is explicit and never replaced by an arbitrary sibling",
            "gencase": "GenCase Def/geometry input hashes and generated XML output hash are separate evidence scopes",
            "control_assets": "motion/acceleration content is SHA-256 verified and parsed for monotonic time coverage; end-before-tmax is retained",
            "effective_key": "continuous owner/XML geometry, initial-state, control class, semantic CLI flags, and asset content/coverage; case IDs, dp, particle counts, discrete sampling, paths, and saved windows excluded",
            "lineage": "same keys are observed source relations; unknown recovery/template/control links remain conservative family groups",
            "qualification": "all QI/QN/QE remain UNKNOWN; every case and card is DEVELOPMENT",
        },
        "dependency_and_license_access": dependency,
        "families": family_summary,
        "cases": audited,
        "family_cards": {family: f"{family}-family-card-v15.json" for family in sorted(by_family)},
        "unresolved_catalog": current.get("unresolved"),
        "raw_to_typed_to_label": _raw_to_typed_to_label_plan(current_path, audited),
    }
    audit["sha256"] = digest(audit)
    return audit, cards


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--case-index", action="append", type=int,
                        help="audit one CURRENT case index; repeat for a minimal source-bound audit")
    args = parser.parse_args()
    audit, cards = build_audit(args.current.expanduser(), args.case_index)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite existing lineage output directory: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = args.output_dir / "CURRENT336-effective-lineage-audit-v15.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    for family, card in cards.items():
        (args.output_dir / f"{family}-family-card-v15.json").write_text(
            json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    print(json.dumps({"audit": str(audit_path), "case_count": audit["case_count"],
                      "families": sorted(cards), "audit_sha256": audit["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
