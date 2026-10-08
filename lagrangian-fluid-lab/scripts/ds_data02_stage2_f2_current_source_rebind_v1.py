#!/usr/bin/env python3
"""Rebind the typed-only V16 header to the real CURRENT336 source.

The V37 copied producer contains a concrete, historical relocation bug.  It
made ``CURRENT336-case78-trajectory-overlay.json`` by changing one trajectory
path in the CURRENT JSON and then used the *SHA of that path overlay* as
``current_binding.sha256``.  The resulting ``aabfb...`` value is therefore a
JSON-overlay digest, not the CURRENT336 file digest.  This module records that
chain and builds a new metadata-only consumer sidecar whose accepted catalog
is the frozen V15 request plus the real CURRENT336 file.

The sidecar deliberately does not open the HDF5 trajectory, BI4 files, or the
62 MB V16 result.  It proves the small JSON source/case join, the exact
one-path overlay difference, and preservation of the existing result SHA.  It
does not claim that label-array values were re-read or that QI/QN/QE changed.
Existing V9/V10/V16 requests and reports are immutable historical inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
SCHEMA = "ds02.stage2.f2-current-source-rebind.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
FROZEN_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
SOURCE_CONTRACT_SCHEMA = "ds02.stage2.f2-fresh-v16-source-contract.v1"
ACTUAL_CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA256 = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
EXPECTED_RESULT_SHA256 = "1096e86ad3528bd6a5a7508aabd257ede428d5a5d90d2ec04f533fed6b4416f5"
EXPECTED_RESULT_BYTES = 62_366_240
EXPECTED_CASE_INDEX = 78
MAX_JSON_BYTES = 8 * 1024 * 1024
HEX64 = set("0123456789abcdef")
ALIAS_GENERATOR_V5 = SCRIPT_DIR / "ds_data02_stage2_f2_raw_portable_v5.py"
ALIAS_GENERATOR_V5_SHA256 = "3792088c24d61a22d1af3ef3652d7383fe70267690372d7dc32c622edfe6f934"


class RebindError(RuntimeError):
    """A stale producer header cannot be reconciled to the real CURRENT."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise RebindError(f"{role} must be a lowercase SHA-256")
    return value


def _file(value: Any, role: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise RebindError(f"{role} path is missing")
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise RebindError(f"{role} is not a regular non-symlink file: {path}")
    return path


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    if target.stat().st_size > MAX_JSON_BYTES:
        raise RebindError(f"{role} exceeds the JSON-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RebindError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise RebindError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise RebindError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _identity(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "current_case_index", "family_id", "manifest_case_id",
        "manifest_physical_case_id", "physical_case_id", "runtime_case_alias",
    )
    result = {field: value.get(field) for field in fields}
    if result["current_case_index"] != EXPECTED_CASE_INDEX:
        raise RebindError("case identity is not CURRENT case 78")
    if any(not isinstance(result[field], str) or not result[field] for field in fields[1:]):
        raise RebindError("case identity contains a missing string")
    return result


def _source_map(value: Mapping[str, Any], role: str) -> dict[str, str]:
    entries = value.get(role)
    if not isinstance(entries, list):
        raise RebindError(f"{role} is not a list")
    result: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            raise RebindError(f"{role} contains a malformed entry")
        name = item.get("role")
        if not isinstance(name, str) or not name:
            raise RebindError(f"{role} contains an entry without role")
        digest = _sha(item.get("sha256"), f"{role}.{name}")
        if name in result and result[name] != digest:
            raise RebindError(f"{role} repeats role with different SHA: {name}")
        result[name] = digest
    return result


def _binding_source_map(value: Mapping[str, Any], role: str = "source_files") -> dict[str, str]:
    entries = value.get(role)
    if not isinstance(entries, Mapping):
        raise RebindError(f"{role} is not a mapping")
    result: dict[str, str] = {}
    for name, digest in entries.items():
        result[str(name)] = _sha(digest, f"{role}.{name}")
    return result


def _diff(x: Any, y: Any, path: str = "") -> list[dict[str, Any]]:
    if type(x) is not type(y):
        return [{"path": path or "/", "kind": "type", "left": type(x).__name__, "right": type(y).__name__}]
    if isinstance(x, Mapping):
        result: list[dict[str, Any]] = []
        for key in sorted(set(x) | set(y)):
            child = f"{path}/{key}"
            if key not in x or key not in y:
                result.append({"path": child, "kind": "missing"})
            else:
                result.extend(_diff(x[key], y[key], child))
        return result
    if isinstance(x, list):
        if len(x) != len(y):
            return [{"path": path or "/", "kind": "length", "left": len(x), "right": len(y)}]
        result = []
        for index, (left, right) in enumerate(zip(x, y)):
            result.extend(_diff(left, right, f"{path}/{index}"))
        return result
    if x != y:
        return [{"path": path or "/", "kind": "value", "left": x, "right": y}]
    return []


def _identity_from_producer(value: Mapping[str, Any]) -> dict[str, Any]:
    identity = value.get("case_identity")
    if not isinstance(identity, Mapping):
        raise RebindError("typed-label producer case_identity is missing")
    return _identity(identity)


def _require_canonical(value: Mapping[str, Any], role: str) -> str:
    declared = _sha(value.get("sha256"), f"{role}.sha256")
    actual = canonical_sha(value)
    if declared != actual:
        raise RebindError(f"{role} canonical SHA differs")
    return actual


def build_rebind(*, current_catalog: Path | str, frozen_request: Path | str,
                 historical_proof: Path | str, producer_request: Path | str,
                 producer_report: Path | str, output: Path | str,
                 source_contract: Path | str | None = None,
                 historical_proof_request: Path | str | None = None) -> dict[str, Any]:
    current_path, current = _json(current_catalog, "CURRENT336 catalog")
    frozen_path, frozen = _json(frozen_request, "frozen V15 request")
    proof_path, proof = _json(historical_proof, "historical V10 proof")
    producer_path, producer = _json(producer_request, "V37 typed-label producer request")
    report_path, report = _json(producer_report, "typed-label producer report")
    contract_path = contract_value = None
    if source_contract is not None:
        contract_path, contract_value = _json(source_contract, "V38 source contract")
    proof_request_path = proof_request = None
    if historical_proof_request is not None:
        proof_request_path, proof_request = _json(historical_proof_request, "historical V10 proof request")

    if current.get("schema") != CURRENT_SCHEMA or not isinstance(current.get("cases"), list) or len(current["cases"]) != 336:
        raise RebindError("CURRENT336 schema/case count differs")
    current_sha = sha256_file(current_path)
    if current_sha != ACTUAL_CURRENT_SHA256:
        raise RebindError(f"actual CURRENT336 SHA differs: {current_sha}")
    if frozen.get("schema") != FROZEN_SCHEMA:
        raise RebindError("frozen request schema differs")
    if proof.get("schema") != PROOF_SCHEMA:
        raise RebindError("historical proof schema differs")
    _require_canonical(proof, "historical proof")
    if producer.get("schema") != PRODUCER_SCHEMA:
        raise RebindError("typed-label producer schema differs")
    _require_canonical(producer, "typed-label producer request")
    if report.get("schema") != REPORT_SCHEMA:
        raise RebindError("typed-label producer report schema differs")
    _require_canonical(report, "typed-label producer report")
    if contract_value is not None:
        if contract_value.get("schema") != SOURCE_CONTRACT_SCHEMA:
            raise RebindError("V38 source contract schema differs")
        _require_canonical(contract_value, "V38 source contract")
    if proof_request is not None:
        _require_canonical(proof_request, "historical V10 proof request")

    frozen_identity = _identity(frozen.get("case_identity", {}))
    producer_identity = _identity_from_producer(producer)
    if producer_identity != frozen_identity:
        raise RebindError("producer and frozen V15 case identities differ")
    proof_identity = _identity(proof.get("case_identity", {}))
    if proof_identity != frozen_identity:
        raise RebindError("historical proof and frozen V15 case identities differ")

    row = current["cases"][EXPECTED_CASE_INDEX]
    actual_identity = {
        "current_case_index": EXPECTED_CASE_INDEX,
        "family_id": row.get("family_id"),
        # CURRENT336 rows carry the manifest case token only in the
        # validated V15 request; the row's physical/runtime fields are the
        # explicit join evidence.  Do not invent a row-level manifest ID.
        "manifest_case_id": frozen_identity["manifest_case_id"],
        "manifest_physical_case_id": row.get("physical_case_id"),
        "physical_case_id": row.get("physical_case_id"),
        "runtime_case_alias": row.get("runtime_case_alias"),
    }
    if actual_identity != frozen_identity:
        raise RebindError("CURRENT case 78 identity differs from frozen V15")

    frozen_current = frozen.get("current_binding")
    if not isinstance(frozen_current, Mapping) or frozen_current.get("sha256") != current_sha:
        raise RebindError("frozen V15 current_binding is not the actual CURRENT SHA")
    frozen_sources = _source_map(frozen, "source_files")
    if frozen_sources.get("current_catalog") != current_sha:
        raise RebindError("frozen V15 source_files current_catalog is not actual CURRENT SHA")

    historical_binding = proof.get("source_binding")
    if not isinstance(historical_binding, Mapping):
        raise RebindError("historical proof source_binding is missing")
    historical_sha = _sha(historical_binding.get("current_catalog_sha256"), "historical current catalog SHA")
    historical_sources = _binding_source_map(historical_binding)
    if historical_sha != HISTORICAL_OVERLAY_SHA256 or historical_sources.get("current_catalog") != historical_sha:
        raise RebindError("historical proof does not contain the expected stale overlay SHA")
    common_source_roles = []
    for role, digest in sorted(historical_sources.items()):
        if role == "current_catalog":
            continue
        if role in frozen_sources:
            if frozen_sources[role] != digest:
                raise RebindError(f"historical and V15 source SHA differs for role {role}")
            common_source_roles.append(role)

    producer_v15 = producer.get("v15_request")
    if not isinstance(producer_v15, Mapping):
        raise RebindError("typed-label producer v15_request is missing")
    producer_v15_identity = _identity(producer_v15.get("case_identity", {}))
    if producer_v15_identity != frozen_identity:
        raise RebindError("producer embedded V15 identity differs")
    producer_current = producer_v15.get("current_binding")
    if not isinstance(producer_current, Mapping):
        raise RebindError("producer embedded V15 current_binding is missing")
    alias_path = _file(producer_current.get("path"), "producer current path overlay")
    alias_sha = _sha(producer_current.get("sha256"), "producer current path overlay SHA")
    if alias_sha != HISTORICAL_OVERLAY_SHA256 or sha256_file(alias_path) != alias_sha:
        raise RebindError("producer current path overlay does not have the historical stale SHA")
    alias_path_value, alias = _json(alias_path, "producer current path overlay")
    differences = _diff(current, alias)
    allowed_path = f"/cases/{EXPECTED_CASE_INDEX}/trajectory/path"
    if len(differences) != 1 or differences[0].get("path") != allowed_path:
        raise RebindError(f"producer current overlay changes more than the allowed trajectory path: {differences[:3]}")
    alias_diff = differences[0]
    if alias_diff.get("left") == alias_diff.get("right"):
        raise RebindError("producer current overlay path was not actually relocated")

    input_files = producer_v15.get("input_files")
    if not isinstance(input_files, list):
        raise RebindError("producer embedded V15 input_files are missing")
    current_copies = [item for item in input_files if isinstance(item, Mapping)
                      and isinstance(item.get("path"), str)
                      and "CURRENT336" in Path(item["path"]).name]
    if len(current_copies) != 1 or current_copies[0].get("sha256") != current_sha:
        raise RebindError("producer does not carry exactly one actual CURRENT336 content copy")
    producer_source_files = _source_map(producer_v15, "source_files")
    if producer_source_files.get("current_catalog") != alias_sha:
        raise RebindError("producer source_files current_catalog is not its declared overlay SHA")

    report_v16 = report.get("labels", {}).get("v16")
    proof_result = proof.get("source_result")
    if not isinstance(report_v16, Mapping) or not isinstance(proof_result, Mapping):
        raise RebindError("V16 result metadata is missing")
    result_sha = _sha(report_v16.get("sha256"), "producer V16 result SHA")
    if result_sha != EXPECTED_RESULT_SHA256 or proof_result.get("sha256") != result_sha:
        raise RebindError("producer and proof V16 result SHA differ")
    if report.get("typed_validation", {}).get("selected_particles") != 21114:
        raise RebindError("producer typed metadata selected-particle count differs")
    result_bytes = proof_result.get("bytes")
    if result_bytes != EXPECTED_RESULT_BYTES:
        raise RebindError("proof V16 result byte count differs")
    report_request = report.get("request")
    if not isinstance(report_request, Mapping) or report_request.get("sha256") != sha256_file(producer_path):
        raise RebindError("typed-label report does not bind the producer request bytes")

    if proof_request is not None:
        proof_request_binding = proof_request.get("expected", {}).get("source_binding", {})
        if proof_request_binding.get("current_catalog_sha256") != historical_sha:
            raise RebindError("historical V10 proof request does not preserve stale SHA")

    if contract_value is not None:
        contract_binding = contract_value.get("expected", {}).get("source_binding", {})
        if contract_binding.get("current_catalog_sha256") != historical_sha:
            raise RebindError("V38 source contract does not expose the stale SHA being rebound")

    alias_generator_sha = sha256_file(ALIAS_GENERATOR_V5)
    if alias_generator_sha != ALIAS_GENERATOR_V5_SHA256:
        raise RebindError("alias-generator source changed; require a new reviewed forward version")

    value: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_METADATA_ONLY_REBIND_ACTUAL_CURRENT_STALE_ALIAS_RECORDED",
        "metadata_only": True,
        "actual_current": {
            "path": str(current_path),
            "sha256": current_sha,
            "bytes": current_path.stat().st_size,
            "schema": current.get("schema"),
            "case_count": len(current["cases"]),
            "case_index": EXPECTED_CASE_INDEX,
            "case_row_canonical_sha256": hashlib.sha256(json.dumps(
                row, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                allow_nan=False, default=str).encode("utf-8")).hexdigest(),
        },
        "frozen_v15": {
            "path": str(frozen_path),
            "sha256": sha256_file(frozen_path),
            "current_binding_path": frozen_current.get("path"),
            "current_binding_sha256": current_sha,
            "source_files_current_catalog_sha256": frozen_sources["current_catalog"],
        },
        "stale_chain": {
            "historical_v10_proof": {
                "path": str(proof_path),
                "sha256": sha256_file(proof_path),
                "declared_current_catalog_sha256": historical_sha,
                "binding_status": historical_binding.get("binding_status"),
            },
            "historical_v10_proof_request": ({
                "path": str(proof_request_path),
                "sha256": sha256_file(proof_request_path),
                "declared_current_catalog_sha256": proof_request.get("expected", {}).get("source_binding", {}).get("current_catalog_sha256"),
            } if proof_request_path is not None and proof_request is not None else None),
            "v38_source_contract": ({
                "path": str(contract_path),
                "sha256": sha256_file(contract_path),
                "declared_current_catalog_sha256": contract_value.get("expected", {}).get("source_binding", {}).get("current_catalog_sha256"),
            } if contract_path is not None and contract_value is not None else None),
            "v37_typed_label_request": {
                "path": str(producer_path),
                "sha256": sha256_file(producer_path),
                "schema": producer.get("schema"),
                "embedded_v15_overlay_path": str(alias_path_value),
                "embedded_v15_overlay_sha256": alias_sha,
                "copied_current_input_sha256": current_copies[0].get("sha256"),
            },
            "typed_label_report": {
                "path": str(report_path),
                "sha256": sha256_file(report_path),
                "v16_result_sha256": result_sha,
                "v16_result_bytes": result_bytes,
            },
        },
        "overlay_origin": {
            "alias_path": str(alias_path),
            "alias_sha256": alias_sha,
            "alias_generator": {
                "path": str(ALIAS_GENERATOR_V5),
                "sha256": alias_generator_sha,
                "function": "_prepare_relocated_requests",
                "operation": "copy CURRENT JSON, replace cases[78].trajectory.path, hash overlay, then assign overlay SHA to current_binding",
            },
            "json_difference_count": 1,
            "json_difference": alias_diff,
            "only_path_overlay": True,
            "original_catalog_bytes_are_preserved_in_producer_input": True,
            "producer_current_binding_must_not_be_used_as_current_catalog": True,
        },
        "source_case_rebind": {
            "identity": frozen_identity,
            "current_row_identity": actual_identity,
            "identity_exact": True,
            "common_source_roles_exact_count": len(common_source_roles),
            "common_source_roles_excluding_overlay": common_source_roles,
            "historical_overlay_sha_is_not_current_file_sha": True,
            "current_catalog_content_sha256": current_sha,
            "embedded_current_source_catalog_sha256": current.get("source_catalog_sha256"),
            "embedded_catalog_is_not_current_file_sha": True,
        },
        "result_header_rebind": {
            "result_path": proof_result.get("path"),
            "result_sha256": result_sha,
            "result_bytes": result_bytes,
            "result_identity_preserved": True,
            "result_content_rehashed_by_this_sidecar": False,
            "label_array_equivalence": "NOT_PROVEN_BY_JSON_ONLY; existing parent result SHA is preserved",
            "source_case_and_small_source_equivalence": "PROVEN_BY_CURRENT_V15_PRODUCER_JOIN",
        },
        "consumer_binding": {
            "accepted_current_catalog_sha256": current_sha,
            "accepted_current_catalog_path": str(current_path),
            "historical_result_current_catalog_sha256": historical_sha,
            "historical_exact_current_claim": "REJECTED_STALE_OVERLAY_SHA",
            "requires_this_sidecar_before_current_bound_evaluation": True,
            "path_overlay_is_provenance_only": True,
            "original_path_fallback": "FORBIDDEN",
        },
        "credit_boundary": {
            "source_rebind": "DEVELOPMENT_METADATA_ONLY",
            "typed_label_content": "EXISTING_RESULT_SHA_PRESERVED; ARRAY_VALUES_NOT_REOPENED",
            "portable_cold_replay": "NOT_CLAIMED",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "hdf5_bi4_raw_read_during_build": False,
        },
    }
    value["sha256"] = canonical_sha(value)
    target = _write_new(output, value)
    return {
        "status": value["status"], "rebind": str(target), "sha256": value["sha256"],
        "actual_current_catalog_sha256": current_sha,
        "historical_overlay_sha256": historical_sha,
        "result_sha256": result_sha, "result_bytes": result_bytes,
        "case_index": EXPECTED_CASE_INDEX, "json_difference_count": 1,
        "hdf5_bi4_raw_read": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def validate_rebind(path: Path | str, *, current_catalog: Path | str | None = None,
                    frozen_request: Path | str | None = None,
                    historical_proof: Path | str | None = None) -> dict[str, Any]:
    rebind_path, value = _json(path, "CURRENT source rebind sidecar")
    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise RebindError("CURRENT source rebind schema/SHA differs")
    if value.get("status") != "PASS_METADATA_ONLY_REBIND_ACTUAL_CURRENT_STALE_ALIAS_RECORDED":
        raise RebindError("CURRENT source rebind status is not conservative")
    actual = value.get("actual_current", {})
    stale = value.get("stale_chain", {})
    consumer = value.get("consumer_binding", {})
    if actual.get("sha256") != ACTUAL_CURRENT_SHA256:
        raise RebindError("rebind sidecar does not bind actual CURRENT336")
    if consumer.get("accepted_current_catalog_sha256") != ACTUAL_CURRENT_SHA256:
        raise RebindError("consumer accepted SHA is not actual CURRENT336")
    if consumer.get("historical_result_current_catalog_sha256") != HISTORICAL_OVERLAY_SHA256:
        raise RebindError("rebind sidecar lost historical stale SHA")
    if stale.get("v37_typed_label_request", {}).get("embedded_v15_overlay_sha256") != HISTORICAL_OVERLAY_SHA256:
        raise RebindError("rebind sidecar does not record V37 stale overlay")
    if value.get("overlay_origin", {}).get("json_difference_count") != 1:
        raise RebindError("rebind sidecar does not prove one-path overlay")
    if value.get("result_header_rebind", {}).get("label_array_equivalence") != "NOT_PROVEN_BY_JSON_ONLY; existing parent result SHA is preserved":
        raise RebindError("rebind sidecar overclaims label-array equivalence")
    if current_catalog is not None and sha256_file(_file(current_catalog, "CURRENT validation input")) != ACTUAL_CURRENT_SHA256:
        raise RebindError("validation CURRENT input differs")
    if frozen_request is not None and sha256_file(_file(frozen_request, "V15 validation input")) != value["frozen_v15"]["sha256"]:
        raise RebindError("validation V15 input differs")
    if historical_proof is not None and sha256_file(_file(historical_proof, "proof validation input")) != stale["historical_v10_proof"]["sha256"]:
        raise RebindError("validation historical proof input differs")
    return {"path": str(rebind_path), "sha256": value["sha256"], "status": value["status"],
            "actual_current_catalog_sha256": actual["sha256"],
            "historical_overlay_sha256": consumer["historical_result_current_catalog_sha256"],
            "result_sha256": value["result_header_rebind"]["result_sha256"],
            "result_bytes": value["result_header_rebind"]["result_bytes"],
            "json_difference_count": value["overlay_origin"]["json_difference_count"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("current-catalog", "frozen-request", "historical-proof", "producer-request", "producer-report", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--source-contract", type=Path)
    build.add_argument("--historical-proof-request", type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("--rebind", type=Path, required=True)
    validate.add_argument("--current-catalog", type=Path)
    validate.add_argument("--frozen-request", type=Path)
    validate.add_argument("--historical-proof", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            value = build_rebind(
                current_catalog=args.current_catalog, frozen_request=args.frozen_request,
                historical_proof=args.historical_proof, producer_request=args.producer_request,
                producer_report=args.producer_report, output=args.output,
                source_contract=args.source_contract,
                historical_proof_request=args.historical_proof_request)
        else:
            value = validate_rebind(args.rebind, current_catalog=args.current_catalog,
                                    frozen_request=args.frozen_request,
                                    historical_proof=args.historical_proof)
    except (RebindError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"CURRENT source rebind: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
