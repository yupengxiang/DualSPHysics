#!/usr/bin/env python3
"""Static/source-only validator for the fresh087 Root299 downstream handoff."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
ROOT299 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f1_actualGenQA298_eight_full_native_299")
CASES = [
    "F1_STAGE1_DUAL_H240_DP020",
    "F1_STAGE1_DUAL_H240_DP020_VX010",
    "F1_STAGE1_DUAL_H280_DP020",
    "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010",
    "F1_STAGE1_ECC_H140_DP010",
    "F1_STAGE1_ECC_H160_DP010",
    "F1_STAGE1_ECC_H180_DP010",
]


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"expected object: {path}")
    return value


def sha(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}:
        raise AssertionError(f"scientific array hash attempted: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    checks: list[str] = []

    for path in package.rglob("*"):
        if path.is_file():
            require(path.suffix.lower() not in {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz", ".vtk"}, f"array artifact copied into source package: {path}")
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    checks.append("package contains no scientific array artifacts; Python source parses")

    for case in CASES:
        aq = load(package / "actual-gencase-qa-bindings" / f"{case}.json")
        require(aq["status"] == "completed/0" and aq["passed"] is True, f"actual Root298 QA not pass: {case}")
        qa_receipt = Path(aq["actual_receipt"]); qa_report = Path(aq["actual_report"]); qa_request = Path(aq["actual_request"])
        require(qa_receipt.is_file() and qa_report.is_file() and qa_request.is_file(), f"Root298 paths missing: {case}")
        qr = load(qa_receipt); qp = load(qa_report)
        require((qr.get("status"), qr.get("returncode")) == ("completed", 0), f"Root298 receipt status: {case}")
        require(sha(qa_receipt) == aq["actual_receipt_sha256"], f"Root298 receipt SHA: {case}")
        require(sha(qa_report) == aq["actual_report_sha256"], f"Root298 report SHA: {case}")
        require(sha(qa_request) == qr.get("request_sha256"), f"Root298 request closure: {case}")
        require(qp.get("cases", [{}])[0].get("passed") is True, f"Root298 report predicate: {case}")
        checks.append(f"{case}: Root298 completed/0 and pass")

        nb = load(package / "actual-native-bindings" / f"{case}.json")
        nr_path = Path(nb["actual_request"]); receipt_path = Path(nb["actual_receipt"])
        require(nr_path.is_file() and receipt_path.is_file(), f"Root299 provenance paths missing: {case}")
        nr = load(nr_path); receipt = load(receipt_path)
        require((receipt.get("status"), receipt.get("returncode")) == ("completed", 0), f"Root299 receipt status: {case}")
        require(sha(nr_path) == receipt.get("request_sha256") == nb["actual_request_sha256"], f"Root299 request closure: {case}")
        require(sha(receipt_path) == nb["actual_receipt_sha256"], f"Root299 receipt SHA: {case}")
        require(nr.get("attempt_id") == nb["actual_attempt_id"], f"Root299 attempt identity: {case}")
        requested_command = [str(x) for x in nr.get("command", [])]
        actual_command = [str(x) for x in receipt.get("command", [])]
        require(requested_command[-2:] == actual_command[-2:], f"Root299 solver option closure: {case}")
        command = " ".join(actual_command)
        require("-mdbc" not in command and "-forcing" not in command, f"Root299 command mutation: {case}")
        expected = nr.get("expected_output", {})
        data_root = Path(nb["actual_native_data_root"])
        require(data_root.is_dir(), f"Root299 data root missing: {case}")
        observed = len(list(data_root.glob("Part_*.bi4")))
        require(observed == int(expected["frame_count"]) == int(nb["observed_frame_file_count"]), f"Root299 frame inventory: {case}")
        require(nb["actual_native_particle_counts"] is None, f"native counts falsely claimed from receipt: {case}")
        checks.append(f"{case}: Root299 completed/0, command closed, {observed} frame filenames observed")

        fb = load(package / "native-frame0-qa-bindings" / f"{case}.json")
        fr_path = package / "requests" / f"{case}.native-frame0-qa.request.json"; fr = load(fr_path)
        require(fr.get("disabled") is True and fr.get("execution_allowed") is False and fr.get("launch_allowed") is False, f"frame0 request not disabled: {case}")
        require(fr.get("native_solver_attempt_id") == nb["actual_attempt_id"], f"frame0 Root299 dependency: {case}")
        require(fr.get("native_solver_receipt_sha256") == nb["actual_receipt_sha256"], f"frame0 receipt hash: {case}")
        require(fb.get("native_frame0_bi4_sha256") is None and fb.get("prospective_output_not_generated") is True, f"frame0 future hash claim: {case}")
        require(fr.get("future_input_sha256") is None, f"frame0 future input hash prefilled: {case}")

        tr_path = package / "typed-conversion/requests" / f"{case}.full-native-typed-nvme.request.json"; tr = load(tr_path)
        require(tr.get("cpu_task_kind") == "conversion", f"typed kind: {case}")
        require(tr.get("disabled") is True and tr.get("execution_allowed") is False and tr.get("launch_allowed") is False, f"typed request not disabled: {case}")
        require(nb["actual_attempt_id"] in tr.get("depends_on_attempts", []), f"typed native dependency: {case}")
        require(fr.get("attempt_id") in tr.get("depends_on_attempts", []), f"typed frame0 dependency: {case}")
        for key in ("trajectory_h5_sha256", "conversion_report_sha256", "execution_receipt_sha256", "typed_partvtk_sha256"):
            require(tr.get("future_outputs", {}).get(key) is None, f"typed future hash prefilled {key}: {case}")
        checks.append(f"{case}: disabled frame0 and typed requests are acyclic")

        xr_path = package / "xmf/requests" / f"{case}.root193-xmf.request.json"; xr = load(xr_path)
        require(xr.get("disabled") is True and xr.get("execution_allowed") is False and xr.get("launch_allowed") is False, f"XMF request not disabled: {case}")
        require(xr.get("future_input_sha256") is None, f"XMF future hash prefilled: {case}")
        rr_path = package / "render/requests" / f"{case}.root194-render.request.json"; rr = load(rr_path)
        require(rr.get("disabled") is True and rr.get("execution_allowed") is False and rr.get("launch_allowed") is False, f"render request not disabled: {case}")
        require(rr.get("future_input_sha256") is None, f"render future hash prefilled: {case}")
        checks.append(f"{case}: disabled XMF and Root023 render requests retain null future hashes")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema": "ds02.f1.fresh087.root299-static-validation.v1", "passed": True, "checks": checks, "arrays_read": False, "arrays_hashed": False, "jobs_started": False, "shared_state_modified": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "checks": len(checks), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
