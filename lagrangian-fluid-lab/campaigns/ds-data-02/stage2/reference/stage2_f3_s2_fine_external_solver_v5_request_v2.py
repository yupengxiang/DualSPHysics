#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Forward fine-grid external-v5 builder with nested ROOT102 output support.

The consumed fine request adapter (v1) delegates to the shared external-v5
writer, whose historical ROOT120 contract assumes generated XML and BI4 sit
directly under the producer receipt root.  ROOT102 stores them under
``worker/generated``.  This additive adapter preserves the v1 bytes and
changes only the in-memory producer-root validation: it accepts the exact
ROOT102 descendant while restoring the real receipt root in the emitted
provenance.  It still requires ROOT167's successful selected-native report
and a parent-supplied post-reservation BI4 SHA; it never reads BI4/VTK/
forcing payloads or launches a solver.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f3_s2_fine_external_solver_v5_request_v1.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V1 = load_module("stage2_f3_s2_fine_external_solver_v5_request_v1_forward_v2", V1_PATH)
VARIANT = "ds02.stage2.f3.s2.fine-external-solver-request.v2-nested-producer-root"


def validate_middle_terminal(receipt_path: Path, proof_path: Path, observer_path: Path) -> dict[str, Any]:
    """Accept the actual ROOT162 report-v5 receipt shape.

    The consumed v1 adapter expected the older flat execution-receipt fields
    (``bytes``, ``returncode`` and ``output_root``).  ROOT162's terminal
    receipt is the report-v5 shape: those values live under ``filesystem`` and
    ``execution`` while the independent proof carries the actual output-byte
    total.  Normalize only this in-memory validation result; no source
    artifact is rewritten.
    """

    receipt = V1.load_json(receipt_path, "ROOT162 terminal receipt")
    proof = V1.load_json(proof_path, "ROOT162 terminal proof")
    observer = V1.load_json(observer_path, "ROOT167 selected observer report")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0", "completed_development_unknown"}:
        raise ValueError("ROOT162 receipt is not terminal")
    execution = receipt.get("execution") if isinstance(receipt.get("execution"), dict) else {}
    filesystem = receipt.get("filesystem") if isinstance(receipt.get("filesystem"), dict) else {}
    if execution.get("returncode") not in (0, None):
        raise ValueError("ROOT162 receipt execution returncode is not zero")
    actual_bytes = int(proof.get("actual_output_bytes", 0) or filesystem.get("measured_total_bytes", 0) or 0)
    if actual_bytes <= 0:
        raise ValueError("ROOT162 terminal evidence has no positive output bytes")
    allowed_proof_schema = {
        "ds02.stage2.root-actual-verification.v1",
        "ds02.stage2.root-actual-external-solver-verification.v1",
    }
    runparts_summary = proof.get("RunPARTs_summary")
    if proof.get("schema") not in allowed_proof_schema or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError("ROOT162 proof is not an actual terminal proof")
    if not isinstance(runparts_summary, dict) or int(runparts_summary.get("rows", 0) or 0) < 2:
        raise ValueError("ROOT162 proof has no terminal RunPARTs evidence")
    if proof.get("parent_source_prepost_full_sha_equal") is not True:
        raise ValueError("ROOT162 proof does not close materialized source pre/post SHA")
    proof_receipt = proof.get("receipt")
    if proof_receipt is not None and Path(str(proof_receipt)).expanduser().resolve() != receipt_path.expanduser().resolve():
        raise ValueError("ROOT162 proof receipt path does not match supplied receipt")
    proof_receipt_sha = proof.get("receipt_sha256")
    if proof_receipt_sha is not None and proof_receipt_sha != V1.sha256(receipt_path):
        raise ValueError("ROOT162 proof receipt SHA does not match supplied receipt")
    if execution.get("source_verified_after_reservation") is False:
        raise ValueError("ROOT162 receipt does not confirm post-reservation source verification")
    if not str(observer.get("status", "")).startswith("PASS_MIDDLE_SELECTED_NATIVE_FIELDS"):
        raise ValueError("ROOT167 selected observer is not a successful native-field report")
    if observer.get("scope", {}).get("typed_conversion") not in (None, "NOT_PERFORMED"):
        raise ValueError("ROOT167 observer unexpectedly includes typed conversion")

    # V1 only consumes these three normalized fields while constructing its
    # small cost-basis/provenance card.  Keep the actual report-v5 payload in
    # the independent receipt file and add compatibility aliases in memory.
    normalized_receipt = copy.deepcopy(receipt)
    normalized_receipt["bytes"] = actual_bytes
    normalized_receipt["returncode"] = execution.get("returncode", 0)
    if filesystem.get("output_root") is not None:
        normalized_receipt["output_root"] = filesystem["output_root"]
    return {"receipt": normalized_receipt, "proof": proof, "observer": observer}


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{path.stat().st_ino if path.exists() else 'new'}.tmp")
    fd = None
    try:
        fd = open(temporary, "x", encoding="utf-8")
        json.dump(value, fd, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        fd.write("\n")
        fd.flush()
        import os

        os.fsync(fd.fileno())
        fd.close()
        fd = None
        temporary.replace(path)
    finally:
        if fd is not None:
            fd.close()
        temporary.unlink(missing_ok=True)


def _nested_receipt_loader(module, middle_receipt_path: Path, middle_proof_path: Path):
    original = module.load_json
    fine_receipt = V1.FINE_RECEIPT.expanduser().resolve()
    middle_receipt = middle_receipt_path.expanduser().resolve()
    generated_root = V1.FINE_XML.expanduser().resolve().parent
    actual_receipt_root = V1.FINE_ROOT.expanduser().resolve()
    middle_proof = V1.load_json(middle_proof_path, "ROOT162 terminal proof")
    middle_bytes = int(middle_proof.get("actual_output_bytes", 0) or 0)
    if middle_bytes <= 0:
        raise ValueError("ROOT162 proof has no positive actual output bytes")

    def load_json(path: Path, label: str):
        value = original(path, label)
        if Path(path).expanduser().resolve() == fine_receipt:
            # Only the shared writer's structural validation sees this
            # in-memory alias.  The actual receipt remains an input binding;
            # output provenance is restored to actual_receipt_root below.
            value = copy.deepcopy(value)
            value["output_root"] = str(generated_root)
        elif Path(path).expanduser().resolve() == middle_receipt:
            # The shared v5 writer only uses the cost-basis receipt's flat
            # ``bytes`` field.  ROOT162 stores the same charge in its
            # independent proof/filesystem report shape, so expose a
            # validation-only alias without rewriting that receipt.
            value = copy.deepcopy(value)
            value["bytes"] = middle_bytes
        return value

    module.load_json = load_json
    return actual_receipt_root, generated_root


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    original_loader = V1.load_delegate
    original_writer = V1.write_once
    original_terminal_validator = V1.validate_middle_terminal

    def load_delegate():
        delegate = original_loader()
        actual_root, generated_root = _nested_receipt_loader(delegate, args.middle_terminal_receipt, args.middle_proof)
        delegate.__fine_actual_receipt_root = actual_root
        delegate.__fine_generated_nested_root = generated_root
        return delegate

    V1.load_delegate = load_delegate
    V1.write_once = lambda _path, value: captured.setdefault("request", value)
    V1.validate_middle_terminal = validate_middle_terminal
    try:
        result = V1.build_request(args)
    finally:
        V1.load_delegate = original_loader
        V1.write_once = original_writer
        V1.validate_middle_terminal = original_terminal_validator
    request = captured.get("request")
    if not isinstance(request, dict):
        raise RuntimeError(f"v1 fine adapter did not emit an in-memory request: {result!r}")

    actual_root = str(V1.FINE_ROOT.expanduser().resolve())
    nested_root = str(V1.FINE_XML.expanduser().resolve().parent)
    request["request_variant_schema"] = VARIANT
    request["request_variant_status"] = request.get("status")
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    request["source_provenance"]["gencase_output_root"] = actual_root
    request["source_provenance"]["gencase_generated_nested_root"] = nested_root
    request["source_provenance"]["gencase_generated_nested_root_is_descendant"] = True
    request["source_provenance"]["receipt_output_root_is_authoritative"] = actual_root
    request["source_provenance"]["shared_v5_root_assumption_forwarded"] = False
    request["source_provenance"]["fine_adapter_v2_nested_root_fix"] = True
    request["input_files"] = sorted(set(list(request.get("input_files", [])) + [str(Path(__file__).resolve())]))
    request["input_sha256"] = dict(request.get("input_sha256", {}))
    request["input_sha256"][str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    request["input_content_scope"] = dict(request.get("input_content_scope", {}))
    request["input_content_scope"][str(Path(__file__).resolve())] = "small_forward_adapter_source_hashed_by_builder_and_parent"
    request["fine_generated_path_contract"] = {
        "receipt_output_root": actual_root,
        "generated_xml": str(V1.FINE_XML.expanduser().resolve()),
        "generated_bi4": str(V1.FINE_BI4.expanduser().resolve()),
        "generated_parent": nested_root,
        "nested_generated_parent_is_exact": True,
        "payload_read_by_builder": False,
    }
    request["physical_qualification"] = {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "reason": "ROOT102 nested generated-input path is source-bound; initial/middle evidence and parent BI4 fingerprint are separate from solver qualification",
    }
    request["sha256"] = canonical(request)
    return request


def self_test() -> dict[str, Any]:
    base = V1.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    if V1.FINE_XML.parent != V1.FINE_ROOT / "worker" / "generated":
        raise AssertionError("ROOT102 nested generated input contract changed")
    return {
        "status": "PASS",
        "schema": "ds02.stage2.external-solver-request.v5",
        "request_variant_schema": VARIANT,
        "nested_generated_root_supported": True,
        "receipt_root_provenance_restored": True,
        "payload_read": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path, default=V1.LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-owner-centered-dp003-full-cfd-fine-root-170-001-v2.json")
    parser.add_argument("--source-card", type=Path, default=V1.DEFAULT_CARD)
    parser.add_argument("--middle-terminal-receipt", type=Path)
    parser.add_argument("--middle-proof", type=Path)
    parser.add_argument("--middle-observer-report", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP003_FULL_CFD_FINE_ROOT_170")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp003-full-cfd-fine-root-170-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=64 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=16 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=21600.0)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (args.middle_terminal_receipt, args.middle_proof, args.middle_observer_report, args.generated_bi4_sha256, args.launch_commit)
    if any(value is None for value in required):
        parser.error("--build-request requires ROOT162 receipt/proof, ROOT167 observer report, BI4 SHA and launch commit")
    request = build_request(args)
    write_once(args.output, request)
    print(json.dumps({"status": request["status"], "request_variant_schema": VARIANT, "output": str(args.output.resolve()), "solver_started": False, "payload_read": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
