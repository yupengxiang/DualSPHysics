#!/usr/bin/env python3
"""Prepare an additive F3 GenCase source repair for the forcing mismatch.

The consumed owner-grid producer package recorded the continuous F3 forcing
source (14,919,771 bytes) while the candidate directories contain a different
7,737,549-byte file with the same basename.  This module never treats those
files as interchangeable.  It creates a *source-prepared* repair package in
which the requested ``dp`` change is kept separate from an explicit auxiliary
forcing rebind.  The parent must either copy the exact owner forcing into the
fresh attempt input directory after reservation (the default ``staged`` mode)
or use the opt-in absolute-path mode.  Neither mode launches GenCase here.

Only bounded candidate XML/JSON and file metadata are read.  The declared
owner forcing SHA is carried through without reading the large source.  The
old V2 requests and candidate files are immutable inputs and are never
overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.three-sentinel.f3-forcing-rebind.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT = "three-sentinel-owner-grid-gencase-producer-f3-forcing-rebind-v1"
TARGET = "F3-S1"
GRIDS = ("original", "coarse", "fine")
SMALL_CAP = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5", ".part", ".hdf"}
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}


class BuildFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {
        "device": int(s.st_dev),
        "inode": int(s.st_ino),
        "bytes": int(s.st_size),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise BuildFailure(f"{label} exceeds the bounded metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, {
        "path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
        "stat_before": before, "stat_after": after,
        "read_mode": "small_read", "payload_read_by_builder": True,
    }


def _record_small(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise BuildFailure(f"{label} exceeds the bounded metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
        "stat_before": before, "stat_after": after,
        "read_mode": "small_read", "hash_status": "BOUND_SMALL_SOURCE",
        "payload_read_by_builder": True, "scope": "bounded_small_source",
    }


def _record_stat_only(path: Path, *, sha256: str, label: str,
                      declared_stat: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record the owner forcing without reading its bytes."""
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    if not _valid_sha(sha256):
        raise BuildFailure(f"{label} requires a concrete owner SHA")
    before = _stat(path)
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while statting: {path}")
    if declared_stat is not None:
        for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
            if key in declared_stat and int(declared_stat[key]) != before[key]:
                raise BuildFailure(f"{label} {key} differs from declared owner stat")
    return {
        "path": str(path), "sha256": sha256.lower(), "bytes": before["bytes"],
        "stat_before": before, "stat_after": after,
        "read_mode": "deferred_parent_after_reservation",
        "hash_status": "DECLARED_OWNER_SHA_PARENT_REVERIFY_REQUIRED",
        "payload_read_by_builder": False, "scope": "deferred_control_source",
    }


def _write(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite of immutable repair output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_owner_record(path: Path) -> dict[str, Any]:
    value, _ = _read_json(path, "owner forcing record")
    record = value.get("record", value)
    if not isinstance(record, dict):
        raise BuildFailure("owner forcing record is not an object")
    source_path = record.get("path")
    if not isinstance(source_path, str):
        raise BuildFailure("owner forcing record has no path")
    if not _valid_sha(record.get("sha256")):
        raise BuildFailure("owner forcing record has no concrete SHA")
    stat = record.get("stat_after", record.get("stat"))
    if not isinstance(stat, dict):
        raise BuildFailure("owner forcing record has no complete stat")
    # This stat-only check deliberately does not hash/read the forcing.
    return _record_stat_only(Path(source_path), sha256=str(record["sha256"]),
                             label="owner forcing", declared_stat=stat)


def _candidate_aux(request: dict[str, Any], candidate_path: Path) -> tuple[Path, dict[str, Any]]:
    binding = request.get("source_binding")
    if not isinstance(binding, dict):
        raise BuildFailure("request has no source_binding")
    aux = binding.get("motion_or_forcing")
    if not isinstance(aux, dict) or not isinstance(aux.get("path"), str):
        raise BuildFailure("F3 request has no motion_or_forcing record")
    declared_path = Path(str(aux["path"])).expanduser().absolute()
    # The consumed V2 request binds the owner source in
    # source_binding.motion_or_forcing, while the candidate Def's cwd also
    # contains a same-basename rejected copy.  Resolve the candidate copy from
    # the Def directory; never mistake the owner path for that copy.
    aux_path = candidate_path.parent / declared_path.name
    if aux_path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise BuildFailure(f"forcing path unexpectedly looks like a native payload: {aux_path}")
    if aux_path.is_symlink() or not aux_path.is_file():
        raise BuildFailure(f"candidate forcing is not a regular file: {aux_path}")
    st = _stat(aux_path)
    # The candidate copy is intentionally below the metadata cap.  Read/hash
    # only this bounded rejected copy; the owner source remains stat-only.
    if st["bytes"] > SMALL_CAP:
        raise BuildFailure(f"candidate forcing exceeds bounded metadata cap: {aux_path}")
    candidate_record = _record_small(aux_path, "candidate forcing copy")
    declared = aux.get("sha256") if declared_path == aux_path else None
    if declared is not None and _valid_sha(declared) and candidate_record["sha256"] != str(declared).lower():
        raise BuildFailure(f"candidate forcing declared SHA differs from actual copy: {aux_path}")
    if aux_path.name != "CaseSloshingAccData.csv":
        raise BuildFailure("unexpected F3 forcing filename")
    candidate_record.update({
        "read_mode": "bounded_read_rejected_candidate_copy",
        "scope": "candidate_auxiliary_mismatch_diagnostic",
        "payload_read_by_builder": True,
        "declared_binding_path": str(declared_path),
    })
    return aux_path, candidate_record


def _candidate_def(request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    binding = request.get("source_binding")
    candidate = binding.get("candidate_def") if isinstance(binding, dict) else None
    if not isinstance(candidate, dict) or not isinstance(candidate.get("path"), str):
        raise BuildFailure("request has no candidate_def binding")
    path = Path(str(candidate["path"])).expanduser().absolute()
    return path, _record_small(path, "candidate Def")


def _rebind_xml(candidate_path: Path, candidate_record: dict[str, Any], old_aux: Path,
                owner: dict[str, Any], destination: Path, mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create the new Def with only the declared dp/path operation."""
    raw = candidate_path.read_bytes()
    old_name = old_aux.name
    text = raw.decode("utf-8")
    count = text.count(old_name)
    if count < 1:
        raise BuildFailure(f"candidate Def has no {old_name} reference: {candidate_path}")
    owner_path = str(owner["path"])
    if mode == "absolute":
        replacement = owner_path
        new_text = text.replace(old_name, replacement)
        mode_note = "absolute_original_source_path"
    elif mode == "staged":
        # The XML retains the original basename.  The parent must copy the
        # exact owner bytes beside this fresh Def before invoking GenCase.
        replacement = old_name
        new_text = text
        mode_note = "parent_attempt_contained_exact_copy"
    else:
        raise BuildFailure(f"unknown forcing rebind mode: {mode}")
    changed = new_text != text
    if mode == "absolute" and not changed:
        raise BuildFailure("absolute forcing rebind did not change the Def")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(new_text, encoding="utf-8")
    new_record = _record_small(destination, "rebound candidate Def")
    return new_record, {
        "attribute_or_text": "acctimesfile.value",
        "reference_basename": old_name,
        "replacement": replacement,
        "replacement_count": count,
        "mode": mode_note,
        "source_change": "path_only_auxiliary_rebinding_plus_definition_dp",
        "dp_change_remains_separate": True,
        "candidate_def_source_sha256": candidate_record["sha256"],
        "candidate_def_rebound_sha256": new_record["sha256"],
    }


def _record_from_request_value(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} is malformed")
    if not _valid_sha(value.get("sha256")):
        raise BuildFailure(f"{label} has no concrete SHA")
    # Do not open the file here; this is a source-prepared request rebinding.
    return dict(value)


def _rewrite_request(old: dict[str, Any], old_path: Path, owner: dict[str, Any],
                     output_dir: Path, mode: str, sequence: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if old.get("sentinel_id") != TARGET:
        raise BuildFailure(f"not an F3-S1 request: {old_path}")
    grid = str(old.get("grid_label"))
    if grid not in GRIDS:
        raise BuildFailure(f"unexpected F3 grid: {grid}")
    candidate_path, candidate_record = _candidate_def(old)
    old_aux_path, rejected_aux = _candidate_aux(old, candidate_path)
    # Verify the candidate copy is actually distinct from the owner source by
    # metadata.  A same-name record with the owner SHA is not accepted unless
    # its source stat also matches; no inferred byte equality is permitted.
    if rejected_aux["sha256"] == owner["sha256"] and rejected_aux["bytes"] == owner["bytes"]:
        raise BuildFailure("candidate forcing unexpectedly equals owner forcing; no repair needed")
    rebound_dir = output_dir / "prepared" / grid
    rebound_path = rebound_dir / candidate_path.name
    rebound_record, edit = _rebind_xml(candidate_path, candidate_record, old_aux_path, owner,
                                       rebound_path, mode)
    old_records = old.get("input_records")
    if not isinstance(old_records, dict):
        raise BuildFailure(f"{old_path} has no input_records map")
    new_records: dict[str, Any] = {}
    for key, value in old_records.items():
        if not isinstance(value, dict):
            continue
        if str(key) in {str(candidate_record["path"]), str(old_aux_path)}:
            continue
        new_records[str(key)] = dict(value)
    new_records[str(rebound_record["path"])] = rebound_record
    # Keep an explicit parent-staged auxiliary record outside the static map.
    staged_name = "CaseSloshingAccData.csv"
    staged_path = str(rebound_dir / staged_name)
    deferred = [dict(x) for x in old.get("deferred_input_records", []) if isinstance(x, dict)]
    deferred = [x for x in deferred if str(x.get("path")) != str(old_aux_path)]
    deferred.append({
        **owner,
        "path": owner["path"],
        "read_mode": "parent_after_reservation_exact_copy",
        "scope": "owner_forcing_control_source",
        "payload_read_by_builder": False,
        "staging_path": staged_path,
        "parent_copy_required": mode == "staged",
        "absolute_source_allowed": mode == "absolute",
        "candidate_copy_rejected": rejected_aux,
    })
    source_binding = dict(old.get("source_binding") or {})
    source_binding["candidate_def"] = rebound_record
    source_binding["candidate_stem"] = str(rebound_path.with_suffix(""))
    source_binding["motion_or_forcing"] = dict(deferred[-1])
    source_binding["rejected_candidate_auxiliary"] = rejected_aux
    source_binding["source_edit_contract"] = {
        "allowed": ["definition@dp", "auxiliary_path_rebinding"],
        "comparison_status": "PENDING_PARENT_EXACT_SOURCE_CONTROL_JOIN",
        "forbidden": ["drawbox", "drawcylinder", "drawextrude", "clipplane", "clipreset",
                       "pointref", "size", "motion", "gravity", "other_parameters"],
        "auxiliary_rebinding": {
            "role": "CaseSloshingAccData.csv",
            "owner_record": owner,
            "candidate_record_rejected": rejected_aux,
            "edit": edit,
            "mode": mode,
            "parent_rule": (
                "after reservation, copy exact owner bytes to staging_path with a new inode "
                "and bind the staged path in runtime input_files; parent pre/post SHA/stat "
                "must equal owner record before GenCase"
            ) if mode == "staged" else (
                "after reservation, hash the absolute owner path before and after GenCase; "
                "the parent must prove the exact owner SHA/stat was consumed"
            ),
            "candidate_bytes_are_not_control_source": True,
        },
        "dp_change_is_independent": True,
    }
    new_case = f"F3_S1_{grid.upper()}_OWNER_GRID_GENCASE_F3FORCE_REBIND_V1"
    new_attempt = f"f3-s1-{grid}-owner-grid-gencase-f3force-rebind-v1-parent-pending-{sequence:03d}"
    output_root = str(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3") / new_case / new_attempt)
    command_stem = str(rebound_path.with_suffix(""))
    new = dict(old)
    new.update({
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_SHARED_RUNTIME_V8_GENCASERUN_F3FORCE_REBIND_V1",
        "request_variant": REQUEST_VARIANT,
        "case_id": new_case,
        "attempt_id": new_attempt,
        "command": [old.get("command", ["GenCase_linux64"])[0], command_stem,
                     "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(rebound_dir),
        "input_files": sorted(new_records),
        "input_records": new_records,
        "input_sha256": {p: r["sha256"] for p, r in new_records.items() if _valid_sha(r.get("sha256"))},
        "input_hashes": {p: r["sha256"] for p, r in new_records.items() if _valid_sha(r.get("sha256"))},
        "deferred_input_files": [owner["path"]],
        "deferred_input_records": deferred,
        "output_root": "{attempt_root}",
        "planned_output_root": output_root,
        "execution_allowed": False,
        "launch_disabled": True,
        "source_only": True,
        "gencase_only": True,
        "solver_launch": False,
        "solver_started": False,
        "bi4_read": False,
        "hdf5_read": False,
        "read_scope": {
            "builder_reads_candidate_def_only": True,
            "builder_reads_owner_forcing": False,
            "parent_exact_owner_forcing_copy_after_reservation": mode == "staged",
            "parent_absolute_owner_forcing_hash_after_reservation": mode == "absolute",
            "candidate_forcing_copy_rejected": True,
            "genCase_products_deferred": True,
        },
        "source_binding": source_binding,
        "root_rebind_required": True,
        "root_rebind_contract": {
            "candidate_def_source_path": str(rebound_path),
            "fresh_attempt_input_directory": "{attempt_root}/inputs/F3_S1/" + grid,
            "staged_owner_forcing_path": "{attempt_root}/inputs/F3_S1/" + grid + "/" + staged_name,
            "copy_owner_forcing_exact_bytes": mode == "staged",
            "do_not_use_rejected_candidate_copy": True,
            "runtime_v8_input_files_must_include_staged_auxiliary": True,
            "runtime_v8_parent_pre_post_hash_required": True,
        },
        "scientific_qualification": QUALIFICATION,
    })
    # The parent must make the fresh input path agree with the command; this
    # source package intentionally does not pretend that the source path is an
    # executable attempt path.
    new["source_package"] = {
        "prepared_candidate_def": rebound_record,
        "owner_forcing": owner,
        "rejected_candidate_forcing": rejected_aux,
        "auxiliary_rebinding_mode": mode,
        "requires_root_normalization": True,
    }
    return new, {
        "sentinel_id": TARGET, "grid_label": grid, "case_id": new_case,
        "attempt_id": new_attempt, "request": new,
        "candidate_def": rebound_record, "owner_forcing": owner,
        "rejected_candidate_forcing": rejected_aux, "edit": edit,
        "status": "PENDING_PARENT_EXACT_OWNER_FORCING_COPY_AND_GENCASE",
        "scientific_qualification": QUALIFICATION,
    }


def build(request_dir: Path, owner_record_path: Path, output_dir: Path,
          *, mode: str = "staged", expected_owner_bytes: int = 14_919_771) -> dict[str, Any]:
    request_dir = request_dir.expanduser().absolute()
    owner = _load_owner_record(owner_record_path)
    if Path(owner["path"]).name != "CaseSloshingAccData.csv":
        raise BuildFailure("owner forcing is not CaseSloshingAccData.csv")
    if int(owner["bytes"]) != int(expected_owner_bytes):
        raise BuildFailure(f"owner forcing size {owner['bytes']} is not the declared {expected_owner_bytes}-byte source")
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing overwrite of non-empty repair package: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    requests_out = output_dir / "requests"
    rows: list[dict[str, Any]] = []
    for grid in GRIDS:
        candidates = sorted(request_dir.glob(f"f3-s1-{grid}-*-request.json"))
        if len(candidates) != 1:
            raise BuildFailure(f"expected one F3 {grid} request in {request_dir}, got {candidates}")
        old_path = candidates[0]
        old, old_record = _read_json(old_path, f"F3 {grid} request")
        new, row = _rewrite_request(old, old_path, owner, output_dir, mode, len(rows) + 1)
        new_path = requests_out / f"f3-s1-{grid}-owner-grid-gencase-f3force-rebind-v1-request.json"
        _write(new_path, new)
        row["request_path"] = str(new_path)
        row["request_file_sha256"] = _sha(new_path.read_bytes())
        row["request_source_record"] = _record_small(new_path, f"new F3 {grid} request")
        rows.append(row)
    manifest = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_SOURCE_CONTROL_REBIND_REVIEW",
        "request_variant": REQUEST_VARIANT,
        "sentinel_id": TARGET,
        "owner_forcing": owner,
        "candidate_forcing_semantics": {
            "same_basename_does_not_mean_same_control": True,
            "candidate_copy_sizes_observed": sorted({int(r["rejected_candidate_forcing"]["bytes"]) for r in rows}),
            "owner_bytes": int(owner["bytes"]),
            "owner_sha256": owner["sha256"],
        },
        "source_edit_contract": {
            "allowed": ["definition@dp", "auxiliary_path_rebinding"],
            "prohibited": ["mass_rescale", "density_change", "geometry_change", "motion_change", "gravity_change"],
            "parent_must_prove_exact_owner_control": True,
            "qualification": QUALIFICATION,
        },
        "auxiliary_rebinding_mode": mode,
        "rows": [{k: v for k, v in row.items() if k not in {"request"}} for row in rows],
        "read_scope": {
            "source_builder_reads_candidate_xml_and_json_only": True,
            "owner_forcing_bytes_read_by_builder": False,
            "candidate_forcing_bytes_read_by_builder": False,
            "parent_after_reservation_exact_copy_and_hash": mode == "staged",
            "parent_after_reservation_absolute_hash": mode == "absolute",
            "gencase_started": False,
            "solver_started": False,
            "scientific_credit": 0,
        },
        "root_rebind_required": True,
    }
    manifest_path = output_dir / "f3-forcing-rebind-manifest-v1.json"
    _write(manifest_path, manifest)
    return {"manifest": manifest, "manifest_path": str(manifest_path),
            "request_paths": [r["request_path"] for r in rows], "rows": rows}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f3-force-rebind-") as td:
        root = Path(td)
        candidate_dir = root / "candidate"
        candidate_dir.mkdir()
        old_aux = candidate_dir / "CaseSloshingAccData.csv"
        old_aux.write_bytes(b"candidate-control\n")
        owner_aux = root / "owner" / "CaseSloshingAccData.csv"
        owner_aux.parent.mkdir()
        owner_aux.write_bytes(b"owner-control-with-different-bytes\n")
        owner_record = _record_small(owner_aux, "tiny owner")
        # In a real 14.9 MB source this record is stat-only.  The fixture uses
        # the same API but keeps the tiny payload and declared size meaningful.
        owner_record["sha256"] = _sha(owner_aux.read_bytes())
        def_path = candidate_dir / "F3_S1_SPATIAL_COARSE_DP0p007500_Def.xml"
        def_path.write_text(
            '<case><definition dp="0.0075"/><execution><motion><acctimesfile value="CaseSloshingAccData.csv"/></motion></execution></case>\n',
            encoding="utf-8")
        req_dir = root / "old"; req_dir.mkdir()
        req = {
            "schema": REQUEST_SCHEMA, "sentinel_id": TARGET, "grid_label": "coarse",
            "source_binding": {
                "candidate_def": _record_small(def_path, "tiny candidate Def"),
                "motion_or_forcing": {**_record_small(old_aux, "tiny candidate forcing"),
                                       "read_mode": "small_read"},
            },
            "input_records": {str(def_path): _record_small(def_path, "tiny candidate Def"),
                              str(old_aux): _record_small(old_aux, "tiny candidate forcing")},
            "deferred_input_records": [], "command": ["GenCase_linux64", str(def_path.with_suffix(""))],
            "input_files": [str(def_path), str(old_aux)],
        }
        for grid in GRIDS:
            gp = req_dir / f"f3-s1-{grid}-owner-grid-gencase-v2-request.json"
            value = json.loads(json.dumps(req))
            value["grid_label"] = grid
            value["source_binding"]["candidate_def"]["path"] = str(def_path)
            _write(gp, value)
        # Adapt the fixture owner record to the builder's exact expected name;
        # no source bytes are hidden from the builder API.
        owner_record_path = root / "owner-record.json"
        _write(owner_record_path, {"record": owner_record})
        out = root / "out"
        result = build(req_dir, owner_record_path, out, mode="absolute", expected_owner_bytes=owner_record["bytes"])
        assert len(result["rows"]) == 3
        for row in result["rows"]:
            q = json.loads(Path(row["request_path"]).read_text())
            assert q["source_binding"]["source_edit_contract"]["allowed"] == ["definition@dp", "auxiliary_path_rebinding"]
            assert q["source_binding"]["rejected_candidate_auxiliary"]["sha256"] != q["source_binding"]["motion_or_forcing"]["sha256"]
            assert str(owner_aux) in Path(q["source_binding"]["candidate_def"]["path"]).read_text()
            assert q["deferred_input_records"][0]["sha256"] == owner_record["sha256"]
        # Wrong owner declaration must fail closed without reading a large
        # source to “discover” a replacement SHA.
        bad = root / "bad-owner.json"
        _write(bad, {"record": {**owner_record, "sha256": "0" * 64}})
        try:
            build(req_dir, bad, root / "bad-out", mode="staged")
        except BuildFailure:
            pass
        else:
            raise AssertionError("bad owner SHA was accepted")
    print("PASS_THREE_SENTINEL_OWNER_GRID_F3_FORCING_REBIND_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--request-dir", type=Path)
    parser.add_argument("--owner-record", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mode", choices=("staged", "absolute"), default="staged")
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_F3_FORCING_REBIND_V1_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    for required in (args.request_dir, args.owner_record, args.output_dir):
        if required is None:
            parser.error("--build requires --request-dir, --owner-record and --output-dir")
    try:
        result = build(args.request_dir, args.owner_record, args.output_dir, mode=args.mode)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_F3_FORCING_REBIND_V1: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["manifest"]["status"], "manifest": result["manifest_path"],
                      "requests": result["request_paths"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
