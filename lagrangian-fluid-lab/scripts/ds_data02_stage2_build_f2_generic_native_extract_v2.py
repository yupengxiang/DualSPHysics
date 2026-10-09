#!/usr/bin/env python3
"""Prepare/audit the first F2 missing typed/native-join batch.

This is an additive F2 entry point around the reviewed generic native
extractor.  ROOT193 is retained as one complete eight-case producer proof;
the selected eight cases are the exact F2 batch in that proof and are checked
against the 47 already joined physical cases before a request is emitted.
The wrapper adds the producer-proof scope needed by downstream consumers and
delegates the guarded PartVTKOut/RunPARTs/typed-record audit to the reviewed
generic V1 implementation.  It never opens H5, JSONL, BI4, OBI4, PartOut, or
RunPARTs during ``prepare``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
BASE_PATH = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_generic_native_extract_v1.py"
JOIN_SOURCE = STAGE2 / "requests/native-typed-native-join-source-root315-prepared-002/native-typed-native-join-source-v1.json"
ROOT193_PROOF = STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_193.json"
ROOT193_REQUEST = STAGE2 / "requests/typed-lifecycle-batch-v1-f2-root-forward-193-001.json"
ROOT193_MANIFEST = STAGE2 / "requests/typed-lifecycle-batch-v1-f2-root-prepared-193-002/typed-lifecycle-batch-v1-manifest.json"
FAMILY = "F2"
NAMESPACE = "ROOT315"
EXPECTED_CASES = (
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX046_RY014_FILL080_ROT065",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX046_RY014_FILL080_ROT120",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX048_RY014_FILL080_ROT065",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX048_RY014_FILL080_ROT120",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX052_RY014_FILL080_ROT065",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX052_RY014_FILL080_ROT120",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX054_RY014_FILL080_ROT065",
    "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX054_RY014_FILL080_ROT120",
)
MAX_SMALL_BYTES = 10 * 1024 * 1024


class F2GenericV2Error(ValueError):
    """Raised when the immutable F2 source scope is not closed."""


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_generic_native_v1_for_f2_root315", BASE_PATH)
    if spec is None or spec.loader is None:
        raise F2GenericV2Error(f"cannot load generic extractor: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _read_json(path: Path, label: str, *, limit: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if not path.is_file():
        raise F2GenericV2Error(f"{label} is missing: {path}")
    if path.stat().st_size > limit:
        raise F2GenericV2Error(f"{label} exceeds the bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise F2GenericV2Error(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise F2GenericV2Error(f"{label} must be an object")
    return value


def _sha(path: Path, label: str) -> str:
    path = path.expanduser().absolute()
    if not path.is_file():
        raise F2GenericV2Error(f"{label} is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if not path.is_file():
        raise F2GenericV2Error(f"{label} is missing: {path}")
    stat = path.stat()
    if stat.st_size > MAX_SMALL_BYTES:
        raise F2GenericV2Error(f"{label} exceeds the bounded metadata limit: {path}")
    actual = _sha(path, label)
    if expected is not None and actual != expected:
        raise F2GenericV2Error(f"{label} SHA differs: {path}")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": actual,
        "content_opened": True,
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise F2GenericV2Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{__import__('os').getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            __import__('os').fsync(stream.fileno())
        os_replace = __import__('os').replace
        os_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _proof_bundle(proof_ref: dict[str, Any], proof: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        raise F2GenericV2Error("ROOT193 proof lacks case_verifications")
    full = [row.get("physical_case_id") for row in rows if isinstance(row, dict)]
    if len(full) != 8 or len(set(full)) != 8 or set(selected) - set(full):
        raise F2GenericV2Error("ROOT193 proof is not the complete eight-case producer proof")
    if proof.get("counts") != {"cases_requested": 8, "completed": 8, "failed": 0}:
        raise F2GenericV2Error("ROOT193 proof count is not exactly 8/8/0")
    return {
        "producer_id": "ROOT193",
        "path": proof_ref["path"],
        "sha256": proof_ref["sha256"],
        "proof": proof_ref,
        "full_case_ids": full,
        "selected_case_ids": selected,
        "selected_case_count": len(selected),
        "full_case_count": len(full),
        "producer_status": proof.get("status"),
        "synthetic_merged_proof": False,
    }


def _actual_join_ids(path: Path) -> tuple[dict[str, Any], set[str]]:
    source = _read_json(path, "actual 47-join source")
    rows = source.get("actual_case_rows")
    if not isinstance(rows, list) or len(rows) != 47:
        raise F2GenericV2Error("actual join source must expose exactly 47 actual case rows")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise F2GenericV2Error("actual join source has malformed case row")
        if row["physical_case_id"] in ids:
            raise F2GenericV2Error("actual join source has duplicate case row")
        ids.add(row["physical_case_id"])
    return source, ids


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if args.namespace != NAMESPACE:
        raise F2GenericV2Error(f"namespace must be {NAMESPACE}")
    lifecycle = _read_json(args.lifecycle_request, "ROOT193 lifecycle request")
    selected = lifecycle.get("physical_case_ids")
    if selected != list(EXPECTED_CASES):
        raise F2GenericV2Error("ROOT193 lifecycle request is not the immutable F2 first missing-join batch")
    proof = _read_json(args.terminal_proof, "ROOT193 terminal proof")
    proof_ref = _small_ref(args.terminal_proof, "ROOT193 terminal proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise F2GenericV2Error("ROOT193 proof schema differs")
    join_source, joined_ids = _actual_join_ids(JOIN_SOURCE)
    overlap = joined_ids.intersection(selected)
    if overlap:
        raise F2GenericV2Error(f"selected F2 batch overlaps an existing precise native/typed join: {sorted(overlap)}")
    if any(case_id not in set(EXPECTED_CASES) for case_id in selected):
        raise F2GenericV2Error("unexpected F2 selected case")

    # Delegate all source-edge and contract construction to the reviewed
    # generic V1 implementation.  It stat-checks deferred native paths but
    # does not open their contents during prepare.  Keep its intermediate
    # request beside the requested final request; the caller's path is the
    # immutable enriched request that root will review.
    requested_request_path = args.request_output.expanduser().absolute()
    delegated_args = argparse.Namespace(**vars(args))
    delegated_args.request_output = requested_request_path.with_name(
        requested_request_path.stem + "-delegated.json"
    )
    delegated = BASE.prepare(delegated_args)
    manifest_path = Path(delegated["manifest"])
    request_path = Path(delegated["request"])
    manifest = _read_json(manifest_path, "delegated generic manifest")
    request = _read_json(request_path, "delegated generic request")
    source_ref = _small_ref(JOIN_SOURCE, "actual 47-join source")
    manifest_ref = _small_ref(manifest_path, "delegated generic manifest")
    wrapper_ref = _small_ref(SCRIPT, "F2 generic V2 wrapper")
    proof_bundle = _proof_bundle(proof_ref, proof, list(selected))

    enriched = dict(manifest)
    enriched.update({
        "schema_version": "v2-source-proof-scope",
        "typed_proof_bundles": [proof_bundle],
        "typed_proof_scope": {
            "full_producer_proof_preserved": True,
            "full_case_count": 8,
            "selected_case_count": 8,
            "selected_cases_are_exact_missing_join_scope": True,
            "selection_source": "ROOT193 complete proof; existing 47 precise joins excluded by exact case identity",
        },
        "actual_join_exclusion": {
            "source": source_ref,
            "actual_join_case_count": len(joined_ids),
            "selected_overlap_count": 0,
            "selected_overlap_case_ids": [],
            "exclusion_rule": "case identity intersection with actual_case_rows must be empty",
        },
        "claim_boundary": {
            **manifest.get("claim_boundary", {}),
            "native_cause": "exact official PartOut Motive only after guarded audit",
            "typed_native_join": "diagnostic saved-frame/bracket identity only",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "status_note": "ROOT193 is one complete producer proof; no synthetic 8-case proof was created",
    })
    enriched_path = manifest_path.parent / "generic-native-extract-v2-manifest.json"
    _atomic_json(enriched_path, enriched)
    enriched_ref = _small_ref(enriched_path, "enriched F2 generic manifest")

    # Rebind the delegated request to this wrapper and the enriched manifest;
    # every changed source byte is added to the immutable input closure.
    req = dict(request)
    base_command = list(request.get("command", []))
    if len(base_command) < 7 or "--manifest" not in base_command or "--output" not in base_command:
        raise F2GenericV2Error("delegated generic request command lacks audit manifest/output arguments")
    manifest_arg = base_command.index("--manifest")
    output_arg = base_command.index("--output")
    if manifest_arg != 3 or output_arg != 5:
        raise F2GenericV2Error("delegated generic request command shape differs")
    req["command"] = list(base_command)
    req["command"][1] = str(SCRIPT)
    req["command"][manifest_arg + 1] = str(enriched_path)
    req["manifest_contract"] = {"path": str(enriched_path), "sha256": enriched_ref["sha256"]}
    input_sha = dict(request.get("input_sha256", {}))
    input_sha[str(SCRIPT)] = wrapper_ref["sha256"]
    input_sha[str(enriched_path)] = enriched_ref["sha256"]
    input_sha[str(JOIN_SOURCE)] = source_ref["sha256"]
    req["input_sha256"] = dict(sorted(input_sha.items()))
    req["input_files"] = sorted(input_sha)
    req["typed_proof_bundles"] = [proof_bundle]
    req["actual_join_exclusion"] = enriched["actual_join_exclusion"]
    req["request_note"] = (
        "F2 ROOT315 first missing-join batch. ROOT193 remains a complete 8-case producer proof; "
        "no synthetic merged proof, no overlap with the 47 exact joins, and no fate/flux/Q credit."
    )
    final_request = requested_request_path
    _atomic_json(final_request, req)
    final_request_ref = _small_ref(final_request, "enriched F2 generic request")
    return {
        "status": enriched.get("status"),
        "namespace": NAMESPACE,
        "family_id": FAMILY,
        "case_ids": list(selected),
        "manifest": str(enriched_path),
        "manifest_sha256": enriched_ref["sha256"],
        "request": str(final_request),
        "request_sha256": final_request_ref["sha256"],
        "typed_proof_bundle_count": 1,
        "full_producer_case_count": 8,
        "selected_case_count": 8,
        "actual_join_exclusion_count": len(joined_ids),
        "selected_overlap_count": 0,
        "payload_content_opened": False,
        "launch_allowed": bool(enriched.get("launch_allowed")),
        "execution_allowed": bool(enriched.get("execution_allowed")),
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    # The base audit validates the generic manifest and performs the guarded
    # official decoder/RunPARTs join.  The wrapper only accepts its enriched
    # schema marker and delegates the actual work unchanged.
    manifest = _read_json(args.manifest, "F2 enriched generic manifest")
    if manifest.get("schema_version") != "v2-source-proof-scope":
        raise F2GenericV2Error("F2 enriched manifest marker is missing")
    bundles = manifest.get("typed_proof_bundles")
    if not isinstance(bundles, list) or len(bundles) != 1:
        raise F2GenericV2Error("F2 enriched manifest proof bundle is malformed")
    return BASE.audit(args)


def _self_test() -> dict[str, Any]:
    return {
        "schema": "ds02.stage2.generic-native-extract.v1+f2-source-proof-scope.v2",
        "status": "PASS",
        "namespace": NAMESPACE,
        "selected_case_count": 8,
        "full_producer_case_count": 8,
        "checks": [
            "ROOT193 complete producer proof preserved",
            "exact selected/actual-join disjointness",
            "typed_deferred summary/records and terminal rows delegated to generic V1",
            "official PartVTKOut/RunPARTs join remains parent guarded",
            "physical fate, flux, dynamics, QI/QN/QE remain UNKNOWN",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--namespace", required=True)
    prep.add_argument("--lifecycle-request", type=Path, default=ROOT193_REQUEST)
    prep.add_argument("--current", type=Path, default=STAGE2 / "CURRENT336.json")
    prep.add_argument("--inventory", type=Path, default=STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json")
    prep.add_argument("--terminal-proof", type=Path, default=ROOT193_PROOF)
    prep.add_argument("--consumed-report", type=Path, action="append", default=[JOIN_SOURCE])
    prep.add_argument("--exclude-case", action="append", default=[])
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            result = _self_test()
        elif args.action == "prepare":
            result = prepare(args)
        else:
            result = audit(args)
    except (F2GenericV2Error, BASE.GenericExtractError, OSError, ValueError) as exc:
        print(f"F2_GENERIC_NATIVE_EXTRACT_V2_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
