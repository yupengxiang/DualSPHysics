#!/usr/bin/env python3
"""Build explicit F2-only provenance aliases for the frozen converter bridge.

The shared converter currently accepts a DS-DATA-02 ``*.generator.v1`` owner
metadata schema.  The V4 commensurate owner metadata is intentionally
``*.commensurate-fallback.v1`` and its bytes are frozen by the qualification
receipts.  This adapter creates a derived metadata/receipt pair that keeps
every physical field and source hash unchanged while recording the schema
compatibility alias.  It never reruns GenCase and never edits a consumed
receipt or source file.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[4]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
SCOPE_ROOT = FAMILY_ROOT / "commensurate_cellcenter_v4"


class AdapterError(RuntimeError):
    """Raised when a compatibility alias would lose source provenance."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise AdapterError(f"{label} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdapterError(f"{label} must be an object: {path}")
    return value


def binding(path: Path) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise AdapterError(f"source is missing: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def _replace_path(value: str, source: Path, target: Path) -> tuple[str, bool]:
    """Replace one exact absolute input binding and report whether it matched."""
    if Path(value).expanduser().resolve() == source.resolve():
        return str(target.resolve()), True
    return value, False


def _replace_request_inputs(request: Mapping[str, Any], replacements: Mapping[Path, Path]) -> tuple[dict[str, Any], bool]:
    adapted = dict(request)
    values = request.get("input_files")
    if not isinstance(values, list):
        raise AdapterError("execution request has no input_files list")
    changed = False
    inputs: list[str] = []
    for value in values:
        text = str(value)
        for source, target in replacements.items():
            text, matched = _replace_path(text, source, target)
            changed = changed or matched
        inputs.append(text)
    adapted["input_files"] = inputs
    return adapted, changed


def _adapt_input_hashes(value: Any, replacements: Mapping[Path, Path]) -> dict[str, str]:
    """Copy runner hashes while adding hashes for derived paths.

    The original map is retained separately by the caller.  The derived map
    is only a provenance convenience; this file is never presented as a
    runner-produced execution receipt.
    """
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for raw_path, digest in value.items():
        path = Path(str(raw_path)).expanduser().resolve()
        target = replacements.get(path)
        result[str(target.resolve() if target else path)] = str(digest)
    for target in replacements.values():
        if target.is_file():
            result[str(target.resolve())] = sha256(target)
    return result


def _metadata_path(request: Mapping[str, Any]) -> Path:
    paths = [Path(str(value)).resolve() for value in request.get("input_files", []) if str(value).endswith(".metadata.json")]
    if len(paths) != 1:
        raise AdapterError(f"expected one frozen owner metadata input for {request.get('case_id')}")
    return paths[0]


def _write_case(request_path: Path, output_dir: Path) -> dict[str, Any]:
    request = load_json(request_path, "qualification request")
    case_id = str(request.get("case_id", ""))
    if request.get("family_id") != "F2" or not case_id.startswith("F2_COMM4_"):
        raise AdapterError(f"not a V4 F2 qualification request: {request_path}")
    artifacts = request.get("gencase_artifacts")
    if not isinstance(artifacts, Mapping):
        raise AdapterError(f"qualification request has no GenCase artifacts: {case_id}")
    source_metadata = _metadata_path(request)
    source_metadata_obj = load_json(source_metadata, "frozen owner metadata")
    source_schema = str(source_metadata_obj.get("schema", ""))
    if not source_schema.endswith("commensurate-fallback.v1"):
        raise AdapterError(f"unexpected V4 owner schema for {case_id}: {source_schema}")
    source_gencase = Path(str(artifacts.get("receipt", {}).get("path", ""))).resolve()
    source_gencase_obj = load_json(source_gencase, "frozen GenCase receipt")
    if source_gencase_obj.get("status") != "completed" or source_gencase_obj.get("returncode") != 0:
        raise AdapterError(f"GenCase receipt is not completed: {source_gencase}")
    source_request = source_gencase_obj.get("request")
    if not isinstance(source_request, Mapping) or source_request.get("case_id") != case_id:
        raise AdapterError(f"GenCase receipt case binding mismatch: {source_gencase}")
    raw_output_root = Path(str(request.get("raw_output_root", ""))).resolve()
    attempt_id = str(request.get("attempt_id", ""))
    solver_candidates = [
        raw_output_root / case_id / attempt_id / "execution-receipt.json",
        raw_output_root / attempt_id / "execution-receipt.json",
    ]
    source_solver = next((path for path in solver_candidates if path.is_file()), solver_candidates[0])
    source_solver_obj = load_json(source_solver, "completed solver receipt")
    if source_solver_obj.get("schema") != "ds02.execution-receipt.v1" or source_solver_obj.get("status") != "completed" or source_solver_obj.get("returncode") != 0:
        raise AdapterError(f"solver receipt is not completed: {source_solver}")
    solver_request = source_solver_obj.get("request")
    if not isinstance(solver_request, Mapping) or solver_request.get("case_id") != case_id:
        raise AdapterError(f"solver receipt case binding mismatch: {source_solver}")
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / f"{case_id}.generator-compat-v2.metadata.json"
    receipt_path = output_dir / f"{case_id}.gencase-receipt.compat-v2.json"
    solver_path = output_dir / f"{case_id}.solver-receipt.compat-v2.json"
    if metadata_path.exists() or receipt_path.exists() or solver_path.exists():
        raise AdapterError(f"refusing to overwrite compatibility alias: {case_id}")
    adapted_metadata = dict(source_metadata_obj)
    adapted_metadata["schema"] = "ds-data-02.f2.generator.v1"
    adapted_metadata["compatibility_adapter"] = {
        "schema": "ds-data-02.f2.commensurate-converter-compat.v1",
        "source_schema": source_schema,
        "source_owner_metadata": binding(source_metadata),
        "reason": "converter schema gate accepts generator.v1; all geometry, control, population, and source hashes remain unchanged",
        "derived_only": True,
        "no_gencase_rerun": True,
        "no_physical_field_change": True,
    }
    metadata_path.write_text(json.dumps(adapted_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    adapted_request, replaced = _replace_request_inputs(source_request, {source_metadata: metadata_path})
    if not replaced:
        raise AdapterError(f"frozen GenCase receipt did not bind owner metadata: {source_gencase}")
    adapted_request["request_note"] = str(adapted_request.get("request_note", "")) + " Derived F2 converter compatibility receipt; original GenCase execution receipt and owner metadata are bound below; no solver rerun."
    adapted_request["compatibility_adapter"] = {
        "schema": "ds-data-02.f2.commensurate-converter-compat.v1",
        "source_gencase_receipt": binding(source_gencase),
        "source_owner_metadata": binding(source_metadata),
        "adapted_owner_metadata": binding(metadata_path),
        "derived_only": True,
        "no_gencase_rerun": True,
    }
    adapted_receipt = dict(source_gencase_obj)
    adapted_receipt["source_original_request_sha256"] = source_gencase_obj.get("request_sha256")
    adapted_receipt["request"] = adapted_request
    adapted_receipt["source_original_gencase_receipt"] = binding(source_gencase)
    adapted_receipt["source_original_owner_metadata"] = binding(source_metadata)
    adapted_receipt["compatibility_adapter"] = adapted_request["compatibility_adapter"]
    # Preserve the original runner maps verbatim and expose the derived map
    # separately.  The compatibility receipt is a provenance input to the
    # converter, never a replacement for the consumed execution receipt.
    adapted_receipt["source_original_input_hashes_at_launch"] = adapted_receipt.get("input_hashes_at_launch")
    adapted_receipt["source_original_input_hashes_after_run"] = adapted_receipt.get("input_hashes_after_run")
    adapted_receipt["input_hashes_at_launch"] = _adapt_input_hashes(
        adapted_receipt.get("input_hashes_at_launch"), {source_metadata: metadata_path}
    )
    adapted_receipt["input_hashes_after_run"] = _adapt_input_hashes(
        adapted_receipt.get("input_hashes_after_run"), {source_metadata: metadata_path}
    )
    receipt_path.write_text(json.dumps(adapted_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    solver_replacements = {source_gencase: receipt_path, source_metadata: metadata_path}
    adapted_solver_request, solver_replaced = _replace_request_inputs(solver_request, solver_replacements)
    if not solver_replaced:
        raise AdapterError(f"frozen solver receipt did not bind the source GenCase receipt: {source_solver}")
    adapted_solver_request["gencase_receipt"] = str(receipt_path.resolve())
    adapted_solver_request["gencase_receipt_sha256"] = sha256(receipt_path)
    adapted_solver_artifacts = dict(adapted_solver_request.get("gencase_artifacts", {}))
    if isinstance(adapted_solver_artifacts.get("receipt"), Mapping):
        adapted_solver_artifacts["receipt"] = dict(adapted_solver_artifacts["receipt"])
        adapted_solver_artifacts["receipt"]["path"] = str(receipt_path.resolve())
        adapted_solver_artifacts["receipt"]["sha256"] = sha256(receipt_path)
    adapted_solver_request["gencase_artifacts"] = adapted_solver_artifacts
    adapted_solver = dict(source_solver_obj)
    adapted_solver["source_original_request_sha256"] = source_solver_obj.get("request_sha256")
    adapted_solver["source_original_solver_receipt"] = binding(source_solver)
    adapted_solver["source_original_gencase_receipt"] = binding(source_gencase)
    adapted_solver["source_original_owner_metadata"] = binding(source_metadata)
    adapted_solver["compatibility_adapter"] = adapted_request["compatibility_adapter"]
    adapted_solver["request"] = adapted_solver_request
    adapted_solver["input_hashes_at_launch"] = _adapt_input_hashes(
        source_solver_obj.get("input_hashes_at_launch"), solver_replacements
    )
    adapted_solver["input_hashes_after_run"] = _adapt_input_hashes(
        source_solver_obj.get("input_hashes_after_run"), solver_replacements
    )
    solver_path.write_text(json.dumps(adapted_solver, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "case_id": case_id,
        "source_owner_metadata": binding(source_metadata),
        "adapted_owner_metadata": binding(metadata_path),
        "source_gencase_receipt": binding(source_gencase),
        "adapted_gencase_receipt": binding(receipt_path),
        "source_solver_receipt": binding(source_solver),
        "adapted_solver_receipt": binding(solver_path),
        "gencase_artifacts": {
            key: dict(value) for key, value in artifacts.items() if isinstance(value, Mapping)
        },
        "derived_only": True,
        "no_gencase_rerun": True,
    }


def build_aliases(*, request_dir: Path, output_dir: Path, manifest_path: Path) -> dict[str, Any]:
    requests = sorted(request_dir.glob("*_qualification_request.json"))
    if len(requests) != 6:
        raise AdapterError(f"expected six frozen qualification requests, found {len(requests)}")
    cases = [_write_case(path.resolve(), output_dir.resolve()) for path in requests]
    manifest = {
        "schema": "ds-data-02.f2.commensurate-converter-compat-manifest.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "family_id": "F2",
        "scope_id": "F2_SCOPE_COMMENSURATE_CELLCENTER_V4",
        "status": "derived_provenance_aliases_ready",
        "qualification_claim": "none",
        "production_claim": "none",
        "source_bytes_unchanged": True,
        "no_gencase_rerun": True,
        "cases": cases,
    }
    manifest_path = manifest_path.resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        raise AdapterError(f"refusing to overwrite compatibility manifest: {manifest_path}")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-dir", type=Path, default=SCOPE_ROOT / "requests")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_aliases(request_dir=args.request_dir.resolve(), output_dir=args.output_dir.resolve(), manifest_path=args.manifest.resolve())
    except (AdapterError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"f2_commensurate_conversion_adapter: {error}")
        return 2
    print(json.dumps({"status": manifest["status"], "manifest": str(args.manifest.resolve()), "cases": len(manifest["cases"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
