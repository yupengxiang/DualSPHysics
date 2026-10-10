#!/usr/bin/env python3
"""ROOT345 handoff V3 for the actual runtime-v2 receipt shape.

The runtime receipt stores the producer identity under ``receipt.request``;
it does not duplicate ``sentinel_id``/``grid_label``/``case_id`` at the
receipt top level.  Handoff V2 checked those fields at the wrong level and
would reject a real completed GenCase receipt.  V3 reuses the strict V2 edge
validator with only this ABI correction, then binds its own source and V2
modules into the generated whole-parent closure.  Deferred GenCase products
remain stat-only and QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v2.py"
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-native-initial-support-handoff.v3"
NO_CREDIT = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class HandoffV3Failure(RuntimeError):
    pass


def _load_v2() -> Any:
    spec = importlib.util.spec_from_file_location("root345_handoff_v2_for_v3", V2_PATH)
    if spec is None or spec.loader is None:
        raise HandoffV3Failure(f"cannot import strict ROOT345 V2: {V2_PATH}")
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


V2 = _load_v2()
_V2_IDENTITY = V2._identity
SCRIPT_DIR = HERE.parents[4] / "lagrangian-fluid-lab" / "scripts"
if not (SCRIPT_DIR / "ds_data02_runtime_v10_git_bound.py").is_file():
    # The isolated source worktree predates the runtime-V10 files; the
    # primary worktree is used only to bind their small source records during
    # this source-only build.  After integration, HERE.parents[4] resolves to
    # the primary and this fallback is unused.
    SCRIPT_DIR = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts")
V10_FILES = (
    "ds_data02_runtime_v10_git_bound.py", "ds_data02_runtime_v9_git_bound.py",
    "ds_data02_runtime_v8.py", "ds_data02_runtime_v6.py", "ds_data02_runtime_v2.py",
    "ds_data02_git_launch_state_v1.py", "ds_data02_git_launch_state_v2.py",
    "ds_data02_git_launch_state_v3.py",
)


def _identity_receipt(value: dict[str, Any], expected: dict[str, str], label: str, errors: list[str]) -> None:
    if label.endswith(" execution receipt") or label.endswith(" receipt"):
        nested = value.get("request")
        if not isinstance(nested, dict):
            errors.append(f"{label} lacks nested runtime receipt.request identity")
            return
        _V2_IDENTITY(nested, expected, f"{label}.request", errors)
        return
    _V2_IDENTITY(value, expected, label, errors)


def _install_receipt_abi() -> None:
    # V2._edge resolves _identity in its own module globals.  Replacing only
    # that function keeps every other V2 check (raw request SHA, exact request
    # document, output_root, returncode and product path contracts) unchanged.
    V2._identity = _identity_receipt


def _record(path: Path, label: str) -> dict[str, Any]:
    return V2._source(path, label, required=True)[0] or {}


def _augment(result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    manifest_path = Path(result["manifest_path"]).absolute()
    request_path = Path(result["request_path"]).absolute()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    package_path = output_dir / "handoff-package.json"
    package = {"schema": SCHEMA, "status": result["status"],
               "manifest": {"path": str(manifest_path)}, "request": {"path": str(request_path)},
               "scientific_qualification": dict(NO_CREDIT), "production_payload_read_by_builder": False}
    records = manifest.get("static_source_records")
    if not isinstance(records, list):
        raise HandoffV3Failure("V2 handoff output lacks static_source_records")
    extra_paths = (V2_PATH, HERE / "stage2_three_sentinel_owner_grid_native_initial_support_handoff_v3.py",
                   *(SCRIPT_DIR / name for name in V10_FILES))
    existing = {item.get("path"): item for item in records if isinstance(item, dict) and isinstance(item.get("path"), str)}
    for path in extra_paths:
        value, error = V2._source(path, f"ROOT345 handoff V3 closure: {path.name}", required=True)
        if error or value is None:
            raise HandoffV3Failure(error or f"cannot bind {path}")
        existing[value["path"]] = value
    ordered = [existing[key] for key in sorted(existing)]
    digest_edges = [{"path": item["path"], "sha256": item.get("sha256")} for item in ordered]
    import hashlib
    identity = hashlib.sha256(json.dumps(digest_edges, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest["schema"] = SCHEMA
    manifest["source_identity_digest"] = identity
    manifest["static_source_records"] = ordered
    manifest.setdefault("whole_parent_v10", {})["runtime_wrapper"] = {
        "schema": "ds02.stage2.runtime-v10-git-bound.v1",
        "files": [item["path"] for item in ordered if Path(item["path"]).name in V10_FILES],
        "closure_complete": all(Path(item).is_file() for item in [str(SCRIPT_DIR / name) for name in V10_FILES]),
    }
    # The V2 request is newly produced and execution-disabled; bind the exact
    # rewritten manifest record rather than retaining a pre-augmentation SHA.
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = V2._source(manifest_path, "ROOT345 handoff V3 manifest", required=True)[0]
    if manifest_record is None:
        raise HandoffV3Failure("cannot record V3 handoff manifest")
    static = {item["path"]: item for item in ordered}; static[manifest_record["path"]] = manifest_record
    request["schema"] = V2.REQUEST_SCHEMA; request["variant_schema"] = SCHEMA
    request["source_identity_digest"] = identity; request["manifest"] = manifest_record
    request["input_records"] = {key: static[key] for key in sorted(static)}
    request["input_files"] = sorted(static)
    request["input_sha256"] = {key: static[key]["sha256"] for key in sorted(static) if isinstance(static[key].get("sha256"), str)}
    request["execution_allowed"] = False; request["status"] = manifest["status"]
    request["runtime_v10_source_closure"] = manifest["whole_parent_v10"]["runtime_wrapper"]
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    request_record = V2._source(request_path, "ROOT345 handoff V3 request", required=True)[0]
    if request_record is None:
        raise HandoffV3Failure("cannot record V3 handoff request")
    package.update({"manifest": manifest_record, "request": request_record, "source_identity_digest": identity,
                    "static_source_count": len(static), "scientific_qualification": dict(NO_CREDIT)})
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.update({"manifest_path": str(manifest_path), "request_path": str(request_path),
                   "package_path": str(package_path), "manifest": manifest, "request": request, "package": package})
    return result


def build(product_map: Path, output_dir: Path, *, decoder: Path | None = None) -> dict[str, Any]:
    _install_receipt_abi()
    V2.SCHEMA = SCHEMA
    # V2's build resolves _edge and _identity from its module globals, so this
    # is an actual producer-edge adapter rather than a report postprocessor.
    result = V2.build(product_map, output_dir, decoder=decoder)
    return _augment(result, Path(output_dir).absolute())


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root345-handoff-v3-") as td:
        root = Path(td)
        product_map = V2._fixture_map(root)
        # Match the actual runtime receipt ABI before the first build: the
        # identity lives only in receipt.request, while the proof/product
        # records carry the receipt's updated raw-byte SHA.
        product_value = json.loads(product_map.read_text())
        for row in product_value["products"]:
            proof_path = Path(row["actual_producer_proof"]["path"])
            proof = json.loads(proof_path.read_text())
            receipt_path = Path(proof["products"]["gencase_receipt"]["path"])
            receipt = json.loads(receipt_path.read_text())
            for key in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id"):
                receipt.pop(key, None)
            receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
            receipt_sha = V2._sha(receipt_path.read_bytes())
            proof["products"]["gencase_receipt"]["sha256"] = receipt_sha
            proof_path.write_text(json.dumps(proof, sort_keys=True) + "\n")
            row["actual_producer_proof"]["sha256"] = V2._sha(proof_path.read_bytes())
        product_map.write_text(json.dumps(product_value, indent=2, sort_keys=True) + "\n")
        result = build(product_map, root / "out")
        assert result["manifest"]["schema"] == SCHEMA
        assert result["manifest"]["scientific_qualification"] == NO_CREDIT
        assert len(result["manifest"]["rows"]) == 9
        # A real runtime receipt has no duplicated identity fields at its top
        # level.  Remove them from a fixture receipt and ensure the nested
        # request is still accepted by the exact same edge path.
        receipt_path = next(root.glob("**/execution-receipt.json"))
        receipt = json.loads(receipt_path.read_text())
        for key in ("sentinel_id", "grid_label", "family_id", "physical_case_id", "case_id", "attempt_id"):
            receipt.pop(key, None)
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
        # Existing proof receipt SHA is deliberately stale after this mutation;
        # strict source edge verification must reject it, rather than silently
        # accepting a changed receipt.  This exercises the raw-byte edge.
        bad_map = json.loads(product_map.read_text())
        bad_proof = Path(bad_map["products"][0]["actual_producer_proof"]["path"])
        proof = json.loads(bad_proof.read_text()); proof["products"]["gencase_receipt"]["sha256"] = "0" * 64
        bad_proof.write_text(json.dumps(proof, sort_keys=True) + "\n")
        bad_result = build(product_map, root / "bad-out")
        assert bad_result["status"].startswith("WAITING_")
        assert any("declared SHA" in error for row in bad_result["manifest"]["validation_errors"]
                   for error in row["errors"])
    print("PASS_ROOT345_HANDOFF_V3_RUNTIME_NESTED_RECEIPT_EDGE_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.product_map is None or args.output_dir is None:
            parser.error("--build requires --product-map and --output-dir")
        result = build(args.product_map, args.output_dir, decoder=args.decoder)
        print(json.dumps({"status": result["status"], "manifest": result["manifest_path"],
                          "request": result["request_path"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (HandoffV3Failure, V2.HandoffV2Failure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT345_HANDOFF_V3: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
