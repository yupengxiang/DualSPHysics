#!/usr/bin/env python3
"""Validate the fresh085 source package without opening scientific arrays.

This checker only reads package JSON/XML/text and verifies immutable metadata
bindings.  It deliberately does not hash or open the Root246 CSV, BI4, H5, or
any native array.  The Root-supplied CSV SHA is checked as an opaque value.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main() -> None:
    binding = load("diagnostic-binding.json")
    request = load("diagnostic-request.json")
    disabled = load("downstream-disabled.json")
    pipeline = load("pipeline-contract.json")

    require(binding["schema"] == "ds02.f5.c082r1.initial-csv-lattice-diagnostic-binding.fresh085.v1", "binding schema")
    require(request["schema"] == "ds02.runner-request.v2", "request schema")
    require(request["launch_allowed"] is False and request["execution_allowed"] is False, "diagnostic request enabled")
    require(request["source_only"] is True and request["arrays_allowed"] is False, "source policy changed")
    require(request["cpu_task_kind"] == "audit" and request["kind"] == "cpu", "unsupported CPU task kind")
    require(request["full16_authorized"] is False and request["full801_authorized"] is False, "downstream authorization changed")
    require(disabled["all_downstream_disabled"] is True, "downstream gate opened")
    require(all(stage.get("execution_allowed") is False for stage in pipeline["stages"]), "pipeline stage enabled")

    counts = binding["actual_gencase"]["actual_counts"]
    require(counts["total_particles"] == 194427, "actual total changed")
    require(counts["fixed_particles"] + counts["moving_particles"] + counts["floating_particles"] + counts["fluid_particles"] == counts["total_particles"], "producer counts do not sum")
    require(counts["fluid_particles"] == 31658, "actual producer fluid count changed")
    require(binding["actual_root246"]["producer_fluid_particles"] == 31658, "Root246 fluid count changed")
    require(binding["actual_root246"]["overall_qa_pass"] is False, "Root246 failure was erased")
    require(binding["actual_root246"]["official_csv_sha256"] == "a1165d9d1d6645f22774eb57c6be0a236b1fbba90f46577cc2ab3fa51d2abfb8", "Root-supplied CSV SHA changed")
    require(request["input_sha256"].get(binding["actual_root246"]["official_csv"]) == binding["actual_root246"]["official_csv_sha256"], "CSV opaque hash is not bound")
    require("expected_fluid_particles" not in request and binding["lattice_comparison_contract"]["expected_fluid_is_not_substituted"] is True, "expected fluid became a contract")
    require(binding["lattice_comparison_contract"]["clip_only_candidate_count_band"] == [40695, 40740], "clip band changed")
    require(binding["execution_policy"]["arrays_allowed"] is False and binding["execution_policy"]["solver_allowed"] is False, "binding execution policy changed")

    worker = ROOT / "workers" / "diagnose_r1_initial_csv_lattice.py"
    tree = ast.parse(worker.read_text(encoding="utf-8"), filename=str(worker))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported.update(node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module)
    require(imported <= {"__future__", "argparse", "csv", "hashlib", "json", "math", "statistics", "struct", "collections", "decimal", "pathlib"}, f"non-stdlib worker import: {sorted(imported)}")
    source = worker.read_text(encoding="utf-8")
    require("subprocess" not in imported and "Popen" not in source, "worker invokes a producer")
    require("raw coordinates are never modified" in source, "worker coordinate immutability guard missing")
    require("float32_ulp" in source and "missing_by_xy_strict_nonzero" in source and "field_quality" in source, "diagnostic coverage incomplete")

    print(json.dumps({"status": "fresh085_source_contract_pass", "package": str(ROOT), "csv_hash_bound_opaque": True, "arrays_opened": False, "jobs_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
