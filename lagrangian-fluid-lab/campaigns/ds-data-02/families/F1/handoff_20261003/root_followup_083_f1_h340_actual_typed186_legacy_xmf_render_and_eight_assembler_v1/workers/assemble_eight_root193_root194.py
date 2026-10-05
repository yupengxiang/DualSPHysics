"""Assemble F1's eight already-qualified typed products into Root requests.

This worker is metadata-only.  It validates the immutable GenCase/native/frame-0
and typed receipt chain, verifies every non-scientific input hash, and adopts the
converter report's ``output_sha256`` as the producer hash for the trajectory.
It deliberately never opens, hashes, or imports an HDF5/BI4/CSV/VTK array.

By default output requests remain disabled.  Root may pass ``--enable`` together
with a JSON adoption receipt whose schema/status are accepted below; that is the
only mode that emits launch-enabled XMF/render request copies.  This script does
not invoke a runner, solver, converter, XMF exporter, or renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
INPUT_INDEX = PACKAGE / "metadata/eight-case-inputs.json"
RAW_SUFFIXES = {".h5", ".bi4", ".ibi4", ".csv", ".vtk", ".vtu"}
ADOPTION_SCHEMA = "ds02.f1.root-adoption.v1"
ACCEPTED_ADOPTION_STATUS = {"accepted", "approved", "adopted"}


class ContractError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON metadata: {path}") from exc


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ContractError(f"{label} is missing: {path}")


def require_sha(path: Path, expected: str, label: str) -> None:
    require_file(path, label)
    actual = sha256(path)
    if actual != expected:
        raise ContractError(f"{label} SHA differs: {actual} != {expected}")


def canonical_binding_sha(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def check_owner_chain(binding: dict[str, Any]) -> dict[str, Any]:
    owner_path = Path(binding["canonical_owner"])
    typed_owner_path = Path(binding["typed_owner"])
    owner = load_json(owner_path)
    typed_owner = load_json(typed_owner_path)
    if not isinstance(owner, dict) or not isinstance(typed_owner, dict):
        raise ContractError(f"owner metadata is not an object: {binding['case_id']}")
    require_sha(owner_path, binding["canonical_owner_sha256"], "canonical owner")
    require_sha(typed_owner_path, binding["typed_owner_sha256"], "typed owner")
    if owner.get("physical_condition_sha256") != binding["canonical_physical_condition_sha256"]:
        raise ContractError(f"canonical condition mismatch: {binding['case_id']}")
    if canonical_binding_sha(owner["physical_binding"]) != binding["canonical_physical_binding_sha256"]:
        raise ContractError(f"canonical physical_binding mismatch: {binding['case_id']}")
    if typed_owner.get("source_owner") != binding["canonical_owner"]:
        raise ContractError(f"typed owner does not point to canonical owner: {binding['case_id']}")
    if typed_owner.get("source_owner_sha256") != binding["canonical_owner_sha256"]:
        raise ContractError(f"typed owner source-owner SHA mismatch: {binding['case_id']}")
    if typed_owner.get("physical_condition_sha256") != binding["canonical_physical_condition_sha256"]:
        raise ContractError(f"typed owner canonical condition mismatch: {binding['case_id']}")
    return typed_owner


def check_actual_chain(binding: dict[str, Any]) -> dict[str, Any]:
    report_path = Path(binding["typed_conversion_report"])
    receipt_path = Path(binding["typed_execution_receipt"])
    report = load_json(report_path)
    receipt = load_json(receipt_path)
    require_sha(report_path, binding["typed_conversion_report_sha256"], "typed conversion report")
    require_sha(receipt_path, binding["typed_execution_receipt_sha256"], "typed execution receipt")
    if report.get("conversion_status") != "completed":
        raise ContractError(f"typed conversion is not completed: {binding['case_id']}")
    if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
        raise ContractError(f"typed receipt is not completed/0: {binding['case_id']}")
    if report.get("output_sha256") != binding["typed_output_sha256"]:
        raise ContractError(f"typed H5 producer SHA differs from report: {binding['case_id']}")
    if int(report.get("frames", -1)) != int(binding["expected_frames"]):
        raise ContractError(f"typed frame count differs: {binding['case_id']}")
    if int(report.get("particles", -1)) != int(binding["expected_particles"]):
        raise ContractError(f"typed particle count differs: {binding['case_id']}")
    if int(report.get("solver_dimension", {}).get("solver_dimension", -1)) != 3:
        raise ContractError(f"typed product is not 3-D: {binding['case_id']}")
    scopes = report.get("hash_scopes", {})
    legacy = scopes.get("physical_condition_sha256")
    if legacy != binding["legacy_h5_physical_condition_sha256"]:
        raise ContractError(f"legacy report scope differs: {binding['case_id']}")
    if legacy == binding["canonical_physical_condition_sha256"]:
        raise ContractError(f"legacy/canonical scope collapsed: {binding['case_id']}")
    if scopes.get("physical_condition", {}).get("schema") != "legacy-owner-scope.v0":
        raise ContractError(f"unexpected legacy scope schema: {binding['case_id']}")
    for key, path_key, hash_key in (
        ("generated_xml", "generated_xml", "generated_xml_sha256"),
        ("gencase_receipt", "actual_gencase_receipt", "actual_gencase_receipt_sha256"),
    ):
        entry = report.get("source_provenance", {}).get(key, {})
        if entry.get("path") != binding[path_key] or entry.get("sha256") != binding[hash_key]:
            raise ContractError(f"typed source provenance differs for {key}: {binding['case_id']}")

    metadata_files = (
        ("source_definition", "source_definition_sha256"),
        ("generated_xml", "generated_xml_sha256"),
        ("generated_def", "generated_def_sha256"),
        ("actual_gencase_receipt", "actual_gencase_receipt_sha256"),
        ("actual_gencase_report", "actual_gencase_report_sha256"),
        ("actual_native_receipt", "actual_native_receipt_sha256"),
        ("actual_root181_frame0_vx_closure", "actual_root181_frame0_vx_closure_sha256"),
        ("actual_root181_frame0_vx_receipt", "actual_root181_frame0_vx_receipt_sha256"),
        ("actual_root181_frame0_vx_report", "actual_root181_frame0_vx_report_sha256"),
    )
    for path_key, hash_key in metadata_files:
        require_sha(Path(binding[path_key]), binding[hash_key], path_key)
    gencase_receipt = load_json(Path(binding["actual_gencase_receipt"]))
    if (gencase_receipt.get("status"), gencase_receipt.get("returncode")) != ("completed", 0):
        raise ContractError(f"GenCase receipt is not completed/0: {binding['case_id']}")
    gencase_report = load_json(Path(binding["actual_gencase_report"]))
    if int(gencase_report.get("actual_total_particles", -1)) != int(binding["expected_particles"]):
        raise ContractError(f"GenCase total particle metadata differs: {binding['case_id']}")
    fluid_count = int(gencase_report.get("generated_xml_particle_counts", {}).get("fluid", -1))
    if fluid_count <= 0:
        raise ContractError(f"GenCase fluid metadata is missing: {binding['case_id']}")
    typed_fluid_count = sum(
        int(block.get("count", 0)) for block in report.get("typed_identity", {}).get("blocks", [])
        if block.get("tag") == "fluid" and int(block.get("type", -1)) == 3
    )
    if typed_fluid_count != fluid_count:
        raise ContractError(f"GenCase/typed fluid metadata differs: {binding['case_id']}")
    native_receipt = load_json(Path(binding["actual_native_receipt"]))
    if (native_receipt.get("status"), native_receipt.get("returncode")) != ("completed", 0):
        raise ContractError(f"native receipt is not completed/0: {binding['case_id']}")
    frame0 = load_json(Path(binding["actual_root181_frame0_vx_report"]))
    frame0_cases = frame0.get("cases", []) if isinstance(frame0, dict) else []
    if not frame0_cases or not all(bool(item.get("passed")) for item in frame0_cases if isinstance(item, dict)):
        # Root181 records the native saved-frame result inside its case list;
        # this is evidence from the solver-saved frame, never a GenCase claim.
        raise ContractError(f"Root181 frame-0 audit is not passing: {binding['case_id']}")
    return report


def check_request_inputs(request: dict[str, Any], binding: dict[str, Any]) -> None:
    files = set(request.get("input_files", []))
    hashes = set(request.get("input_sha256", {}))
    if files != hashes:
        raise ContractError(f"request input file/hash closure differs: {binding['case_id']}")
    for path_text, expected in request.get("input_sha256", {}).items():
        path = Path(path_text)
        if path.suffix.lower() in RAW_SUFFIXES:
            if path.suffix.lower() == ".h5" and expected != binding["typed_output_sha256"]:
                raise ContractError(f"H5 producer SHA is not report output SHA: {binding['case_id']}")
            if len(expected) != 64:
                raise ContractError(f"raw input hash is not SHA-256: {path}")
            continue
        require_sha(path, expected, "request input")
    future = request.get("future_outputs", {})
    if any(value is not None for value in future.values()):
        raise ContractError(f"future output hash is fabricated: {binding['case_id']}")


def load_adoption(path: Path) -> dict[str, Any]:
    adoption = load_json(path)
    if not isinstance(adoption, dict):
        raise ContractError("Root adoption receipt must be a JSON object")
    if adoption.get("schema") != ADOPTION_SCHEMA:
        raise ContractError(f"Root adoption schema must be {ADOPTION_SCHEMA}")
    if adoption.get("status") not in ACCEPTED_ADOPTION_STATUS:
        raise ContractError(f"Root adoption status must be one of {sorted(ACCEPTED_ADOPTION_STATUS)}")
    if adoption.get("owner") != "root":
        raise ContractError("Root adoption receipt owner must be root")
    return adoption


def write_request(source: Path, destination: Path, enabled: bool, adoption_path: Path | None, adoption: dict[str, Any] | None, binding: dict[str, Any]) -> None:
    request = load_json(source)
    if not isinstance(request, dict):
        raise ContractError(f"request is not an object: {source}")
    check_request_inputs(request, binding)
    if request.get("case_id") != binding["case_id"]:
        raise ContractError(f"request case mismatch: {source}")
    out = dict(request)
    out["schema"] = "ds02.runner-request.v2"
    out["assembler_schema"] = "ds02.f1.fresh083.eight-case-adoption-assembler.v1"
    # Root's strict runtime reserves the attempt root for its receipt.  Both
    # read-only products therefore write below a dedicated child directory.
    is_render = ".root194-" in source.name
    out["cpu_task_kind"] = "audit"
    command = list(out.get("command", []))
    if "--output-dir" not in command:
        raise ContractError(f"request lacks --output-dir: {source}")
    output_index = command.index("--output-dir") + 1
    command[output_index] = "{attempt_root}/render" if is_render else "{attempt_root}/xdmf"
    out["command"] = command
    if is_render:
        future_files = []
        future_hashes = {}
        for old_path in out.get("future_input_files", []):
            old = Path(old_path)
            if old.parent.name == "xdmf":
                new_path = old
            else:
                new_path = old.parent / "xdmf" / old.name
            future_files.append(str(new_path))
            future_hashes[str(new_path)] = None
        out["future_input_files"] = future_files
        out["future_input_sha256"] = future_hashes
    out["assembler_source"] = str(Path(__file__).resolve())
    out["assembler_source_sha256"] = sha256(Path(__file__).resolve())
    out["source_disabled_request"] = str(source)
    out["source_disabled_request_sha256"] = sha256(source)
    if adoption_path is not None:
        if str(adoption_path) not in out["input_files"]:
            out["input_files"] = list(out["input_files"]) + [str(adoption_path)]
        out["input_sha256"] = dict(out["input_sha256"])
        out["input_sha256"][str(adoption_path)] = sha256(adoption_path)
        out["root_adoption_receipt"] = str(adoption_path)
        out["root_adoption_receipt_sha256"] = sha256(adoption_path)
        if set(out["input_files"]) != set(out["input_sha256"]):
            raise ContractError(f"adoption input closure differs: {binding['case_id']}")
    out["launch"] = bool(enabled)
    out["launch_allowed"] = bool(enabled)
    out["execution_allowed"] = bool(enabled)
    out["status"] = "root_adopted_enabled" if enabled else "source_only_disabled"
    out["root_review_required"] = not enabled
    out["future_outputs"] = {key: None for key in out.get("future_outputs", {})}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--enable", action="store_true", help="emit enabled request copies after a Root adoption receipt")
    parser.add_argument("--root-adoption-receipt", type=Path, help=f"JSON receipt with schema {ADOPTION_SCHEMA}")
    parser.add_argument("--include-render", action="store_true", help="also emit Root194 request copies")
    args = parser.parse_args()
    if args.enable and args.root_adoption_receipt is None:
        raise SystemExit("--enable requires --root-adoption-receipt")
    if not args.enable and args.root_adoption_receipt is not None:
        raise SystemExit("--root-adoption-receipt requires --enable")
    adoption = None
    adoption_path = None
    if args.enable:
        adoption_path = args.root_adoption_receipt.resolve()
        require_file(adoption_path, "Root adoption receipt")
        adoption = load_adoption(adoption_path)

    index = load_json(INPUT_INDEX)
    if index.get("schema") != "ds02.f1.fresh083.eight-case-inputs.v1":
        raise SystemExit("unexpected eight-case input index schema")
    records = index.get("cases", [])
    if len(records) != 8:
        raise SystemExit(f"expected eight input records, got {len(records)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[str] = []
    for record in records:
        binding_path = Path(record["legacy_aware_binding"])
        binding = load_json(binding_path)
        if not isinstance(binding, dict):
            raise SystemExit(f"binding is not an object: {binding_path}")
        if binding.get("case_id") != record["case_id"]:
            raise SystemExit(f"binding case mismatch: {binding_path}")
        if sha256(binding_path) != record["legacy_aware_binding_sha256"]:
            raise SystemExit(f"binding SHA differs: {binding_path}")
        typed_owner = check_owner_chain(binding)
        report = check_actual_chain(binding)
        if report.get("output_sha256") != record["typed_h5_producer_sha256"]:
            raise SystemExit(f"producer SHA differs from input index: {binding['case_id']}")
        if typed_owner.get("physical_condition_sha256") != record["canonical_physical_condition_sha256"]:
            raise SystemExit(f"canonical SHA differs from input index: {binding['case_id']}")
        xmf_source = Path(record["root193_request"])
        write_request(xmf_source, args.output_dir / "root193" / xmf_source.name, args.enable, adoption_path, adoption, binding)
        output_paths.append(str(args.output_dir / "root193" / xmf_source.name))
        if args.include_render:
            render_source = Path(record["root194_request"])
            write_request(render_source, args.output_dir / "root194" / render_source.name, args.enable, adoption_path, adoption, binding)
            output_paths.append(str(args.output_dir / "root194" / render_source.name))

    summary = {
        "schema": "ds02.f1.fresh083.eight-case-assembly-report.v1",
        "case_count": 8,
        "request_count": len(output_paths),
        "enabled": bool(args.enable),
        "root_adoption_receipt": str(adoption_path) if adoption_path else None,
        "root_adoption_status": adoption.get("status") if adoption else None,
        "h5_arrays_read": False,
        "bi4_arrays_read": False,
        "csv_arrays_read": False,
        "jobs_started": False,
        "h5_hash_source": "actual conversion-report output_sha256; no H5 read or rehash",
        "requests": output_paths,
    }
    (args.output_dir / "assembly-report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
