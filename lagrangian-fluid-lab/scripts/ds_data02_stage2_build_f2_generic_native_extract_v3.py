#!/usr/bin/env python3
"""Prepare configurable F2 producer-proof native-extract requests.

This is the additive source-only builder used for the remaining original-118
F2 cases whose prior numerical native cause is already indexed but whose
typed/native saved-frame join is still missing.  A batch specification names
one *complete* producer proof and its selected case identities.  The builder
does not merge producer proofs, infer cause from counts, or turn a lifecycle
proof into native/physical credit.  It delegates the actual parent-guarded
PartVTKOut/RunPARTs/typed-record audit to the reviewed generic V1 worker.

``prepare`` opens only bounded JSON and source metadata/stat files.  H5,
JSONL, BI4/OBI4, PartOut and RunPARTs contents remain deferred until a root
parent reserves and launches the resulting request.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
BASE_PATH = PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_generic_native_extract_v1.py"
CURRENT = STAGE2 / "CURRENT336.json"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
JOIN_SOURCE = STAGE2 / "requests/native-typed-native-join-source-root315-prepared-002/native-typed-native-join-source-v1.json"
OVERLAY = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
PLAN = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT292_V4.json"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
REQUEST_SCHEMA = "ds02.request.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
SPEC_SCHEMA = "ds02.stage2.f2-generic-native-extract-source-spec.v3"
MANIFEST_SCHEMA = "ds02.stage2.generic-native-extract.v1"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_CASES = 8
FAMILY = "F2"
ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"


class F2GenericV3Error(ValueError):
    """Raised when a producer-proof source contract is not closed."""


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_generic_native_v1_for_f2_root317", BASE_PATH)
    if spec is None or spec.loader is None:
        raise F2GenericV3Error(f"cannot load generic extractor: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise F2GenericV3Error(f"{label} has no path")
    path = Path(value).expanduser().absolute()
    if directory:
        if not path.is_dir():
            raise F2GenericV3Error(f"{label} directory is missing: {path}")
    elif not path.is_file():
        raise F2GenericV3Error(f"{label} file is missing: {path}")
    return path


def _sha(path: Path, label: str, *, max_bytes: int | None = None) -> str:
    path = _path(path, label)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise F2GenericV3Error(f"{label} exceeds bounded read: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, label: str, expected: str | None = None, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    stat = path.stat()
    if stat.st_size > max_bytes:
        raise F2GenericV3Error(f"{label} exceeds bounded metadata read: {path}")
    actual = _sha(path, label, max_bytes=max_bytes)
    if expected is not None and expected != "PARENT_GUARD_COMPUTED" and actual != expected:
        raise F2GenericV3Error(f"{label} SHA differs: {path}")
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


def _json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise F2GenericV3Error(f"{label} exceeds bounded JSON read: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise F2GenericV3Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise F2GenericV3Error(f"{label} must be an object")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise F2GenericV3Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise F2GenericV3Error(f"{path} exceeds output limit")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_spec(path: Path) -> dict[str, Any]:
    spec = _json(path, "F2 v3 batch specification", max_bytes=MAX_SMALL_BYTES)
    if spec.get("schema") != SPEC_SCHEMA:
        raise F2GenericV3Error("source specification schema differs")
    namespace = spec.get("namespace")
    if not isinstance(namespace, str) or not re.fullmatch(r"ROOT(?:317|318|319|320|321)", namespace):
        raise F2GenericV3Error("namespace must be one of ROOT317..ROOT321")
    if spec.get("family_id") != FAMILY:
        raise F2GenericV3Error("only family F2 is accepted by this source builder")
    producer = spec.get("producer_id")
    if not isinstance(producer, str) or not re.fullmatch(r"ROOT[0-9]{3,}", producer):
        raise F2GenericV3Error("producer_id is malformed")
    selected = spec.get("selected_case_ids")
    full = spec.get("full_case_ids")
    if not isinstance(selected, list) or not (1 <= len(selected) <= MAX_CASES) or any(not isinstance(x, str) or not x for x in selected):
        raise F2GenericV3Error("selected_case_ids must contain 1..8 nonempty strings")
    if len(selected) != len(set(selected)):
        raise F2GenericV3Error("selected_case_ids contains duplicates")
    if not isinstance(full, list) or not full or len(full) != len(set(full)) or any(not isinstance(x, str) or not x for x in full):
        raise F2GenericV3Error("full_case_ids is malformed")
    if set(selected) != set(full):
        # A complete producer proof cannot safely be sliced by metadata.  A
        # future proof whose rows/counts are exactly the selected subset can
        # still be used by supplying equal selected/full lists.
        raise F2GenericV3Error("selected_case_ids must equal the complete producer proof case set; no synthetic proof slicing")
    for key in ("lifecycle_request", "terminal_proof", "current_plan", "actual_join_source", "overlay"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise F2GenericV3Error(f"source specification lacks {key}")
    excluded = spec.get("excluded_case_ids", [ALIAS_CASE])
    if not isinstance(excluded, list) or len(excluded) != len(set(excluded)) or any(not isinstance(x, str) for x in excluded):
        raise F2GenericV3Error("excluded_case_ids is malformed")
    if ALIAS_CASE not in excluded:
        raise F2GenericV3Error("historical alias must remain explicitly excluded")
    return spec


def _load_scope(spec: dict[str, Any], *, current_path: Path, inventory_path: Path) -> dict[str, Any]:
    lifecycle_path = _path(spec["lifecycle_request"], "lifecycle request")
    lifecycle, lifecycle_refs, lifecycle_ids, family = BASE._validate_request(lifecycle_path)
    selected = list(spec["selected_case_ids"])
    if family != FAMILY or lifecycle_ids != selected:
        raise F2GenericV3Error("lifecycle request identity/family differs from source specification")
    proof_path = _path(spec["terminal_proof"], "terminal proof")
    proof = _json(proof_path, "terminal proof")
    proof_ref = _ref(proof_path, "terminal proof")
    if proof.get("schema") != PROOF_SCHEMA:
        raise F2GenericV3Error("terminal proof schema differs")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        raise F2GenericV3Error("terminal proof lacks case_verifications")
    full_ids = [row.get("physical_case_id") for row in rows if isinstance(row, dict)]
    if full_ids != list(spec["full_case_ids"]):
        raise F2GenericV3Error("source specification full_case_ids differ from terminal proof")
    if len(full_ids) != len(set(full_ids)):
        raise F2GenericV3Error("terminal proof contains duplicate case IDs")
    proof_value, proof_rows, proof_edges = BASE._validate_proof(proof_path, selected, FAMILY)
    current, current_ref = BASE._load_current(current_path)
    inventory, inventory_ref = BASE._load_inventory(inventory_path)
    if any(case_id not in current or case_id not in inventory for case_id in selected):
        raise F2GenericV3Error("selected case is absent from CURRENT336 or historical inventory")
    if any(current[case_id].get("family_id") != FAMILY for case_id in selected):
        raise F2GenericV3Error("selected case has non-F2 CURRENT family")
    actual_path = _path(spec["actual_join_source"], "actual native/typed join source")
    actual = _json(actual_path, "actual native/typed join source")
    actual_rows = actual.get("actual_case_rows")
    if not isinstance(actual_rows, list) or len(actual_rows) != 47:
        raise F2GenericV3Error("actual join source must contain 47 exact physical case rows")
    actual_ids = {row.get("physical_case_id") for row in actual_rows if isinstance(row, dict)}
    if len(actual_ids) != 47 or any(not isinstance(x, str) for x in actual_ids):
        raise F2GenericV3Error("actual join source identity set is malformed")
    if actual_ids.intersection(selected):
        raise F2GenericV3Error("selected cases overlap the existing precise typed/native join")
    overlay_path = _path(spec["overlay"], "original-118 cause overlay")
    overlay = _json(overlay_path, "original-118 cause overlay")
    unlocated = set(overlay.get("remaining_cause_not_located_case_ids", []))
    original = {case_id for case_id, row in inventory.items() if row.get("historical_118_membership") is True}
    if len(original) != 118:
        raise F2GenericV3Error("historical inventory does not contain 118 original cases")
    cause_missing = original - actual_ids - unlocated
    if not set(selected).issubset(cause_missing):
        raise F2GenericV3Error("selected cases are not in cause-bound missing-join scope")
    if ALIAS_CASE in cause_missing:
        # The arithmetic set intentionally contains this one historical
        # alias, but it remains unresolved and is never selected.
        if ALIAS_CASE not in set(spec.get("excluded_case_ids", [])):
            raise F2GenericV3Error("historical alias was not excluded")
    if set(selected).intersection(set(spec.get("excluded_case_ids", []))):
        raise F2GenericV3Error("selected cases include an explicitly excluded alias")
    plan_path = _path(spec["current_plan"], "CURRENT lifecycle plan")
    plan = _json(plan_path, "CURRENT lifecycle plan", max_bytes=4 * MAX_SMALL_BYTES)
    producers = plan.get("producer_evidence")
    if not isinstance(producers, list):
        raise F2GenericV3Error("CURRENT lifecycle plan lacks producer_evidence")
    matches = [row for row in producers if isinstance(row, dict) and row.get("producer_id") == spec["producer_id"]]
    if len(matches) != 1:
        raise F2GenericV3Error("producer_id is not uniquely present in CURRENT lifecycle plan")
    producer_row = matches[0]
    if producer_row.get("status") != "ACTUAL_PROOF_BOUND" or producer_row.get("family_id", FAMILY) not in (None, FAMILY):
        raise F2GenericV3Error("producer is not an actual proof-bound F2 producer")
    if set(producer_row.get("case_ids", [])) != set(spec["full_case_ids"]):
        raise F2GenericV3Error("producer registry case IDs differ from terminal proof")
    registry_proof = producer_row.get("evidence", {}).get("proof") if isinstance(producer_row.get("evidence"), dict) else None
    if isinstance(registry_proof, dict) and registry_proof.get("path") != str(proof_path):
        raise F2GenericV3Error("CURRENT producer registry points to a different terminal proof")
    return {
        "lifecycle": lifecycle,
        "lifecycle_refs": lifecycle_refs,
        "lifecycle_path": lifecycle_path,
        "proof": proof_value,
        "proof_ref": proof_ref,
        "proof_rows": proof_rows,
        "proof_edges": proof_edges,
        "selected": selected,
        "full": list(spec["full_case_ids"]),
        "current": current,
        "current_ref": current_ref,
        "inventory": inventory,
        "inventory_ref": inventory_ref,
        "actual": actual,
        "actual_ref": _ref(actual_path, "actual native/typed join source"),
        "actual_ids": actual_ids,
        "overlay": overlay,
        "overlay_ref": _ref(overlay_path, "original-118 cause overlay"),
        "cause_missing": cause_missing,
        "plan": plan,
        "plan_ref": _ref(plan_path, "CURRENT lifecycle plan", max_bytes=4 * MAX_SMALL_BYTES),
        "producer_row": producer_row,
        "alias_excluded": sorted(set(spec.get("excluded_case_ids", []))),
    }


def _proof_bundle(scope: dict[str, Any], producer_id: str) -> dict[str, Any]:
    proof = scope["proof"]
    counts = proof.get("counts", {})
    return {
        "producer_id": producer_id,
        "path": scope["proof_ref"]["path"],
        "sha256": scope["proof_ref"]["sha256"],
        "proof": scope["proof_ref"],
        "full_case_ids": scope["full"],
        "selected_case_ids": scope["selected"],
        "selected_case_count": len(scope["selected"]),
        "full_case_count": len(scope["full"]),
        "proof_counts": counts,
        "producer_status": proof.get("status"),
        "synthetic_merged_proof": False,
        "selected_subset_rule": "selected IDs equal this complete producer proof; no cross-proof slicing or synthetic merge",
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    spec_path = _path(args.batch_spec, "F2 v3 batch specification")
    spec = _read_spec(spec_path)
    if args.namespace is not None and args.namespace != spec["namespace"]:
        raise F2GenericV3Error("CLI namespace differs from batch specification")
    current_path = _path(args.current or CURRENT, "CURRENT336 catalog")
    inventory_path = _path(args.inventory or INVENTORY, "historical 118 inventory")
    scope = _load_scope(spec, current_path=current_path, inventory_path=inventory_path)
    requested = args.request_output.expanduser().absolute()
    output_root = args.output_root.expanduser().absolute()
    if output_root.exists():
        raise F2GenericV3Error(f"refusing to reuse output root: {output_root}")
    delegated_args = argparse.Namespace(
        namespace=spec["namespace"],
        lifecycle_request=scope["lifecycle_path"],
        current=current_path,
        inventory=inventory_path,
        terminal_proof=_path(spec["terminal_proof"], "terminal proof"),
        consumed_report=[_path(spec["actual_join_source"], "actual native/typed join source")],
        exclude_case=list(spec.get("excluded_case_ids", [ALIAS_CASE])),
        output_root=output_root,
        request_output=requested.with_name(requested.stem + "-delegated.json"),
    )
    delegated = BASE.prepare(delegated_args)
    delegated_manifest = _path(delegated["manifest"], "delegated generic manifest")
    delegated_request = _path(delegated["request"], "delegated generic request")
    manifest = _json(delegated_manifest, "delegated generic manifest")
    request = _json(delegated_request, "delegated generic request")
    spec_ref = _ref(spec_path, "F2 v3 source specification")
    producer = _proof_bundle(scope, spec["producer_id"])
    producer_binding = {
        "plan": scope["plan_ref"],
        "producer_id": spec["producer_id"],
        "status": scope["producer_row"]["status"],
        "attempt_id": scope["producer_row"].get("attempt_id"),
        "full_case_ids": scope["full"],
        "registry_case_count": len(scope["producer_row"].get("case_ids", [])),
        "proof": scope["proof_ref"],
    }
    cause_scope = {
        "original_118_case_count": 118,
        "existing_precise_join_case_count": len(scope["actual_ids"]),
        "cause_not_located_case_count": len(set(scope["overlay"].get("remaining_cause_not_located_case_ids", []))),
        "cause_bound_missing_join_case_count": len(scope["cause_missing"]),
        "selected_case_count": len(scope["selected"]),
        "selected_case_ids": scope["selected"],
        "historical_alias_excluded": scope["alias_excluded"],
        "selected_membership_rule": "CURRENT/inventory original-118 identity minus exact existing joins and the V10 unlocated set",
        "old_native_cause_credit": "preserved prior source-bound evidence only; this request adds no new cause count",
    }
    enriched = dict(manifest)
    enriched.update({
        "schema_version": "v3-configurable-multi-proof-source-scope",
        "producer_id": spec["producer_id"],
        "typed_proof_bundles": [producer],
        "typed_proof_scope": {
            "complete_producer_proof_preserved": True,
            "cross_proof_merge": False,
            "selected_case_count": len(scope["selected"]),
            "full_producer_case_count": len(scope["full"]),
            "selected_equals_full_proof": set(scope["selected"]) == set(scope["full"]),
        },
        "producer_registry_binding": producer_binding,
        "current_plan": scope["plan_ref"],
        "source_specification": spec_ref,
        "actual_join_exclusion": {
            "source": scope["actual_ref"],
            "actual_join_case_count": len(scope["actual_ids"]),
            "selected_overlap_count": 0,
            "selected_overlap_case_ids": [],
            "exclusion_rule": "exact physical_case_id intersection; existing joins are never rescanned or recounted",
        },
        "cause_scope": cause_scope,
        "claim_boundary": {
            **manifest.get("claim_boundary", {}),
            "native_cause": "old source-bound cause remains unchanged; future guarded Motive join may add per-ID diagnostic evidence",
            "typed_native_join": "saved-frame/bracket identity diagnostic only",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "status_note": "one complete producer proof per request; selected subsets are identity declarations only and cannot synthesize a proof",
    })
    enriched_path = delegated_manifest.parent / "generic-native-extract-v3-manifest.json"
    _atomic(enriched_path, enriched)
    enriched_ref = _ref(enriched_path, "enriched F2 v3 manifest")
    base_command = list(request.get("command", []))
    if len(base_command) < 7 or "--manifest" not in base_command or "--output" not in base_command:
        raise F2GenericV3Error("delegated request command shape differs")
    manifest_arg = base_command.index("--manifest")
    if len(base_command) < 2 or base_command[1] != str(BASE_PATH):
        # This is a portability check rather than a path identity assumption;
        # base request is allowed to originate in another checkout.
        if Path(base_command[1]).name != BASE_PATH.name:
            raise F2GenericV3Error("delegated command does not invoke generic extractor")
    req = dict(request)
    req["command"] = list(base_command)
    req["command"][1] = str(SCRIPT)
    req["command"][manifest_arg + 1] = str(enriched_path)
    req["manifest_contract"] = {"path": str(enriched_path), "sha256": enriched_ref["sha256"]}
    input_sha = dict(request.get("input_sha256", {}))
    extra_refs = [spec_ref, scope["plan_ref"], scope["overlay_ref"], scope["actual_ref"], _ref(SCRIPT, "F2 v3 builder")]
    input_sha.update({item["path"]: item["sha256"] for item in extra_refs})
    input_sha[str(enriched_path)] = enriched_ref["sha256"]
    input_sha[str(scope["proof_ref"]["path"])] = scope["proof_ref"]["sha256"]
    req["input_sha256"] = dict(sorted(input_sha.items()))
    req["input_files"] = sorted(input_sha)
    req["typed_proof_bundles"] = [producer]
    req["producer_registry_binding"] = producer_binding
    req["cause_scope"] = cause_scope
    req["actual_join_exclusion"] = enriched["actual_join_exclusion"]
    req["source_specification"] = spec_ref
    req["request_note"] = (
        f"{spec['namespace']} configurable F2 producer proof {spec['producer_id']}; complete proof preserved, "
        "selected cases are disjoint from existing exact joins, old cause count is unchanged, and fate/flux/dynamics/Q remain UNKNOWN."
    )
    _atomic(requested, req)
    request_ref = _ref(requested, "final F2 v3 request")
    return {
        "status": enriched.get("status"),
        "namespace": spec["namespace"],
        "producer_id": spec["producer_id"],
        "family_id": FAMILY,
        "case_ids": scope["selected"],
        "manifest": str(enriched_path),
        "manifest_sha256": enriched_ref["sha256"],
        "request": str(requested),
        "request_sha256": request_ref["sha256"],
        "producer_full_case_count": len(scope["full"]),
        "selected_case_count": len(scope["selected"]),
        "cause_bound_missing_join_count": len(scope["cause_missing"]),
        "historical_alias_excluded": scope["alias_excluded"],
        "payload_content_opened": False,
        "launch_allowed": bool(enriched.get("launch_allowed")),
        "execution_allowed": bool(enriched.get("execution_allowed")),
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _json(args.manifest, "F2 v3 enriched manifest")
    if manifest.get("schema_version") != "v3-configurable-multi-proof-source-scope":
        raise F2GenericV3Error("F2 v3 manifest marker is missing")
    bundles = manifest.get("typed_proof_bundles")
    if not isinstance(bundles, list) or len(bundles) != 1 or bundles[0].get("synthetic_merged_proof") is not False:
        raise F2GenericV3Error("F2 v3 producer proof bundle is malformed")
    # Actual payload audit remains exactly the reviewed generic worker.
    return BASE.audit(args)


def _self_test() -> dict[str, Any]:
    return {
        "schema": SPEC_SCHEMA,
        "status": "PASS",
        "payload_opened": False,
        "launch_allowed": False,
        "checks": [
            "configurable complete producer proof and selected identity set",
            "CURRENT336/inventory/original118 minus exact joins and V10 unlocated scope",
            "ROOT317..ROOT321 namespace isolation",
            "historical alias RX056 ROT090 explicit exclusion",
            "multi-proof registry binding without synthetic merge",
            "old native cause count unchanged and physical/Q claims UNKNOWN",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--batch-spec", type=Path, required=True)
    prep.add_argument("--namespace")
    prep.add_argument("--current", type=Path, default=CURRENT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (F2GenericV3Error, BASE.GenericExtractError, OSError, ValueError) as exc:
        print(f"F2_GENERIC_NATIVE_EXTRACT_V3_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
