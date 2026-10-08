#!/usr/bin/env python3
"""Join verified F7 selected-observer JSON and run the bounded calibration.

The same-CFL producer already has an immutable 17-frame observer report.  A
forward observer decodes only frames 302, 602, and 902.  This worker joins the
two JSON artifacts into a 20-frame same-CFL report, keeps the independently
verified half-CFL 17-frame report unchanged, and invokes the existing
calibration worker on those two reports.  It never opens BI4/HDF5 and never
performs particle-field interpolation itself.

The join is deliberately strict: successful observer status, exact frame
sets, source report hashes, and the selected-frame metadata must all agree.
Missing half-CFL radius-two rows remain the calibration worker's explicit
UNKNOWN outcome; this worker does not synthesize them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


OBSERVER_SCHEMA = "ds02.stage2.native-physical-observer.v2"
EXPECTED_STATUS = "PASS_DECODED_SELECTED_NATIVE_FIELDS"
SAME_OLD_FRAMES = (0, 1, 298, 299, 300, 301, 598, 599, 600, 601,
                   898, 899, 900, 901, 1198, 1199, 1200)
SAME_NEW_FRAMES = (302, 602, 902)
HALF_FRAMES = SAME_OLD_FRAMES
SAME_MERGED_FRAMES = tuple(sorted(set(SAME_OLD_FRAMES) | set(SAME_NEW_FRAMES)))


class JoinError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise JoinError(f"{label} is unavailable or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JoinError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise JoinError(f"{label} must be a JSON object: {path}")
    return value


def _frames(value: Mapping[str, Any], label: str) -> tuple[int, ...]:
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise JoinError(f"{label} has no observations")
    result: list[int] = []
    for item in observations:
        if not isinstance(item, Mapping) or not isinstance(item.get("frame"), int):
            raise JoinError(f"{label} has an invalid observation frame")
        result.append(int(item["frame"]))
    if result != sorted(set(result)):
        raise JoinError(f"{label} observation frames are not sorted and unique")
    return tuple(result)


def _require_success(value: Mapping[str, Any], label: str) -> None:
    if value.get("schema") != OBSERVER_SCHEMA:
        raise JoinError(f"{label} schema is not {OBSERVER_SCHEMA}")
    if value.get("status") != EXPECTED_STATUS:
        raise JoinError(f"{label} is not a successful native observer")
    scope = value.get("scope")
    if not isinstance(scope, Mapping):
        raise JoinError(f"{label} lacks observer scope")
    if scope.get("hdf5_read") is not False or scope.get("typed_conversion") != "NOT_PERFORMED":
        raise JoinError(f"{label} scope permits HDF5/typed conversion")
    if scope.get("particle_field_interpolation") != "NOT_PERFORMED":
        raise JoinError(f"{label} claims particle-field interpolation")
    integrity = value.get("source_integrity")
    if not isinstance(integrity, Mapping) or integrity.get("status") != "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT":
        raise JoinError(f"{label} lacks complete source pre/post integrity")


def _source_records(value: Mapping[str, Any], label: str) -> list[dict[str, Any]]:
    source = value.get("source")
    if not isinstance(source, Mapping):
        raise JoinError(f"{label} lacks source records")
    records = source.get("selected_part_records")
    if not isinstance(records, list) or not records:
        raise JoinError(f"{label} lacks selected source records")
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise JoinError(f"{label} contains a malformed source record")
        path = str(record.get("path", ""))
        name = Path(path).name
        if not name.startswith("Part_") or not name.endswith(".bi4"):
            raise JoinError(f"{label} source record is not a Part_*.bi4: {path}")
        try:
            frame = int(name[5:-4])
            bytes_value = int(record["bytes"])
        except (KeyError, ValueError, TypeError) as exc:
            raise JoinError(f"{label} source record has invalid frame/bytes") from exc
        digest = str(record.get("sha256", ""))
        if len(digest) != 64:
            raise JoinError(f"{label} source record has incomplete SHA")
        normalized.append({"frame": frame, "path": path, "bytes": bytes_value,
                           "sha256": digest, "mtime_ns": record.get("mtime_ns")})
    if [int(item["frame"]) for item in normalized] != sorted({int(item["frame"]) for item in normalized}):
        raise JoinError(f"{label} source records are not sorted and unique")
    return normalized


def _merge_source_records(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_frame: dict[int, dict[str, Any]] = {}
    for record in old + new:
        frame = int(record["frame"])
        if frame in by_frame:
            raise JoinError(f"same-CFL merge repeats frame {frame}")
        by_frame[frame] = record
    result = [by_frame[frame] for frame in sorted(by_frame)]
    return result


def merge_same_report(old_path: Path, new_path: Path, output: Path) -> dict[str, Any]:
    """Join one old 17-frame report and one new 3-frame report atomically."""
    old = load_json(old_path, "same-CFL old observer")
    new = load_json(new_path, "same-CFL new observer")
    _require_success(old, "same-CFL old observer")
    _require_success(new, "same-CFL new observer")
    if _frames(old, "same-CFL old observer") != SAME_OLD_FRAMES:
        raise JoinError("same-CFL old observer is not the verified 17-frame producer")
    if _frames(new, "same-CFL new observer") != SAME_NEW_FRAMES:
        raise JoinError("same-CFL new observer must contain only frames 302/602/902")
    old_records = _source_records(old, "same-CFL old observer")
    new_records = _source_records(new, "same-CFL new observer")
    merged_frames = _merge_source_records(old_records, new_records)
    if tuple(item["frame"] for item in merged_frames) != SAME_MERGED_FRAMES:
        raise JoinError("same-CFL merged frame set is not the registered 20-frame set")

    observations: dict[int, dict[str, Any]] = {}
    for value, label in ((old, "same-CFL old observer"), (new, "same-CFL new observer")):
        for item in value["observations"]:
            frame = int(item["frame"])
            if frame in observations:
                raise JoinError(f"same-CFL merge repeats observation frame {frame}")
            observations[frame] = item
    merged = dict(old)
    merged["observations"] = [observations[frame] for frame in sorted(observations)]
    merged["scope"] = dict(old["scope"])
    merged["scope"]["selected_frame_count"] = len(SAME_MERGED_FRAMES)
    merged["scope"]["selected_frames"] = list(SAME_MERGED_FRAMES)
    merged["source"] = dict(old["source"])
    merged["source"]["selected_frames"] = list(SAME_MERGED_FRAMES)
    merged["source"]["selected_part_records"] = merged_frames
    merged["source"]["selected_frame_count"] = len(SAME_MERGED_FRAMES)
    merged["source_integrity"] = dict(old["source_integrity"])
    merged["source_integrity"]["selected_frame_count"] = len(SAME_MERGED_FRAMES)
    merged["source_integrity"]["merged_json_only"] = True
    merged["source_integrity"]["old_producer_report_sha256"] = sha256_file(old_path)
    merged["source_integrity"]["new_producer_report_sha256"] = sha256_file(new_path)
    merged["source_integrity"]["old_report_path"] = str(old_path.resolve())
    merged["source_integrity"]["new_report_path"] = str(new_path.resolve())
    merged["enforcer"] = {
        "schema": "ds02.stage2.f7-neighbor-json-join.v1",
        "old_report": str(old_path.resolve()),
        "old_report_sha256": sha256_file(old_path),
        "new_report": str(new_path.resolve()),
        "new_report_sha256": sha256_file(new_path),
        "old_frame_count": len(SAME_OLD_FRAMES),
        "new_frame_count": len(SAME_NEW_FRAMES),
        "merged_frame_count": len(SAME_MERGED_FRAMES),
        "raw_decode_in_join": False,
        "hdf5_read": False,
        "particle_field_interpolation": "NOT_PERFORMED",
    }
    merged["merge_scope"] = {
        "same_cfl": "old verified 17-frame JSON plus new verified 3-frame JSON",
        "half_cfl": "kept as separate verified 17-frame JSON; no synthetic frames",
        "same_frames": list(SAME_MERGED_FRAMES),
        "half_frames": list(HALF_FRAMES),
        "half_radius_two_missing": [302, 602, 902],
        "four_x_status": "UNKNOWN_FOR_HALF_CFL_UNTIL_THREE_HALF_NATIVE_FRAMES_EXIST",
    }
    merged["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    if output.exists():
        raise JoinError(f"refusing to overwrite merged observer output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(merged, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return merged


def _self_test() -> None:
    import tempfile

    def observer(frames: tuple[int, ...]) -> dict[str, Any]:
        obs = []
        records = []
        for frame in frames:
            obs.append({"frame": frame, "time": {"runparts_s": float(frame), "decoded_s": float(frame),
                       "absolute_error_s": 0.0, "status": "PASS_DECODED_TIME_MATCH"},
                        "finite_fields": {"position": True, "velocity": True, "density": True},
                        "groups": {"fluid": {"mass_semantics": "native_particle_sample_mass_only",
                                               "weighted_centroid_m": [0.0, 0.0, 0.0],
                                               "weighted_velocity_m_per_s": [0.0, 0.0, 0.0],
                                               "kinetic_energy_j": 0.0, "sample_mass_kg": 1.0}}})
            records.append({"path": f"/tmp/Part_{frame:04d}.bi4", "bytes": 1,
                            "sha256": f"{frame:064x}"[-64:], "mtime_ns": 1})
        return {"schema": OBSERVER_SCHEMA, "status": EXPECTED_STATUS, "observations": obs,
                "scope": {"hdf5_read": False, "typed_conversion": "NOT_PERFORMED",
                          "particle_field_interpolation": "NOT_PERFORMED", "selected_frame_count": len(frames)},
                "source_integrity": {"status": "PASS_PRE_POST_EXPECTED_SOURCE_AND_STAT"},
                "source": {"selected_part_records": records, "selected_frames": list(frames)}}

    with tempfile.TemporaryDirectory(prefix="ds02-f7-join-selftest-") as root_text:
        root = Path(root_text)
        old = root / "old.json"; new = root / "new.json"; out = root / "merged.json"
        old.write_text(json.dumps(observer(SAME_OLD_FRAMES)), encoding="utf-8")
        new.write_text(json.dumps(observer(SAME_NEW_FRAMES)), encoding="utf-8")
        value = merge_same_report(old, new, out)
        assert [item["frame"] for item in value["observations"]] == list(SAME_MERGED_FRAMES)
        assert value["scope"]["selected_frame_count"] == 20
        try:
            merge_same_report(old, new, out)
        except JoinError:
            pass
        else:
            raise AssertionError("merged output overwrite was accepted")
        print("PASS F7 same17+new3 JSON join self-test")


def run_join_and_calibration(args: argparse.Namespace) -> dict[str, Any]:
    merged = merge_same_report(args.same_old, args.same_new, args.merged_same)
    half = load_json(args.half_old, "half-CFL verified 17-frame observer")
    _require_success(half, "half-CFL verified 17-frame observer")
    if _frames(half, "half-CFL verified 17-frame observer") != HALF_FRAMES:
        raise JoinError("half-CFL input must remain the verified 17-frame report")
    if args.merged_output.exists():
        raise JoinError(f"refusing to overwrite calibration output: {args.merged_output}")
    command = [str(args.python), str(args.calibration), "--run",
               "--same-observer", str(args.merged_same.resolve()),
               "--half-observer", str(args.half_old.resolve()),
               "--same-runparts", str(args.same_runparts.resolve()),
               "--half-runparts", str(args.half_runparts.resolve()),
               "--contract", str(args.contract.resolve()),
               "--output", str(args.merged_output.resolve())]
    completed = subprocess.run(command, cwd=str(args.cwd.resolve()), capture_output=True,
                               text=True, check=False)
    if completed.returncode != 0 or not args.merged_output.is_file():
        raise JoinError(f"calibration worker failed ({completed.returncode}): {completed.stderr[-2000:]}")
    report = load_json(args.merged_output, "calibration report")
    return {"status": "PASS_JSON_JOIN_AND_CALIBRATION_WORKER",
            "merged_observer": str(args.merged_same.resolve()),
            "merged_observer_frames": list(SAME_MERGED_FRAMES),
            "half_observer": str(args.half_old.resolve()),
            "half_observer_frames": list(HALF_FRAMES),
            "half_four_x_status": "UNKNOWN_MISSING_302_602_902",
            "calibration_report": str(args.merged_output.resolve()),
            "calibration_report_status": report.get("status"),
            "calibration_stdout_tail": completed.stdout[-2000:],
            "raw_decode_in_join": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--same-old", type=Path)
    parser.add_argument("--same-new", type=Path)
    parser.add_argument("--half-old", type=Path)
    parser.add_argument("--merged-same", type=Path)
    parser.add_argument("--merged-output", type=Path)
    parser.add_argument("--same-runparts", type=Path)
    parser.add_argument("--half-runparts", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--python", type=Path, default=Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"))
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test()
            return 0
        required = (args.same_old, args.same_new, args.half_old, args.merged_same,
                    args.merged_output, args.same_runparts, args.half_runparts,
                    args.contract, args.calibration)
        if not args.run or any(item is None for item in required):
            parser.error("--run and all join/calibration paths are required")
        result = run_join_and_calibration(args)
    except (JoinError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED_JSON_JOIN_OR_CALIBRATION", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
