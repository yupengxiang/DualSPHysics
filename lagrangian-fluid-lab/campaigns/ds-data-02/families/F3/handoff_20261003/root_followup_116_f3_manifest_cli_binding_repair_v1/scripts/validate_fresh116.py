#!/usr/bin/env python3
"""Static validator for the F3 fresh116 manifest binding repair package."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
WORKER = HERE / "workers/nvme_render_successor.py"
REQUIRED = [
    HERE / "README.md",
    HERE / "metadata/fresh114-logging-contract.json",
    HERE / "metadata/fresh116-manifest-cli-repair.json",
    HERE / "metadata/fresh112-source-provenance.json",
    HERE / "metadata/root920-root934-comparison.json",
    HERE / "scripts/compare_root920_root934.py",
    HERE / "scripts/validate_fresh116.py",
    HERE / "tests/test_nvme_render_successor.py",
    WORKER,
]
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw", ".bin"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_worker():
    spec = importlib.util.spec_from_file_location("fresh114_worker", WORKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import fresh114 worker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    missing = [str(path.relative_to(HERE)) for path in REQUIRED if not path.is_file()]
    package_payloads = [path for path in HERE.rglob("*") if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES]
    worker = load_worker()
    comparison = json.loads((HERE / "metadata/root920-root934-comparison.json").read_text(encoding="utf-8"))
    contract = json.loads((HERE / "metadata/fresh114-logging-contract.json").read_text(encoding="utf-8"))
    repair = json.loads((HERE / "metadata/fresh116-manifest-cli-repair.json").read_text(encoding="utf-8"))
    worker_text = WORKER.read_text(encoding="utf-8")
    checks = {
        "required_files_present": not missing,
        "worker_schema": worker.SCHEMA == "ds02.stage1.f3.fresh114.nvme-render-successor.v1",
        "rejection_schema_in_worker": "fresh114.render-rejection.v1" in WORKER.read_text(encoding="utf-8"),
        "bounded_tail_constant": worker.MAX_DIAGNOSTIC_TAIL_BYTES == 16 * 1024,
        "diagnostic_capture_present": all(name in worker_text for name in ("_bounded_text_tail", "_renderer_diagnostics", "actual_argv", "renderer_pgid")),
        "manifest_path_separated_from_parsed_object": all(name in worker_text for name in ("manifest_path = _absolute", "manifest = _load_json(manifest_path", '"manifest": str(manifest_path)')),
        "manifest_cli_regression_metadata": repair["repair"]["returned_cli_value"] == "str(manifest_path)",
        "root945_failure_preserved": repair["source_failures_preserved"] == ["fresh112", "fresh114", "Root934", "Root945"],
        "source_package_has_no_scientific_payload_files": not package_payloads,
        "comparison_payload_boundary_closed": comparison["science_payloads_opened_or_hashed"] is False,
        "comparison_pv_environment_equal": comparison["pv_environment_comparison"]["exact_equal"] is True,
        "comparison_does_not_infer_root_cause": comparison["argv_and_wrapper_comparison"]["no_root_cause_inferred"] is True,
        "root937_import_scope_limited": "paraview.vtk.util.numpy_support" == comparison["root937_no_h5_import_diagnostic"]["renderer_specific_helper_not_tested"],
        "success_contract_preserved": contract["success_contract"]["publication_logic_changed"] is False,
        "no_jobs": contract["no_jobs_started"] is True,
    }
    report = {
        "schema": "ds02.stage1.f3.fresh116.validator-report.v1",
        "package": str(HERE),
        "checks": checks,
        "missing": missing,
        "forbidden_payload_files": [str(path) for path in package_payloads],
        "worker_sha256": sha256(WORKER),
        "tests": {"command": "python3 -m unittest discover -s tests -p 'test_*.py' -q", "expected": 10},
        "source_only": True,
    }
    (HERE / "metadata/fresh116-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not missing and not package_payloads and all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
