#!/usr/bin/env python3
"""Join the immutable F7 same-CFL 17+3 native observers.

This is a JSON-only provenance join.  It does not decode BI4, interpolate
fields, compare against half-CFL, or promote any QI/QN/QE qualification.  It
requires the existing 17-frame observer and the additive observer for frames
302/602/902, checks every recorded RunPARTs time against the actual row, and
emits exactly the 20 native observations needed for the same-run 4x output
diagnostic at 3/6/9 s.  Endpoints and any physical accuracy claim remain
UNKNOWN.  The v3 output carries one complete pre/post/selected source
record for every one of the 20 frames and verifies the common source
identity (raw root, overlay XML path/content, RunPARTs, decoder contract,
particle-range semantics, mass semantics, and the producer receipt).
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any


SCHEMA = "ds02.stage2.f7-s2.same-cfl-20frame-join.v4"
OBSERVER_SCHEMA = "ds02.stage2.native-physical-observer.v2"
FAMILY = "F7"
SENTINEL = "F7-S2"
PHYSICAL_CASE = "F7_OBSTACLE_QUINTIC_B08_A065"
OLD_FRAMES = [0, 1, 298, 299, 300, 301, 598, 599, 600, 601, 898, 899, 900, 901, 1198, 1199, 1200]
NEW_FRAMES = [302, 602, 902]
MERGED_FRAMES = [0, 1, 298, 299, 300, 301, 302, 598, 599, 600, 601, 602, 898, 899, 900, 901, 902, 1198, 1199, 1200]
TIME_TOLERANCE_S = 1.0e-10
SOURCE_RECEIPT_SCHEMA = "ds02.stage2.external-solver-report.v5"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an existing regular non-symlink file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "sha256": sha256(path)}


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def source_receipt_identity(path: Path, raw_root: Path, expected_xml: Path) -> dict[str, Any]:
    """Check the producer receipt that names the physical/current case.

    The observer payloads intentionally have no run-specific case-id field.
    This receipt closes that identity without reading any native payload: it
    binds the actual same-CFL solver output root and the exact overlay XML
    prefix used by the producer.  A development-unknown solver qualification
    is acceptable here; it is not upgraded by this join.
    """

    receipt = load(path, "same-CFL solver receipt")
    if receipt.get("schema") != SOURCE_RECEIPT_SCHEMA:
        raise ValueError(f"same-CFL solver receipt schema is not {SOURCE_RECEIPT_SCHEMA}")
    if not str(receipt.get("status", "")).startswith("COMPLETED_"):
        raise ValueError("same-CFL solver receipt is not a completed producer receipt")
    attempt = str(receipt.get("attempt_id", ""))
    if "f7-s2-a065-same-cfl-dense-savedt-v5-001" not in attempt:
        raise ValueError(f"unexpected same-CFL producer attempt: {attempt}")
    execution = receipt.get("execution", {})
    argv = execution.get("launch_argv", [])
    def argv_prefix(arg: Any) -> str:
        value = Path(str(arg)).expanduser().resolve()
        return str(value.with_suffix("")) if value.suffix == ".xml" else str(value)

    expected_xml_prefix = str(expected_xml.resolve().with_suffix(""))
    expected_xml_sha = sha256(expected_xml)
    argv_basenames = {
        Path(argv_prefix(arg)).name for arg in argv
    } if isinstance(argv, list) else set()
    expected_xml_stem = expected_xml.resolve().stem
    receipt_inputs = receipt.get("source_validation", {}).get("input_hashes_after", {})
    xml_content_bound = any(
        isinstance(item, dict)
        and int(item.get("bytes", 0)) == int(expected_xml.stat().st_size)
        and item.get("sha256") == expected_xml_sha
        for item in receipt_inputs.values()
    ) if isinstance(receipt_inputs, dict) else False
    if expected_xml_stem not in argv_basenames or not xml_content_bound:
        raise ValueError("producer receipt does not bind the expected same-CFL overlay XML content")
    output_root = receipt.get("filesystem", {}).get("output_root")
    if str(Path(str(output_root)).resolve()) != str(raw_root.resolve().parent.parent):
        # The solver receipt stores the attempt output root, while raw_root is
        # its solver_output/data child.
        raise ValueError("producer receipt output root differs from observer raw root")
    return {
        "schema": receipt["schema"],
        "status": receipt["status"],
        "attempt_id": attempt,
        "output_root": str(Path(str(output_root)).resolve()),
        "request_path": str(Path(str(receipt.get("request", {}).get("path", ""))).resolve()),
        "overlay_xml_sha256": expected_xml_sha,
        "overlay_xml_content_bound_in_receipt": True,
        "launch_argv_overlay_path": next((str(arg) for arg in argv if Path(argv_prefix(arg)).name == expected_xml_stem), None),
        "receipt": record(path, "same-CFL solver receipt"),
    }


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable join output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1; json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite")
    return number


def runparts(path: Path) -> dict[int, float]:
    rows: dict[int, float] = {}
    lines = [line for line in regular(path, "RunPARTs").read_text(encoding="utf-8", errors="strict").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    for raw in reader:
        part_text = str(raw.get("Part", "")).strip().split("#", 1)[0].strip()
        time_text = str(raw.get("TimeStep [s]", "")).strip().split("#", 1)[0].strip()
        if not part_text or not time_text:
            continue
        try:
            part = int(part_text); time_s = finite(time_text, f"RunPARTs[{part}]")
        except (TypeError, ValueError):
            continue
        rows[part] = time_s
    if not rows or sorted(rows) != list(range(max(rows) + 1)):
        raise ValueError("RunPARTs is not contiguous zero-based numeric rows")
    return rows


def _source_identity(value: dict[str, Any], label: str) -> dict[str, Any]:
    source = value.get("source", {})
    semantics = source.get("particle_range_semantics", {})
    decoder = source.get("decoder_interface", {})
    generated_xml = source.get("generated_xml", {})
    runparts = source.get("runparts", {})
    decoder_record = source.get("decoder", {})
    return {
        "observer_schema": value.get("schema"),
        "raw_root": str(Path(str(source.get("raw_root", ""))).resolve()),
        "generated_xml": {
            "path": str(Path(str(generated_xml.get("path", ""))).resolve()),
            "bytes": int(generated_xml.get("bytes", 0)),
            "sha256": generated_xml.get("sha256"),
        },
        "runparts": {
            "path": str(Path(str(runparts.get("path", ""))).resolve()),
            "bytes": int(runparts.get("bytes", 0)),
            "sha256": runparts.get("sha256"),
        },
        "decoder": {
            "path": str(Path(str(decoder_record.get("path", ""))).resolve()),
            "bytes": int(decoder_record.get("bytes", 0)),
            "sha256": decoder_record.get("sha256"),
        },
        "decoder_contract_status": decoder.get("status"),
        "decoder_source": {
            "path": str(Path(str(decoder.get("source", {}).get("path", ""))).resolve()),
            "bytes": int(decoder.get("source", {}).get("bytes", 0)),
            "sha256": decoder.get("source", {}).get("sha256"),
        },
        "decoder_argv_contract": decoder.get("argv_contract"),
        "particle_range_semantics_sha256": hashlib.sha256(canonical(semantics).encode()).hexdigest(),
        "mass_semantics_sha256": hashlib.sha256(canonical(value.get("mass_semantics")).encode()).hexdigest(),
    }


def _integrity_records(value: dict[str, Any], expected_frames: list[int], label: str) -> dict[str, Any]:
    integrity = value.get("source_integrity", {})
    if not str(integrity.get("status", "")).startswith("PASS_PRE_POST_EXPECTED_SOURCE"):
        raise ValueError(f"{label} lacks a successful enforcer source-integrity status")
    pre = integrity.get("pre_decode_records")
    post = integrity.get("post_decode_records")
    if not isinstance(pre, list) or not isinstance(post, list) or len(pre) != len(expected_frames) or len(post) != len(expected_frames):
        raise ValueError(f"{label} source-integrity pre/post record counts are incomplete")
    pre_by = {int(item.get("frame", -1)): item for item in pre if isinstance(item, dict)}
    post_by = {int(item.get("frame", -1)): item for item in post if isinstance(item, dict)}
    selected = value.get("source", {}).get("selected_part_records")
    if not isinstance(selected, list) or len(selected) != len(expected_frames):
        raise ValueError(f"{label} selected_part_records are incomplete")
    selected_by = {int(item.get("frame", -1)): item for item in selected if isinstance(item, dict)}
    merged: list[dict[str, Any]] = []
    for frame in expected_frames:
        before = pre_by.get(frame); after = post_by.get(frame); reported = selected_by.get(frame)
        if before is None or after is None or reported is None:
            raise ValueError(f"{label} source-integrity record missing frame {frame}")
        for record_name, item in (("pre", before), ("post", after), ("selected", reported)):
            if not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str) or int(item.get("bytes", 0)) <= 0:
                raise ValueError(f"{label} frame {frame} has incomplete {record_name} source record")
        for boundary in ("stat_before", "stat_after"):
            if not isinstance(before.get(boundary), dict) or not isinstance(after.get(boundary), dict):
                raise ValueError(f"{label} frame {frame} lacks complete {boundary} stat")
        if before["path"] != after["path"] or before["sha256"] != after["sha256"] or before["bytes"] != after["bytes"] or before["stat_after"] != after["stat_before"] or before["stat_before"] != after["stat_after"]:
            raise ValueError(f"{label} frame {frame} failed complete pre/post source closure")
        if reported["path"] != before["path"] or reported["sha256"] != before["sha256"] or int(reported["bytes"]) != int(before["bytes"]):
            raise ValueError(f"{label} frame {frame} selected record disagrees with enforcer records")
        merged.append({"frame": frame, "path": before["path"], "bytes": int(before["bytes"]), "sha256": before["sha256"], "pre_decode": before, "post_decode": after, "selected_part_record": reported})
    return {"status": "PASS_COMPLETE_PRE_POST_SELECTED_RECORDS", "records": merged, "selected_frame_count": len(merged), "enforcer_status": integrity.get("status"), "expected_manifest": integrity.get("expected_manifest")}


def validate_observer(
    value: dict[str, Any],
    expected_frames: list[int],
    label: str,
    expected_xml: str,
    expected_raw_root: str,
    expected_runparts: dict[str, Any],
    expected_decoder: dict[str, Any],
    expected_decoder_source: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if value.get("schema") != OBSERVER_SCHEMA or value.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"{label} is not a successful native observer")
    scope = value.get("scope", {})
    if scope.get("hdf5_read") is not False or scope.get("particle_field_interpolation") != "NOT_PERFORMED":
        raise ValueError(f"{label} scope is not raw selected-native only")
    source = value.get("source", {})
    if str(Path(str(source.get("raw_root", ""))).resolve()) != str(Path(expected_raw_root).resolve()):
        raise ValueError(f"{label} raw root differs from expected source")
    xml = source.get("generated_xml", {})
    if str(Path(str(xml.get("path", ""))).resolve()) != str(Path(expected_xml).resolve()):
        raise ValueError(f"{label} generated XML identity differs")
    expected_xml_record = record(Path(expected_xml), "expected generated XML")
    if (int(xml.get("bytes", 0)), xml.get("sha256")) != (expected_xml_record["bytes"], expected_xml_record["sha256"]):
        raise ValueError(f"{label} generated XML content differs from the bound overlay")
    runparts_record = source.get("runparts", {})
    if (str(Path(str(runparts_record.get("path", ""))).resolve()), int(runparts_record.get("bytes", 0)), runparts_record.get("sha256")) != (expected_runparts["path"], expected_runparts["bytes"], expected_runparts["sha256"]):
        raise ValueError(f"{label} RunPARTs source identity differs")
    decoder_record = source.get("decoder", {})
    if (str(Path(str(decoder_record.get("path", ""))).resolve()), int(decoder_record.get("bytes", 0)), decoder_record.get("sha256")) != (expected_decoder["path"], expected_decoder["bytes"], expected_decoder["sha256"]):
        raise ValueError(f"{label} decoder binary identity differs")
    decoder_source = source.get("decoder_interface", {}).get("source", {})
    if (int(decoder_source.get("bytes", 0)), decoder_source.get("sha256")) != (expected_decoder_source["bytes"], expected_decoder_source["sha256"]):
        raise ValueError(f"{label} decoder source content differs")
    if source.get("decoder_interface", {}).get("status") != "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT":
        raise ValueError(f"{label} decoder contract status is not the registered argv contract")
    frames = value.get("selected_frames")
    observations = value.get("observations")
    if frames != expected_frames or not isinstance(observations, list) or len(observations) != len(expected_frames):
        raise ValueError(f"{label} frame/observation set differs: {frames}")
    by_frame: dict[int, dict[str, Any]] = {}
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError(f"{label} contains a non-object observation")
        frame = int(observation.get("frame", -1))
        if frame in by_frame or frame not in expected_frames:
            raise ValueError(f"{label} has duplicate/unexpected frame {frame}")
        if observation.get("identity", {}).get("id_unique") is not True:
            raise ValueError(f"{label} frame {frame} lacks exact native ID uniqueness")
        finite_fields = observation.get("finite_fields", {})
        if not all(finite_fields.get(key) is True for key in ("position", "velocity", "density")):
            raise ValueError(f"{label} frame {frame} has non-finite field status")
        time = observation.get("time", {})
        finite(time.get("runparts_s"), f"{label} frame {frame} RunPARTs time")
        finite(time.get("decoded_s"), f"{label} frame {frame} decoded time")
        by_frame[frame] = observation
    return [by_frame[frame] for frame in expected_frames], _integrity_records(value, expected_frames, label), _source_identity(value, label)


def brackets(times: dict[int, float], queries: list[float]) -> list[dict[str, Any]]:
    ordered = sorted(times.items())
    output: list[dict[str, Any]] = []
    for query in queries:
        query = finite(query, "query")
        if query < ordered[0][1] - TIME_TOLERANCE_S or query > ordered[-1][1] + TIME_TOLERANCE_S:
            output.append({"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW", "field_interpolation": "FORBIDDEN"}); continue
        exact = next(((frame, time_s) for frame, time_s in ordered if abs(time_s - query) <= TIME_TOLERANCE_S), None)
        if exact is not None:
            output.append({"query_time_s": query, "status": "EXACT", "lower_frame": exact[0], "upper_frame": exact[0], "lower_time_s": exact[1], "upper_time_s": exact[1], "bracket_width_s": 0.0, "field_interpolation": "FORBIDDEN"}); continue
        upper_index = next(index for index, (_frame, time_s) in enumerate(ordered) if time_s > query)
        lower_frame, lower_time = ordered[upper_index - 1]; upper_frame, upper_time = ordered[upper_index]
        output.append({"query_time_s": query, "status": "BRACKETED", "lower_frame": lower_frame, "upper_frame": upper_frame, "lower_time_s": lower_time, "upper_time_s": upper_time, "bracket_width_s": upper_time - lower_time, "field_interpolation": "FORBIDDEN"})
    return output


def assert_common_identity(old: dict[str, Any], new: dict[str, Any]) -> None:
    """Require common producer semantics while permitting checkout path drift.

    The decoder source can be materialized from either shared worktree.  Its
    content bytes/SHA and argv contract must match; the checkout path itself
    is retained in each identity record but is not a physical-condition key.
    All raw/XML/RunPARTs paths and contents remain exact identity fields.
    """

    for key in old:
        if key == "decoder_source":
            continue
        if old.get(key) != new.get(key):
            raise ValueError(f"same-CFL source identity differs at {key}: {old.get(key)!r} != {new.get(key)!r}")
    old_decoder_source = old.get("decoder_source", {})
    new_decoder_source = new.get("decoder_source", {})
    if (old_decoder_source.get("bytes"), old_decoder_source.get("sha256")) != (new_decoder_source.get("bytes"), new_decoder_source.get("sha256")):
        raise ValueError("same-CFL decoder source content differs between producer reports")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    times = runparts(args.runparts)
    expected_runparts = record(args.runparts, "RunPARTs")
    expected_decoder = record(args.decoder, "decoder binary")
    expected_decoder_source = record(args.decoder_source, "decoder source")
    producer_identity = source_receipt_identity(args.source_receipt, args.raw_root, args.generated_xml)
    old = load(args.same_observer, "17-frame same-CFL observer")
    new = load(args.neighbor_observer, "3-frame neighbor observer")
    old_obs, old_integrity, old_identity = validate_observer(
        old, OLD_FRAMES, "17-frame observer", str(args.generated_xml), args.raw_root,
        expected_runparts, expected_decoder, expected_decoder_source,
    )
    new_obs, new_integrity, new_identity = validate_observer(
        new, NEW_FRAMES, "3-frame observer", str(args.generated_xml), args.raw_root,
        expected_runparts, expected_decoder, expected_decoder_source,
    )
    assert_common_identity(old_identity, new_identity)
    for label, observations in (("old", old_obs), ("new", new_obs)):
        for item in observations:
            frame = int(item["frame"]); actual = times.get(frame)
            if actual is None or abs(finite(item["time"]["runparts_s"], f"{label} frame time") - actual) > TIME_TOLERANCE_S:
                raise ValueError(f"{label} frame {frame} observer time does not equal RunPARTs")
    merged = sorted(old_obs + new_obs, key=lambda item: int(item["frame"]))
    if [int(item["frame"]) for item in merged] != MERGED_FRAMES:
        raise ValueError("merged native frame set is not exactly the registered 20-frame union")
    merged_records = sorted(old_integrity["records"] + new_integrity["records"], key=lambda item: int(item["frame"]))
    if [int(item["frame"]) for item in merged_records] != MERGED_FRAMES:
        raise ValueError("merged source-integrity record set is not exactly the registered 20-frame union")
    return {
        "schema": SCHEMA, "status": "PASS_JOINED_20_NATIVE_OBSERVATIONS_NO_INTERPOLATION_V4", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {"family_id": FAMILY, "sentinel_id": SENTINEL, "physical_case_id": PHYSICAL_CASE, "same_cfl_only": True},
        "scope": {"old_selected_frame_count": 17, "new_selected_frame_count": 3, "joined_frame_count": 20, "frame_ids": MERGED_FRAMES, "hdf5_read": False, "bi4_read": False, "decoder_launch": False, "particle_field_interpolation": "NOT_PERFORMED", "neighbor_join_only": True},
        "source": {"raw_root": str(Path(args.raw_root).resolve()), "generated_xml": record(args.generated_xml, "generated XML"), "runparts": record(args.runparts, "RunPARTs")},
        "source_observers": {"same_17": record(args.same_observer, "17-frame observer"), "neighbor_3": record(args.neighbor_observer, "3-frame observer"), "common_identity": old_identity, "producer_receipt": producer_identity},
        "source_integrity": {
            "status": "PASS_COMPLETE_PRE_POST_RECORDS_FOR_ALL_20_FRAMES_V4",
            "pre_decode_records": [item["pre_decode"] for item in merged_records],
            "post_decode_records": [item["post_decode"] for item in merged_records],
            "selected_part_records": [item["selected_part_record"] for item in merged_records],
            "record_frames": [int(item["frame"]) for item in merged_records],
            "merged_record_count": len(merged_records),
            "producer_segments": {"same_17": old_integrity, "neighbor_3": new_integrity},
            "all_selected_records_complete": True,
            "cross_decode_stat_policy": "each producer pre.stat_after == post.stat_before and pre.stat_before == post.stat_after; all 20 records retained at join level",
        },
        "observations": merged,
        "query_brackets": brackets(times, [0.0, 3.0, 6.0, 9.0, 12.0]),
        "output_sampling_scope": {"same_run_4x_neighbor_frames": [302, 602, 902], "queries_with_new_neighbor": [3.0, 6.0, 9.0], "endpoints": "UNKNOWN_NO_ENDPOINT_EXTRAPOLATION", "field_interpolation": "FORBIDDEN", "purpose": "same-run local output sampling diagnostic only", "integration_error_separation": "not evaluated by join"},
        "calibration_contract": record(args.calibration_contract, "F7 calibration contract"),
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def self_test() -> dict[str, Any]:
    assert len(MERGED_FRAMES) == 20 and len(set(MERGED_FRAMES)) == 20
    assert MERGED_FRAMES == sorted(OLD_FRAMES + NEW_FRAMES)
    with tempfile.TemporaryDirectory(prefix="ds02-f7-join-v4-") as temp_text:
        root = Path(temp_text); output_root = root / "attempt"; raw = output_root / "solver_output" / "data"; raw.mkdir(parents=True)
        xml = root / "source.xml"; xml.write_text("<case/>", encoding="utf-8")
        decoder = root / "decoder"; decoder.write_bytes(b"decoder")
        decoder_source = root / "bi4_dump.cpp"; decoder_source.write_bytes(b"decoder source")
        runparts = root / "RunPARTs.csv"; runparts.write_text("Part;TimeStep [s]\n" + "".join(f"{frame};{frame / 100.0}\n" for frame in range(1201)), encoding="utf-8")
        contract = root / "contract.json"; contract.write_text("{}", encoding="utf-8")
        receipt = root / "execution-receipt.json"
        receipt.write_text(json.dumps({
            "schema": SOURCE_RECEIPT_SCHEMA,
            "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
            "attempt_id": "F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001",
            "execution": {"launch_argv": [str(xml.with_suffix(""))]},
            "filesystem": {"output_root": str(output_root)},
            "request": {"path": str(root / "request.json")},
            "source_validation": {"input_hashes_after": {str(xml): {"bytes": xml.stat().st_size, "sha256": sha256(xml)}}},
        }), encoding="utf-8")
        def observer(frames: list[int], name: str) -> Path:
            records = []
            observations = []
            for frame in frames:
                path = str((raw / f"Part_{frame:04d}.bi4").resolve()); stat = {"bytes": 1, "mtime_ns": frame, "ctime_ns": frame, "st_dev": 1, "st_ino": frame + 1}
                records.append({"frame": frame, "path": path, "bytes": 1, "sha256": "0" * 64, "stat_before": stat, "stat_after": stat})
                observations.append({"frame": frame, "time": {"runparts_s": frame / 100.0, "decoded_s": frame / 100.0}, "identity": {"id_unique": True}, "finite_fields": {"position": True, "velocity": True, "density": True}, "groups": {"fluid": {"mass_semantics": "native_particle_sample_mass_only"}}})
            value = {
                "schema": OBSERVER_SCHEMA,
                "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
                "scope": {"hdf5_read": False, "particle_field_interpolation": "NOT_PERFORMED"},
                "source": {
                    "raw_root": str(raw.resolve()),
                    "runparts": record(runparts, "RunPARTs"),
                    "generated_xml": record(xml, "generated XML"),
                    "decoder": record(decoder, "decoder"),
                    "particle_range_semantics": {"test": True},
                    "decoder_interface": {"status": "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT", "source": record(decoder_source, "decoder source"), "argv_contract": ["decoder", "native_part.bi4", "scratch/decoded"]},
                    "selected_part_records": records,
                },
                "mass_semantics": {"fluid": "sample-only"},
                "selected_frames": frames,
                "observations": observations,
                "source_integrity": {"status": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT", "expected_manifest": "manifest", "pre_decode_records": records, "post_decode_records": records},
            }
            path = root / name; path.write_text(json.dumps(value), encoding="utf-8"); return path
        old_path = observer(OLD_FRAMES, "old.json"); new_path = observer(NEW_FRAMES, "new.json"); output = root / "joined.json"
        value = run(SimpleNamespace(output=output, runparts=runparts, same_observer=old_path, neighbor_observer=new_path, generated_xml=xml, decoder=decoder, decoder_source=decoder_source, source_receipt=receipt, raw_root=raw, calibration_contract=contract))
        assert value["status"] == "PASS_JOINED_20_NATIVE_OBSERVATIONS_NO_INTERPOLATION_V4"
        assert value["source_integrity"]["merged_record_count"] == 20
        assert len(value["source_integrity"]["pre_decode_records"]) == 20
        assert len(value["source_integrity"]["post_decode_records"]) == 20
    return {"status": "PASS", "merged_frame_count": len(MERGED_FRAMES), "complete_pre_post_records_tested": True, "source_identity_match_tested": True, "interpolation": "FORBIDDEN", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--same-observer", type=Path)
    parser.add_argument("--neighbor-observer", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path)
    parser.add_argument("--source-receipt", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--calibration-contract", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.same_observer, args.neighbor_observer, args.runparts, args.generated_xml, args.decoder, args.decoder_source, args.source_receipt, args.raw_root, args.calibration_contract, args.output]
    if any(value is None for value in required):
        parser.error("all join arguments are required unless --self-test")
    try:
        value = run(args); atomic_json(args.output, value)
    except Exception as exc:
        print(json.dumps({"status": "FAIL_F7_20FRAME_JOIN", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve()), "frames": len(value["observations"])}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
