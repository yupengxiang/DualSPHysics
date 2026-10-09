#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Full-window native audit with a bounded compact summary sidecar.

This forward worker keeps the consumed v3 source join and v2 decoder intact.
It writes the large full report and, in the same guarded process, emits a
small summary containing its exact path/bytes/SHA, source binding, header
consistency, lifecycle counts, and at most twelve query-endpoint
observations.  The summary is an operational index only; it grants no QI,
QN, or QE qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V3_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v3.py"
SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.v4"
PASS_STATUS = "PASS_F3_FULL_NATIVE_STREAM_STRICT_SOURCE_JOIN_WITH_COMPACT_SUMMARY"
UNKNOWN_STATUS = "UNKNOWN_F3_FULL_NATIVE_STREAM_V4"


def _load_v3():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v3_forward_dependency", V3_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V3_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V3 = _load_v3()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _regular(path: Path, label: str) -> Path:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "mode": int(value.st_mode),
    }


def _stable_record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being hashed: {path}")
    return {"path": str(path), "bytes": before["bytes"], "sha256": digest.hexdigest(), "stat_before": before, "stat_after": after, "stable_read": True, "label": label}


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int | None = None) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable summary: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if max_bytes is not None and temporary.stat().st_size > max_bytes:
            raise ValueError(f"atomic JSON exceeds bounded output size {max_bytes} bytes: {temporary.stat().st_size}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _scalar(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


def _header_compact(observation: dict[str, Any]) -> dict[str, Any]:
    header = observation.get("native_header")
    if not isinstance(header, dict):
        return {"status": "UNKNOWN_NATIVE_HEADER"}
    result: dict[str, Any] = {}
    for name in ("Dp", "MassFluid", "MassBound", "H", "PeriMode"):
        if name in header:
            result[name] = _scalar(header[name])
    return result


def _field_compact(observation: dict[str, Any]) -> dict[str, Any]:
    fields = observation.get("fluid_observable_using_native_header_mass")
    if not isinstance(fields, dict):
        fields = observation.get("fluid_observables")
    if not isinstance(fields, dict):
        return {"status": "UNKNOWN_FLUID_OBSERVABLES"}
    result: dict[str, Any] = {}
    for key in ("weighted_centroid_m", "weighted_velocity_m_per_s", "centroid_m", "mean_velocity_m_per_s", "kinetic_energy_j", "fluid_count", "sample_mass_kg", "mass_semantics"):
        if key in fields:
            result[key] = fields[key]
    identity = observation.get("identity")
    if isinstance(identity, dict) and isinstance(identity.get("particle_count"), int):
        result["total_particle_count"] = int(identity["particle_count"])
        fluid_count = result.get("fluid_count")
        if isinstance(fluid_count, int):
            result["nonfluid_particle_count"] = int(identity["particle_count"]) - fluid_count
    return result


def _source_range_counts(value: dict[str, Any]) -> dict[str, int]:
    """Return XML-range counts without claiming native Type/MK semantics."""

    source = value.get("source")
    semantics = source.get("particle_range_semantics") if isinstance(source, dict) else None
    blocks = semantics.get("blocks") if isinstance(semantics, dict) else None
    counts: dict[str, int] = {}
    if not isinstance(blocks, list):
        return counts
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("kind", "UNKNOWN"))
        count = block.get("count")
        if isinstance(count, int) and count >= 0:
            counts[kind] = counts.get(kind, 0) + int(count)
    return counts


def _count_compact(value: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Summarize fluid/fixed counts, keeping moving/floating ambiguity explicit."""

    result = _field_compact(observation)
    expected_by_xml_kind = _source_range_counts(value)
    if expected_by_xml_kind:
        result["xml_range_counts_expected"] = expected_by_xml_kind
    fluid_count = result.get("fluid_count")
    total_count = result.get("total_particle_count")
    nonfluid = result.get("nonfluid_particle_count")
    nonfixed_kinds = sum(expected_by_xml_kind.get(kind, 0) for kind in ("moving", "floating"))
    if isinstance(nonfluid, int) and nonfixed_kinds == 0 and expected_by_xml_kind.get("fixed", 0) > 0:
        result["fixed_count"] = nonfluid
        result["fixed_count_semantics"] = "decoded_total_minus_decoded_fluid; XML ranges contain no moving/floating block"
    else:
        result["fixed_count"] = "UNKNOWN_NOT_SEPARATED_FROM_NONFLUID"
        result["fixed_count_semantics"] = "XML range labels are available but decoded observation stores no native Type axis"
    if isinstance(total_count, int) and isinstance(fluid_count, int):
        result["nonfluid_particle_count"] = total_count - fluid_count
    result["moving_count"] = "UNKNOWN_NATIVE_TYPE_NOT_DECODED"
    result["floating_count"] = "UNKNOWN_NATIVE_TYPE_NOT_DECODED"
    return result


def _frame_manifest(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Create a compact all-frame source boundary manifest for parent stat-join."""

    source = value.get("source")
    records = source.get("full_window_frame_records") if isinstance(source, dict) else None
    if not isinstance(records, list):
        return []

    def boundary(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {"status": "UNKNOWN_INVALID_BOUNDARY_RECORD"}
        return {key: item.get(key) for key in ("path", "bytes", "sha256", "stat_before", "stat_after", "stat_consistency") if key in item}

    manifest: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            manifest.append({"status": "UNKNOWN_INVALID_FRAME_RECORD"})
            continue
        pre = boundary(record.get("pre_decode"))
        post = boundary(record.get("post_decode"))
        stable = (
            pre.get("status") != "UNKNOWN_INVALID_BOUNDARY_RECORD"
            and post.get("status") != "UNKNOWN_INVALID_BOUNDARY_RECORD"
            and pre.get("path") == post.get("path")
            and pre.get("bytes") == post.get("bytes")
            and pre.get("sha256") == post.get("sha256")
            and pre.get("stat_after") == post.get("stat_before")
            and pre.get("stat_before") == post.get("stat_after")
        )
        manifest.append({"frame": record.get("frame"), "path": pre.get("path"), "pre_decode": pre, "post_decode": post, "stable_boundary": stable})
    return manifest


def _manifest_sha256(manifest: list[dict[str, Any]]) -> str:
    encoded = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _request_binding(path: Path) -> dict[str, Any]:
    """Read and stably bind the small terminal request identity."""

    record = _stable_record(path, "terminal solver request for compact case binding")
    request = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("terminal solver request must be a JSON object")
    return {
        "family_id": request.get("family_id", "UNKNOWN_NOT_EXPOSED_BY_TERMINAL_REQUEST"),
        "sentinel_id": request.get("sentinel_id", "UNKNOWN_NOT_EXPOSED_BY_TERMINAL_REQUEST"),
        "physical_case_id": request.get("physical_case_id", "UNKNOWN_NOT_EXPOSED_BY_TERMINAL_REQUEST"),
        "case_id": request.get("case_id", "UNKNOWN_NOT_EXPOSED_BY_TERMINAL_REQUEST"),
        "attempt_id": request.get("attempt_id", "UNKNOWN_NOT_EXPOSED_BY_TERMINAL_REQUEST"),
        "request_record": record,
    }


def _selected_indices(value: dict[str, Any], maximum: int = 12) -> list[int]:
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        return []
    brackets = value.get("time_window", {}).get("query_brackets", [])
    candidates: list[int] = [0, len(observations) - 1]
    if isinstance(brackets, list):
        for item in brackets:
            if not isinstance(item, dict):
                continue
            for key in ("lower_index", "upper_index"):
                index = item.get(key)
                if isinstance(index, int) and 0 <= index < len(observations):
                    candidates.append(index)
    result: list[int] = []
    for index in candidates:
        if index not in result:
            result.append(index)
        if len(result) >= maximum:
            break
    return sorted(result)


def _observation_summary(value: dict[str, Any], index: int) -> dict[str, Any]:
    observation = value["observations"][index]
    identity = observation.get("identity_lifecycle")
    if not isinstance(identity, dict):
        identity = observation.get("identity") if isinstance(observation.get("identity"), dict) else {}
    return {
        "observation_index": index,
        "frame": observation.get("frame"),
        "runparts_time_s": observation.get("runparts_time_s"),
        "decoded_time_s": observation.get("decoded_time_s"),
        "native_header": _header_compact(observation),
        "fields": _field_compact(observation),
        "identity_lifecycle": {
            "appeared_count": len(identity.get("appeared_idp", [])) if isinstance(identity.get("appeared_idp"), list) else "UNKNOWN",
            "disappeared_count": len(identity.get("disappeared_idp", [])) if isinstance(identity.get("disappeared_idp"), list) else "UNKNOWN",
            "particle_count": identity.get("particle_count", "UNKNOWN"),
        },
        "field_digest_sha256": observation.get("field_digest_sha256"),
    }


def _lifecycle_counts(value: dict[str, Any]) -> dict[str, Any]:
    lifecycle = value.get("id_lifecycle")
    records = lifecycle.get("records") if isinstance(lifecycle, dict) else None
    observations = value.get("observations")
    if not isinstance(records, list) or not isinstance(observations, list):
        return {"status": "UNKNOWN_LIFECYCLE_RECORDS"}
    missing_records = sum(1 for record in records if isinstance(record, dict) and "first_missing_frame" in record)
    introduced_after_frame0 = sum(1 for record in records if isinstance(record, dict) and int(record.get("first_frame", 0)) > 0)
    disappeared_ids: set[int] = set()
    reappeared_ids: set[int] = set()
    missing_seen: set[int] = set()
    for observation in observations:
        row = observation.get("identity_lifecycle") if isinstance(observation, dict) else None
        if not isinstance(row, dict):
            continue
        disappeared = row.get("disappeared_idp")
        appeared = row.get("appeared_idp")
        if not isinstance(disappeared, list) or not isinstance(appeared, list):
            continue
        for value in disappeared:
            particle_id = int(value)
            disappeared_ids.add(particle_id)
            missing_seen.add(particle_id)
        for value in appeared:
            particle_id = int(value)
            if particle_id in missing_seen:
                reappeared_ids.add(particle_id)
    return {
        "status": "MEASURED_FROM_FULL_IDP_LIFECYCLE_SUMMARY",
        "unique_idp_records": len(records),
        "records_with_first_missing_frame": missing_records,
        "introduced_after_frame0_records": introduced_after_frame0,
        "unique_disappeared_idp": len(disappeared_ids),
        "unique_reappeared_idp": len(reappeared_ids),
        "unknown_counts": {
            "physical_fate_or_flux": "UNKNOWN_NOT_INFERRED",
            "native_type_or_mk_lifecycle": "UNKNOWN_XML_RANGE_ONLY",
        },
        "physical_fate_or_flux": "UNKNOWN_NOT_INFERRED",
        "per_id_records_retained_in_full_report_only": True,
    }


def _header_consistency(value: dict[str, Any]) -> dict[str, Any]:
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        return {"status": "UNKNOWN_NO_OBSERVATIONS"}
    result: dict[str, Any] = {}
    for name in ("Dp", "MassFluid", "MassBound"):
        values = []
        for observation in observations:
            header = observation.get("native_header") if isinstance(observation, dict) else None
            if isinstance(header, dict) and name in header:
                item = _scalar(header[name])
                if item not in values:
                    values.append(item)
        result[name] = {"unique_value_count": len(values), "first_values": values[:3], "consistent": len(values) == 1}
    return result


def _compact_summary(value: dict[str, Any], full_report_path: Path, request_binding: dict[str, Any] | None = None) -> dict[str, Any]:
    observations = value.get("observations") if isinstance(value.get("observations"), list) else []
    indexes = _selected_indices(value, 12)
    scope = value.get("scope") if isinstance(value.get("scope"), dict) else {}
    source_binding = value.get("strict_source_binding") if isinstance(value.get("strict_source_binding"), dict) else {}
    frame_manifest = _frame_manifest(value)
    return {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "summary_scope": "bounded_operational_index_only",
        "full_report": {"path": str(full_report_path), "content_hash_added_after_atomic_full_report_rename": True},
        "case_binding": {
            **(request_binding or {
                "family_id": value.get("family_id", "UNKNOWN_NOT_EXPOSED_BY_CONSUMED_V3"),
                "sentinel_id": value.get("sentinel_id", "UNKNOWN_NOT_EXPOSED_BY_CONSUMED_V3"),
                "physical_case_id": value.get("physical_case_id", "UNKNOWN_NOT_EXPOSED_BY_CONSUMED_V3"),
            }),
            "terminal_request_sha256": source_binding.get("terminal_request_sha256", "UNKNOWN"),
            "terminal_output_root": source_binding.get("output_root", "UNKNOWN"),
        },
        "source_binding": source_binding,
        "frame_count": scope.get("frame_count", len(observations)),
        "first_frame": observations[0].get("frame") if observations else "UNKNOWN",
        "last_frame": observations[-1].get("frame") if observations else "UNKNOWN",
        "first_saved_time_s": value.get("time_window", {}).get("first_saved_time_s", "UNKNOWN"),
        "last_saved_time_s": value.get("time_window", {}).get("last_saved_time_s", "UNKNOWN"),
        "native_header_consistency": _header_consistency(value),
        "native_header_summary": value.get("native_header_summary", {"status": "UNKNOWN"}),
        "initial_counts": _count_compact(value, observations[0]) if observations else {"status": "UNKNOWN"},
        "final_counts": _count_compact(value, observations[-1]) if observations else {"status": "UNKNOWN"},
        "lifecycle_counts": _lifecycle_counts(value),
        "query_brackets": value.get("time_window", {}).get("query_brackets", []),
        "selected_observations": [_observation_summary(value, index) for index in indexes],
        "selected_observation_count": len(indexes),
        "frame_manifest": frame_manifest,
        "frame_manifest_count": len(frame_manifest),
        "frame_manifest_sha256": _manifest_sha256(frame_manifest),
        "frame_manifest_scope": "all native Part pre/post path/SHA/stat records; no per-ID lifecycle copied",
        "full_report_frame_records": "retained in full report; not copied into compact summary",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "bounded native fields/identity/header/time summary only; no spatial, continuum, dynamics, integration/output error, event, or physical fate qualification"},
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = _path(args.output)
    summary_output = _path(args.summary_output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable full report: {output}")
    if summary_output.exists() or summary_output.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable compact summary: {summary_output}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.v3-full.tmp")
    delegated = argparse.Namespace(**vars(args))
    delegated.output = temporary
    try:
        value = V3.run(delegated)
        request_binding = _request_binding(args.solver_request)
        terminal_request_sha = value.get("strict_source_binding", {}).get("terminal_request_sha256") if isinstance(value.get("strict_source_binding"), dict) else None
        if terminal_request_sha != request_binding.get("request_record", {}).get("sha256"):
            raise RuntimeError("terminal solver request changed between strict v3 join and compact summary binding")
        summary = _compact_summary(value, output, request_binding)
        if summary.get("frame_manifest_count") != summary.get("frame_count"):
            raise RuntimeError("full report frame manifest is incomplete")
        if any(item.get("stable_boundary") is not True for item in summary.get("frame_manifest", [])):
            raise RuntimeError("full report frame manifest contains an unstable pre/post boundary")
        os.replace(temporary, output)
        report_record = _stable_record(output, "full native v4 report")
        summary["full_report"] = report_record
        _atomic_json(summary_output, summary, max_bytes=2 * 1024 * 1024)
        summary_record = _stable_record(summary_output, "compact full native v4 summary")
        return {"status": PASS_STATUS, "full_report": report_record, "summary": summary_record, "frame_count": summary.get("frame_count"), "selected_observation_count": summary.get("selected_observation_count")}
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = V3.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    tiny = {
        "scope": {"frame_count": 2},
        "time_window": {"first_saved_time_s": 0.0, "last_saved_time_s": 1.0, "query_brackets": [{"query_time_s": 0.0, "status": "EXACT", "lower_index": 0, "upper_index": 0}]},
        "strict_source_binding": {"terminal_request_sha256": "0" * 64},
        "observations": [
            {"frame": 0, "runparts_time_s": 0.0, "decoded_time_s": 0.0, "native_header": {"Dp": {"value": 0.006}, "MassFluid": {"value": 0.003375}, "MassBound": {"value": 0.001}}, "fluid_observable_using_native_header_mass": {"fluid_count": 1, "sample_mass_kg": 0.003375, "weighted_centroid_m": [0.0, 0.0, 0.0], "weighted_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0, "mass_semantics": "native"}, "identity": {"particle_count": 2}, "identity_lifecycle": {"appeared_idp": [0, 1], "disappeared_idp": [], "particle_count": 2}, "field_digest_sha256": "0" * 64},
            {"frame": 1, "runparts_time_s": 1.0, "decoded_time_s": 1.0, "native_header": {"Dp": {"value": 0.006}, "MassFluid": {"value": 0.003375}, "MassBound": {"value": 0.001}}, "fluid_observable_using_native_header_mass": {"fluid_count": 1, "sample_mass_kg": 0.003375, "weighted_centroid_m": [1.0, 0.0, 0.0], "weighted_velocity_m_per_s": [1.0, 0.0, 0.0], "kinetic_energy_j": 0.5, "mass_semantics": "native"}, "identity": {"particle_count": 2}, "identity_lifecycle": {"appeared_idp": [], "disappeared_idp": [], "particle_count": 2}, "field_digest_sha256": "1" * 64},
        ],
        "id_lifecycle": {"records": [{"idp": 0, "first_frame": 0}, {"idp": 1, "first_frame": 0}]},
        "source": {
            "particle_range_semantics": {
                "blocks": [
                    {"kind": "fluid", "begin": 0, "count": 1},
                    {"kind": "fixed", "begin": 1, "count": 1},
                ]
            },
            "full_window_frame_records": [
                {"frame": 0, "pre_decode": {"path": "/tmp/Part_0000.bi4", "bytes": 2, "sha256": "a" * 64, "stat_before": {"bytes": 2}, "stat_after": {"bytes": 2}, "stat_consistency": "PASS"}, "post_decode": {"path": "/tmp/Part_0000.bi4", "bytes": 2, "sha256": "a" * 64, "stat_before": {"bytes": 2}, "stat_after": {"bytes": 2}, "stat_consistency": "PASS"}},
                {"frame": 1, "pre_decode": {"path": "/tmp/Part_0001.bi4", "bytes": 2, "sha256": "b" * 64, "stat_before": {"bytes": 2}, "stat_after": {"bytes": 2}, "stat_consistency": "PASS"}, "post_decode": {"path": "/tmp/Part_0001.bi4", "bytes": 2, "sha256": "b" * 64, "stat_before": {"bytes": 2}, "stat_after": {"bytes": 2}, "stat_consistency": "PASS"}},
            ],
        },
        "native_header_summary": {"massfluid_kg": 0.003375},
    }
    summary = _compact_summary(tiny, Path("/tmp/f3-v4-selftest-full.json"))
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    if summary["selected_observation_count"] > 12 or summary["lifecycle_counts"]["unique_idp_records"] != 2 or summary["frame_manifest_count"] != 2 or summary["initial_counts"].get("fixed_count") != 1 or len(encoded) >= 2 * 1024 * 1024:
        raise AssertionError("compact summary self-test failed")
    return {"status": "PASS", "schema": SCHEMA, "compact_summary": True, "maximum_selected_observations": 12, "full_report_sha_stat": True, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--source-snapshot-proof", type=Path)
    parser.add_argument("--source-snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path)
    parser.add_argument("--calibration-contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--decoder-timeout-s", type=float, default=300.0)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=64 * 1024)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=256 * 1024 * 1024)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.solver_request, args.terminal_receipt, args.terminal_proof, args.source_snapshot_proof, args.source_snapshot_report, args.raw_root, args.runparts, args.generated_xml, args.decoder, args.decoder_source, args.calibration_contract, args.output, args.summary_output, args.scratch_root, args.expected_frame_count, args.expected_final_time_s, args.expected_dp_m, args.expected_initial_fluid_count, args.query_times)
    if any(item is None for item in required):
        parser.error("full v4 observer requires terminal/source provenance, report/summary outputs, and bounded decoder arguments")
    try:
        result = run(args)
    except V3.V2.WorkerCancelled as exc:
        print(str(exc), file=sys.stderr); return 143
    except V3.V2.base.UnsupportedSemantics as exc:
        print(f"full native v4 observer unsupported: {exc}", file=sys.stderr); return 2
    except Exception as exc:
        print(f"full native v4 observer failed: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "summary": result["summary"]["path"], "summary_sha256": result["summary"]["sha256"], "full_report": result["full_report"]["path"], "full_report_sha256": result["full_report"]["sha256"], "frame_count": result.get("frame_count"), "selected_observation_count": result.get("selected_observation_count")}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
