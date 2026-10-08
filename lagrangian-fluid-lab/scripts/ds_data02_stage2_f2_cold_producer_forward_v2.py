#!/usr/bin/env python3
"""Forward V40 cold-producer contracts for a relocated CURRENT view.

V39 made the distinction between the exact CURRENT336 source (``df7e...``)
and the historical ``aabfb...`` overlay explicit, but it did not change the
runtime request consumed by the relocated V15 reader.  In a real relocation,
the alias JSON contains a new path and therefore a new digest.  V40 binds the
new digest to the V15 request and to the small label-header/fresh-proof
contract while retaining the original CURRENT digest as source identity.

This module is metadata-only at build time.  It may read CURRENT JSON and
small request/header JSON, but never opens trajectory H5, BI4, PartOut, or a
large typed result.  The V39 contract and all old requests remain immutable.
The returned engine map deliberately says which parts are consumed by the
future guarded cold worker; V39 itself is only a contract builder.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA_V39 = "ds02.stage2.f2-fresh-v16-source-contract.v1"
SCHEMA_V15 = "ds02.stage2.f2-s1-replay-request.v15"
SCHEMA_CONTRACT = "ds02.stage2.f2-fresh-v16-source-contract.v40"
SCHEMA_RELOCATION = "ds02.stage2.f2-current-relocated-runtime-view.v40"
SCHEMA_HEADER = "ds02.stage2.f2-v16-label-header.v1"
SCHEMA_PROOF = "ds02.stage2.f2-fresh-v16-source-proof.v40"
FORWARD_SCHEMA = "ds02.stage2.f2-cold-producer-v40-forward.v1"
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class ColdProducerV40Error(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ColdProducerV40Error(f"cannot read {role}: {target}: {error}") from error
    if not isinstance(value, dict):
        raise ColdProducerV40Error(f"{role} must be a JSON object: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ColdProducerV40Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ColdProducerV40Error(f"{role} must be a lowercase SHA-256")
    return value


def _load_canonical(path: Path | str, schema: str, role: str) -> dict[str, Any]:
    value = load_json(path, role)
    if value.get("schema") != schema:
        raise ColdProducerV40Error(f"{role} schema differs: {value.get('schema')!r}")
    if value.get("sha256") != canonical_sha(value):
        raise ColdProducerV40Error(f"{role} canonical SHA differs")
    return value


def _actual_current(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    value = load_json(target, "exact CURRENT336")
    digest = sha256_file(target)
    if digest != ACTUAL_CURRENT_SHA:
        raise ColdProducerV40Error("exact CURRENT336 is not the frozen df7e source")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) <= 78 or not isinstance(cases[78], Mapping):
        raise ColdProducerV40Error("CURRENT case 78 is malformed")
    return {"path": str(target), "sha256": digest, "bytes": target.stat().st_size,
            "case_index": 78, "case": copy.deepcopy(cases[78])}


def _same_except_case_path(actual: Mapping[str, Any], overlay: Mapping[str, Any], target_path: str) -> None:
    left = copy.deepcopy(dict(actual))
    right = copy.deepcopy(dict(overlay))
    for value in (left, right):
        cases = value.get("cases")
        if not isinstance(cases, list) or len(cases) <= 78 or not isinstance(cases[78], Mapping):
            raise ColdProducerV40Error("relocated CURRENT case 78 is malformed")
        trajectory = cases[78].get("trajectory")
        if not isinstance(trajectory, Mapping):
            raise ColdProducerV40Error("relocated CURRENT trajectory is malformed")
        trajectory = dict(trajectory)
        trajectory["path"] = "__V40_RELOCATED_TRAJECTORY__"
        cases[78] = dict(cases[78])
        cases[78]["trajectory"] = trajectory
    if left != right:
        raise ColdProducerV40Error("relocated CURRENT changed fields besides case-78 trajectory.path")
    observed_path = str(overlay["cases"][78]["trajectory"]["path"])
    if observed_path != target_path:
        raise ColdProducerV40Error("relocated CURRENT trajectory path differs from target")


def make_relocated_overlay(*, actual_current: Path | str, target_trajectory: Path | str,
                           output: Path | str) -> dict[str, Any]:
    """Create the runtime alias and its source-identity manifest.

    This is the actual producer-side relocation step: the digest is computed
    from the newly written JSON and is never copied from V39's historical
    ``aabfb`` constant.
    """
    info = _actual_current(actual_current)
    target = Path(target_trajectory).expanduser().resolve()
    if not target.is_absolute():
        raise ColdProducerV40Error("relocated trajectory path must be absolute")
    value = load_json(info["path"], "exact CURRENT336")
    cases = value["cases"]
    cases[78] = dict(cases[78])
    trajectory = dict(cases[78].get("trajectory", {}))
    original_path = trajectory.get("path")
    if not isinstance(original_path, str) or Path(original_path).expanduser().resolve() == target:
        raise ColdProducerV40Error("relocation target must differ from the original trajectory path")
    trajectory["path"] = str(target)
    cases[78]["trajectory"] = trajectory
    _same_except_case_path(json.loads(Path(info["path"]).read_text(encoding="utf-8")), value,
                           str(target))
    out = write_new(output, value)
    overlay_sha = sha256_file(out)
    if overlay_sha in {ACTUAL_CURRENT_SHA, HISTORICAL_OVERLAY_SHA}:
        raise ColdProducerV40Error("new relocation view unexpectedly reuses a frozen digest")
    manifest = {
        "schema": SCHEMA_RELOCATION,
        "original_current": {"path": info["path"], "sha256": ACTUAL_CURRENT_SHA,
                              "bytes": info["bytes"], "case_index": 78,
                              "exact_current_source": True},
        "relocated_current_view": {
            "path": str(out), "sha256": overlay_sha, "bytes": out.stat().st_size,
            "case_index": 78, "trajectory_path": str(target),
            "exact_current_source": False,
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW",
        },
        "historical_v39_overlay_sha256": HISTORICAL_OVERLAY_SHA,
        "changed_field": "cases[78].trajectory.path",
        "original_path_fallback": "FORBIDDEN",
        "hdf5_bi4_content_read": False,
        "qualification": dict(UNKNOWN),
    }
    manifest["sha256"] = canonical_sha(manifest)
    manifest_path = Path(output).with_name(Path(output).name + ".manifest.json")
    write_new(manifest_path, manifest)
    return {"status": "READY_V40_RELOCATED_CURRENT_VIEW", "overlay": str(out),
            "manifest": str(manifest_path), "overlay_sha256": overlay_sha,
            "actual_current_sha256": ACTUAL_CURRENT_SHA, "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def _load_manifest(path: Path | str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _load_canonical(path, SCHEMA_RELOCATION, "V40 relocation manifest")
    original = manifest.get("original_current")
    relocated = manifest.get("relocated_current_view")
    if not isinstance(original, Mapping) or not isinstance(relocated, Mapping):
        raise ColdProducerV40Error("V40 relocation manifest lacks original/relocated bindings")
    actual_sha = _require_sha(original.get("sha256"), "manifest.original_current.sha256")
    overlay_sha = _require_sha(relocated.get("sha256"), "manifest.relocated_current_view.sha256")
    if actual_sha != ACTUAL_CURRENT_SHA or overlay_sha in {actual_sha, HISTORICAL_OVERLAY_SHA}:
        raise ColdProducerV40Error("V40 manifest does not contain distinct actual/new-view identities")
    overlay_path = Path(str(relocated.get("path"))).expanduser()
    if sha256_file(overlay_path) != overlay_sha:
        raise ColdProducerV40Error("relocated CURRENT view SHA differs from manifest")
    value = load_json(overlay_path, "relocated CURRENT view")
    return manifest, dict(original), {**dict(relocated), "value": value}


def rebind_replay_v15(*, replay_request: Path | str, manifest: Path | str,
                      output: Path | str) -> dict[str, Any]:
    """Bind a V15 request to the newly generated overlay view.

    The original CURRENT identity is retained under ``current_source_identity``;
    the actionable V15 current binding uses only the newly observed overlay
    digest.  This prevents a historical V39 alias from being silently reused.
    """
    request = load_json(replay_request, "V15 replay request")
    if request.get("schema") != SCHEMA_V15:
        raise ColdProducerV40Error("replay request is not V15")
    manifest_path = Path(manifest).expanduser()
    manifest, original, relocated = _load_manifest(manifest_path)
    overlay_sha = relocated["sha256"]
    value = copy.deepcopy(request)
    binding = value.get("current_binding")
    if not isinstance(binding, dict):
        raise ColdProducerV40Error("V15 current_binding is missing")
    if binding.get("sha256") != original["sha256"]:
        raise ColdProducerV40Error("V15 source is not bound to the exact CURRENT before relocation")
    binding.update({
        "path": relocated["path"], "sha256": overlay_sha,
        "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW",
        "original_current_catalog_sha256": original["sha256"],
        "relocated_view_sha256": overlay_sha,
        "exact_current_source": False,
    })
    source_files = value.get("source_files")
    if not isinstance(source_files, list):
        raise ColdProducerV40Error("V15 source_files are missing")
    current_rows = [item for item in source_files
                    if isinstance(item, dict) and item.get("role") == "current_catalog"]
    if len(current_rows) != 1 or current_rows[0].get("sha256") != original["sha256"]:
        raise ColdProducerV40Error("V15 current_catalog source binding is not exact CURRENT")
    current_rows[0].update({"path": relocated["path"], "sha256": overlay_sha,
                            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW",
                            "original_sha256": original["sha256"]})
    profile = value.get("observer_profile")
    if not isinstance(profile, dict):
        raise ColdProducerV40Error("V15 observer_profile is missing")
    profile["current_binding_sha256"] = overlay_sha
    source_sha = profile.get("source_file_sha256")
    if not isinstance(source_sha, dict):
        raise ColdProducerV40Error("V15 observer_profile.source_file_sha256 is missing")
    source_sha["current_catalog"] = overlay_sha
    profile["sha256"] = canonical_sha(profile)
    value["relocation_source_identity"] = {
        "schema": SCHEMA_RELOCATION,
        "original_current_catalog_sha256": original["sha256"],
        "relocated_view_sha256": overlay_sha,
        "manifest_sha256": manifest["sha256"],
        "exact_current_claim": "REJECTED_FOR_RELOCATED_VIEW",
        "original_path_fallback": "FORBIDDEN",
    }
    value["source_bound_replay"] = dict(value.get("source_bound_replay", {}))
    value["source_bound_replay"].update({
        "current_view_scope": "RELOCATED_RUNTIME_CURRENT_VIEW",
        "current_view_sha256": overlay_sha,
        "original_current_identity_sha256": original["sha256"],
        "historical_v39_overlay_sha256": HISTORICAL_OVERLAY_SHA,
        "exact_current_source_bound": False,
    })
    value["v40_forward"] = {
        "schema": FORWARD_SCHEMA,
        "relocation_manifest": {"path": str(manifest_path),
                                "sha256": manifest["sha256"]},
        "original_current_catalog_sha256": original["sha256"],
        "relocated_current_view_sha256": overlay_sha,
        "v15_reader": "ds_data02_stage2_f2_replay_v15.py",
        "v15_reader_consumes_new_view_digest": True,
        "legacy_v39_contract_consumed": False,
        "hdf5_bi4_content_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    out = write_new(output, value)
    return {"status": "READY_V40_V15_RELOCATED_VIEW_REQUEST", "path": str(out),
            "sha256": sha256_file(out), "actual_current_sha256": original["sha256"],
            "relocated_view_sha256": overlay_sha, "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def build_contract(*, v39_contract: Path | str, relocated_v15: Path | str,
                   manifest: Path | str, output: Path | str) -> dict[str, Any]:
    old = _load_canonical(v39_contract, SCHEMA_V39, "V39 source contract")
    request = load_json(relocated_v15, "V40 relocated V15 request")
    if request.get("schema") != SCHEMA_V15:
        raise ColdProducerV40Error("relocated request is not V15")
    manifest_path = Path(manifest).expanduser()
    manifest_value, original, relocated = _load_manifest(manifest_path)
    overlay_sha = relocated["sha256"]
    binding = request.get("current_binding")
    if not isinstance(binding, Mapping) or binding.get("sha256") != overlay_sha:
        raise ColdProducerV40Error("relocated V15 request does not consume the new view digest")
    value = copy.deepcopy(old)
    source = value.get("expected", {}).get("source_binding")
    if not isinstance(source, dict):
        raise ColdProducerV40Error("V39 expected.source_binding is missing")
    source["binding_status"] = "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"
    source["current_catalog_sha256"] = overlay_sha
    source_files = source.get("source_files")
    if not isinstance(source_files, dict):
        raise ColdProducerV40Error("V39 source binding source_files is missing")
    source_files["current_catalog"] = overlay_sha
    value["derived_schema"] = SCHEMA_CONTRACT
    value["schema"] = SCHEMA_CONTRACT
    value["current_catalog_provenance"] = {
        "schema": SCHEMA_RELOCATION,
        "actual_current_catalog": {"sha256": original["sha256"], "path": original["path"],
                                    "exact_current_source": True},
        "relocated_runtime_view": {"sha256": overlay_sha, "path": relocated["path"],
                                    "exact_current_source": False},
        "historical_v39_overlay_sha256": HISTORICAL_OVERLAY_SHA,
        "legacy_aabfb_is_not_runtime_input": True,
        "source_identity_and_actionable_view_are_separate": True,
    }
    value["expected"]["source_binding_scope"] = {
        "binding_status_scope": "RELOCATED_RUNTIME_CURRENT_VIEW_ONLY",
        "actual_current_catalog_sha256": original["sha256"],
        "relocated_view_sha256": overlay_sha,
        "historical_v39_overlay_sha256": HISTORICAL_OVERLAY_SHA,
        "exact_current_claim": "REJECTED_FOR_RELOCATED_VIEW",
    }
    value["producer_metadata"] = dict(value.get("producer_metadata", {}))
    value["producer_metadata"]["v40_relocation_manifest_sha256"] = manifest_value["sha256"]
    value["v40_forward"] = {
        "schema": FORWARD_SCHEMA,
        "v39_contract_parent_sha256": old["sha256"],
        "relocated_v15_request": {"path": str(Path(relocated_v15).expanduser()),
                                   "sha256": sha256_file(relocated_v15)},
        "relocation_manifest": {"path": str(manifest_path),
                                "sha256": manifest_value["sha256"]},
        "actual_current_catalog_sha256": original["sha256"],
        "relocated_current_view_sha256": overlay_sha,
        "v15_reader_consumes_new_view_digest": True,
        "v39_builder_only_contract": True,
        "cold_engine_runtime_binding": "V40 relocated V15 request + this contract; not the stale V39 aabfb map",
        "hdf5_bi4_result_content_read_during_build": False,
        "quality": dict(UNKNOWN),
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "V40 is a source/header contract; it does not claim a cold H5/BI4 replay.",
        "The actual CURRENT df7e is source identity.  The generated overlay digest is the only actionable relocated V15 view.",
        "A fresh V16 label header must be produced by the guarded producer before fresh-proof/evaluator scoring.",
    ]
    value["sha256"] = canonical_sha(value)
    target = write_new(output, value)
    return {"status": "READY_V40_RELOCATED_SOURCE_CONTRACT", "path": str(target),
            "sha256": value["sha256"], "actual_current_sha256": original["sha256"],
            "relocated_view_sha256": overlay_sha, "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def build_fresh_proof(*, source_contract: Path | str, relocated_v15: Path | str,
                      label_header: Path | str, output: Path | str) -> dict[str, Any]:
    contract = _load_canonical(source_contract, SCHEMA_CONTRACT, "V40 source contract")
    request = load_json(relocated_v15, "V40 relocated V15 request")
    header = _load_canonical(label_header, SCHEMA_HEADER, "V16 label header")
    forward = contract.get("v40_forward", {})
    actual = _require_sha(forward.get("actual_current_catalog_sha256"), "contract actual CURRENT SHA")
    relocated = _require_sha(forward.get("relocated_current_view_sha256"), "contract relocated view SHA")
    binding = request.get("current_binding")
    if not isinstance(binding, Mapping) or binding.get("sha256") != relocated:
        raise ColdProducerV40Error("V15 request does not match V40 source contract")
    if header.get("current_catalog_sha256") != relocated:
        raise ColdProducerV40Error("V16 label header does not consume the new relocated view digest")
    source_identity = header.get("current_source_identity")
    if not isinstance(source_identity, Mapping) or source_identity.get("sha256") != actual:
        raise ColdProducerV40Error("V16 label header lacks exact original CURRENT source identity")
    if header.get("binding_status") != "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND":
        raise ColdProducerV40Error("V16 label header binding status is not the explicit relocated view scope")
    result = {
        "schema": SCHEMA_PROOF,
        "role": "DEVELOPMENT",
        "producer": {"label_header": {"path": str(Path(label_header).expanduser()),
                                         "sha256": sha256_file(label_header),
                                         "schema": SCHEMA_HEADER}},
        "source_binding": {
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "current_catalog_sha256": relocated,
            "current_source_identity_sha256": actual,
            "source_contract_sha256": contract["sha256"],
            "relocation_view_is_not_exact_current": True,
        },
        "fresh_proof_scope": {
            "v16_header_consumed_new_view_digest": True,
            "historical_v39_overlay_sha256_not_used_as_runtime_input": True,
            "hdf5_bi4_content_read_by_contract_builder": False,
            "raw_to_typed_credit": "PENDING_GUARDED_PRODUCER",
            "scientific_qualification": "UNKNOWN",
        },
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
    }
    result["sha256"] = canonical_sha(result)
    target = write_new(output, result)
    return {"status": "READY_V40_FRESH_PROOF_CONTRACT", "path": str(target),
            "sha256": result["sha256"], "actual_current_sha256": actual,
            "relocated_view_sha256": relocated, "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    overlay = sub.add_parser("make-relocated-overlay")
    overlay.add_argument("--actual-current", type=Path, required=True)
    overlay.add_argument("--target-trajectory", type=Path, required=True)
    overlay.add_argument("--output", type=Path, required=True)
    v15 = sub.add_parser("rebind-v15")
    v15.add_argument("--replay-request", type=Path, required=True)
    v15.add_argument("--manifest", type=Path, required=True)
    v15.add_argument("--output", type=Path, required=True)
    contract = sub.add_parser("build-contract")
    contract.add_argument("--v39-contract", type=Path, required=True)
    contract.add_argument("--relocated-v15", type=Path, required=True)
    contract.add_argument("--manifest", type=Path, required=True)
    contract.add_argument("--output", type=Path, required=True)
    proof = sub.add_parser("build-fresh-proof")
    proof.add_argument("--source-contract", type=Path, required=True)
    proof.add_argument("--relocated-v15", type=Path, required=True)
    proof.add_argument("--label-header", type=Path, required=True)
    proof.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "make-relocated-overlay":
            value = make_relocated_overlay(actual_current=args.actual_current,
                                            target_trajectory=args.target_trajectory,
                                            output=args.output)
        elif args.command == "rebind-v15":
            value = rebind_replay_v15(replay_request=args.replay_request,
                                      manifest=args.manifest, output=args.output)
        elif args.command == "build-contract":
            value = build_contract(v39_contract=args.v39_contract,
                                   relocated_v15=args.relocated_v15,
                                   manifest=args.manifest, output=args.output)
        else:
            value = build_fresh_proof(source_contract=args.source_contract,
                                      relocated_v15=args.relocated_v15,
                                      label_header=args.label_header, output=args.output)
    except (ColdProducerV40Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"cold producer V40: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
