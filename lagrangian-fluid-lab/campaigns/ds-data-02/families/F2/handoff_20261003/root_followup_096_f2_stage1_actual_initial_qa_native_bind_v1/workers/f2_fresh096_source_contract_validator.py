#!/usr/bin/env python3
"""Validate fresh096 metadata contracts without opening scientific arrays."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".vtk", ".csv", ".h5", ".hdf5", ".gif"}:
        raise AssertionError(f"array/artifact hashing forbidden: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"object expected: {path}")
    return value


def validate(manifest_path: Path) -> dict[str, Any]:
    manifest = load(manifest_path)
    package = manifest_path.parent
    assert manifest.get("execution_allowed") is False
    assert manifest.get("launch_allowed") is False
    rows = manifest.get("cases")
    assert isinstance(rows, list) and len(rows) == 5
    qa_count = solver_count = 0
    for row in rows:
        for key in ("binding", "owner", "root270_request", "root270_receipt", "prepared_input_report", "actual_xml", "actual_bi4", "actual_qa_request", "solver_request"):
            path = Path(row[key]["path"])
            assert path.is_file(), path
        receipt = load(Path(row["root270_receipt"]["path"]))
        report = load(Path(row["prepared_input_report"]["path"]))
        assert receipt["status"] == "completed" and receipt["returncode"] == 0
        assert receipt["solver_dimension_from_gencase"] == 3
        counts = report["generated_xml_particle_counts"]
        assert sum(int(v) for v in counts.values()) == report["actual_total_particles"] == receipt["total_particles"]
        assert int(counts["fluid"]) == receipt["fluid_particles"]
        assert row["actual_xml"]["sha256"] == report["xml_sha256"]
        assert row["actual_bi4"]["sha256"] == report["bi4_sha256"]
        binding = load(Path(row["binding"]["path"]))
        owner = load(Path(row["owner"]["path"]))
        assert binding["claims"]["typed"] is False
        assert owner["typed_scope_provenance"]["initial_qa_report_sha256"] is None
        assert owner["actual_evidence"]["initial_qa"] is None
        for req_key in ("actual_qa_request", "solver_request"):
            request = load(Path(row[req_key]["path"]))
            assert request["disabled"] is True
            assert request["launch"] is False and request["launch_allowed"] is False and request["execution_allowed"] is False
            assert request["source_only"] is True and request["launch_owner"] == "root"
            assert Path(request["owner_provenance"]).is_file()
            known_bi4_sha = request.get("actual_gencase_output", {}).get("bi4_sha256") or request.get("generated_bi4_sha256")
            for raw_path, expected in request["input_sha256"].items():
                path = Path(raw_path)
                assert path.is_file(), path
                if path.suffix.lower() == ".bi4":
                    assert expected == known_bi4_sha
                else:
                    assert sha256(path) == expected, path
            assert request["gencase_receipt_sha256"] == sha256(Path(request["gencase_receipt"]))
            if request["cpu_task_kind"] == "audit":
                qa_count += 1
                assert request["output_contract"]["actual_initial_qa_report_sha256"] is None
            elif request["cpu_task_kind"] == "solver":
                solver_count += 1
                assert request["initial_qa_report_sha256"] is None
                assert request["expected_output"]["native_output_hash"] is None
            else:
                raise AssertionError(request["cpu_task_kind"])
    for source in (package / "build_fresh096.py", package / "workers/f2_stage1_initial_qa_worker_v2.py"):
        ast.parse(source.read_text(encoding="utf-8"))
    assert qa_count == solver_count == 5
    return {"status": "pass", "cases": 5, "qa_requests": qa_count, "solver_requests": solver_count, "arrays_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "F2_STAGE1_FRESH096_ACTUAL_GENCASERUN_QA_NATIVE_MANIFEST.json")
    args = parser.parse_args()
    print(json.dumps(validate(args.manifest.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
