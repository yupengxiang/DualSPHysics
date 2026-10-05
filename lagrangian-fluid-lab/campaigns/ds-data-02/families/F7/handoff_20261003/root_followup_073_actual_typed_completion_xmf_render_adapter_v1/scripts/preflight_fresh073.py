#!/usr/bin/env python3
"""Static fresh073 contract review; no scientific payload access or jobs."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any


CASES = [
    f"F7_OBSTACLE_QUINTIC_B08_A{number:03d}"
    for number in (31, 32, 33, 34, 36, 37, 38, 39, 41, 42, 43, 44, 46, 47, 48, 49)
]
RAW_SUFFIXES = (".bi4", ".csv", ".h5", ".hdf5", ".dat", ".ibi4")
VENV_PYTHON = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
)
XMF_WORKER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py"
)
RENDERER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
)


class PreflightError(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"JSON root is not an object: {path}")
    return value


def sha(path: Path) -> str:
    if path.name.lower().endswith(RAW_SUFFIXES):
        raise PreflightError(f"scientific payload hash requested: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    if not path.is_file():
        raise PreflightError(f"missing {label}: {path}")
    return path


def literal_subscripts(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
            continue
        values.setdefault(node.value.id, set()).add(node.slice.value)
    return values


def check_worker_ast(contract: dict[str, Any]) -> dict[str, Any]:
    require(XMF_WORKER, "XMF worker")
    require(RENDERER, "Root023 renderer")
    xmf = literal_subscripts(XMF_WORKER)
    renderer = literal_subscripts(RENDERER)
    required_xmf = contract["xmf_worker_contract"]
    expected_binding = set(required_xmf["required_binding_keys"])
    expected_receipt = set(required_xmf["required_receipt_keys"])
    expected_report = set(required_xmf["required_report_keys"])
    if not expected_binding <= xmf.get("binding", set()):
        raise PreflightError(f"XMF binding AST contract drift: {sorted(xmf.get('binding', set()))}")
    if not expected_receipt <= xmf.get("receipt", set()):
        raise PreflightError(f"XMF receipt AST contract drift: {sorted(xmf.get('receipt', set()))}")
    if not expected_report <= xmf.get("report", set()):
        raise PreflightError(f"XMF report AST contract drift: {sorted(xmf.get('report', set()))}")
    required_manifest = set(contract["renderer_contract"]["required_manifest_keys"])
    if not required_manifest <= renderer.get("manifest", set()):
        raise PreflightError(f"Root023 manifest AST contract drift: {sorted(renderer.get('manifest', set()))}")
    return {
        "xmf_worker_sha256": sha(XMF_WORKER),
        "renderer_sha256": sha(RENDERER),
        "xmf_binding_subscripts": sorted(xmf.get("binding", set())),
        "xmf_receipt_subscripts": sorted(xmf.get("receipt", set())),
        "xmf_report_subscripts": sorted(xmf.get("report", set())),
        "renderer_manifest_subscripts": sorted(renderer.get("manifest", set())),
        "ast_contract_passed": True,
    }


def check_request(path: Path, kind: str, source_package: Path) -> dict[str, Any]:
    request = load(path)
    if request.get("disabled") is not True or request.get("launch") is not False:
        raise PreflightError(f"{kind} template is not disabled: {path}")
    if request.get("execution_allowed") is not False or request.get("launch_allowed") is not False:
        raise PreflightError(f"{kind} template launch guard drift: {path}")
    if request.get("future_hashes_null") is not True:
        raise PreflightError(f"{kind} template future hash policy drift: {path}")
    if request.get("expected_frames") != 601 or request.get("expected_native_frames") != 601:
        raise PreflightError(f"{kind} template frame contract drift: {path}")
    if request.get("expected_counts") != {
        "total": 70179,
        "fixed": 27495,
        "moving": 1984,
        "fluid": 40700,
        "floating": 0,
        "dimension": 3,
    }:
        raise PreflightError(f"{kind} template count contract drift: {path}")
    files = [str(item) for item in request.get("input_files", [])]
    hashes = request.get("input_sha256", {})
    if len(files) != len(set(files)) or set(files) != set(hashes):
        raise PreflightError(f"{kind} input closure is not exact: {path}")
    for raw in files:
        item = Path(raw)
        if not item.is_absolute() or not item.is_file():
            raise PreflightError(f"{kind} missing input: {item}")
        if item.name.lower().endswith(RAW_SUFFIXES):
            raise PreflightError(f"fresh072 template registers scientific payload: {item}")
        if sha(item) != hashes[raw]:
            raise PreflightError(f"{kind} input hash drift: {item}")
    if kind == "xmf":
        if request.get("actual_sidecar_output_subdirectory") != "xdmf":
            raise PreflightError(f"XMF sidecar contract drift: {path}")
        shape = request.get("xmf_shape_contract", {})
        if shape.get("implementation") != "outshape = shape[1:]":
            raise PreflightError(f"XMF vector implementation drift: {path}")
        if shape.get("dynamic_vector_dimensions") != "70179 3" or shape.get("dynamic_scalar_dimensions") != "70179":
            raise PreflightError(f"XMF dimension contract drift: {path}")
        if "/xdmf" not in json.dumps(request.get("command", [])):
            raise PreflightError(f"XMF output child directory missing: {path}")
    if kind == "render":
        if request.get("actual_sidecar_output_subdirectory") != "render":
            raise PreflightError(f"render sidecar contract drift: {path}")
        renderer_contract = request.get("renderer_contract", {})
        if renderer_contract.get("fixed_camera_bounds_forbidden") is not True:
            raise PreflightError(f"Root023 fixed-camera guard drift: {path}")
        if renderer_contract.get("expected_contact_pages") != 26:
            raise PreflightError(f"Root023 contact-page contract drift: {path}")
        if "/render" not in json.dumps(request.get("future_outputs", {})):
            raise PreflightError(f"render output child directory missing: {path}")
    return {"path": str(path), "kind": kind, "input_count": len(files), "disabled": True}


def check_native_bindings(source_package: Path) -> list[dict[str, Any]]:
    rows = []
    for case_id in CASES:
        path = source_package / "bindings" / f"{case_id}.full601-xmf-binding.json"
        binding = load(require(path, "fresh072 XMF binding"))
        receipt_path = require(Path(binding["native_receipt"]), "Root313 native receipt")
        receipt = load(receipt_path)
        if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
            raise PreflightError(f"Root313 native receipt is not completed/0: {receipt_path}")
        declared = binding.get("native_receipt_sha256")
        actual = sha(receipt_path)
        if not isinstance(declared, str) or declared.lower() != actual:
            raise PreflightError(f"fresh072 native receipt digest drift: {receipt_path}")
        rows.append({"case_id": case_id, "native_receipt": str(receipt_path), "native_receipt_sha256": actual})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-package", type=Path, required=True)
    args = parser.parse_args()
    source_package = args.source_package.resolve()
    contract_path = Path(__file__).resolve().parents[1] / "metadata" / "downstream-worker-contract.json"
    contract = load(require(contract_path, "fresh073 contract"))
    if contract.get("schema") != "ds02.f7.fresh073.actual-typed-downstream-contract.v1":
        raise PreflightError("fresh073 contract schema drift")
    if not VENV_PYTHON.is_file():
        raise PreflightError(f"integration venv is missing: {VENV_PYTHON}")
    manifest = load(require(source_package / "metadata" / "manifest.json", "fresh072 manifest"))
    if manifest.get("case_count") != 16 or manifest.get("arrays_read") is not False:
        raise PreflightError("fresh072 source evidence flags are not source-only")
    request_rows = []
    for case_id in CASES:
        request_rows.append(check_request(source_package / "requests" / "xmf" / f"{case_id}.full601-normal-xmf-072.disabled-request.json", "xmf", source_package))
        request_rows.append(check_request(source_package / "requests" / "render" / f"{case_id}.full601-native023-render-072.disabled-request.json", "render", source_package))
    native_rows = check_native_bindings(source_package)
    ast_report = check_worker_ast(contract)
    report = {
        "schema": "ds02.f7.fresh073.source-validation-report.v1",
        "scope_id": "root_followup_073_actual_typed_completion_xmf_render_adapter_v1",
        "source_package": str(source_package),
        "case_count": 16,
        "request_count": len(request_rows),
        "requests": request_rows,
        "native_receipt_checks": native_rows,
        "worker_ast": ast_report,
        "integration_python": str(VENV_PYTHON),
        "arrays_read": False,
        "h5_read": False,
        "jobs_started": False,
        "shared_state_written": False,
        "future_output_hashes_null": True,
        "all_passed": True,
        "source_notes": [
            "fresh072 originals remain immutable; fresh073 adds native receipt closure in generated actual-bound output",
            "H5 output_sha256 is accepted only from a completed producer conversion report",
            "XMF and Root023 output hashes remain null until Root runs the actual workers",
        ],
    }
    report_path = Path(__file__).resolve().parents[1] / "metadata" / "source-validation-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as exc:
        raise SystemExit(f"fresh073 preflight failed: {exc}") from exc
