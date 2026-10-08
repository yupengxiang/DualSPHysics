#!/usr/bin/env python3
"""Counterexamples for the consumed F2 fine endpoint semantics sidecar."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f2_fine_endpoint_semantics_v1.py"
SPEC = importlib.util.spec_from_file_location("fine_endpoint_semantics_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import endpoint semantics module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_rejected(callback, label: str) -> None:
    try:
        callback()
    except MODULE.EndpointSemanticsError:
        return
    raise AssertionError(f"manufactured {label} was accepted")


def main() -> int:
    source = MODULE.validate_v4_sources()
    runparts = MODULE.parse_runparts(MODULE.RUNPARTS)
    runout = MODULE.parse_run_out(MODULE.RUN_OUT)
    assert runparts["row_count"] == 801
    assert runparts["steps_sum"] == 91714
    assert runout["simulation_steps"] == 91713
    endpoint = source["endpoint"]
    assert endpoint["last_integration_step"]["requested_end_inside_bound"] is True
    assert endpoint["saved_transition_bracket_s"][0] <= endpoint["requested_endpoint"]["requested_end_s"] <= endpoint["saved_transition_bracket_s"][1]
    semantics = MODULE.source_semantics()
    assert semantics["interpretation"]["runtime_cause_claim"] == "UNKNOWN; this sidecar does not infer why the observed counters differ by one"
    assert semantics["interpretation"]["GPU_initialization_observation"].startswith("GPU source sets PartNstep=-1")

    with tempfile.TemporaryDirectory(prefix="ds02-fine-endpoint-semantics-tests-") as directory:
        root = Path(directory)
        prepared = MODULE.make_manifest(root / "prepared")
        manifest = json.loads(Path(prepared["manifest"]).read_text(encoding="utf-8"))
        request = json.loads(Path(prepared["request"]).read_text(encoding="utf-8"))
        manifest_path = Path(prepared["manifest"]).resolve()
        assert str(manifest_path) not in manifest["input_sha256"]
        assert request["input_sha256"][str(manifest_path)] == prepared["manifest_sha256"]
        output = root / "endpoint-sidecar.json"
        result = MODULE.run(manifest_path, output)
        assert result["runparts_steps_sum"] == 91714
        assert result["run_out_simulation_steps"] == 91713
        sidecar = json.loads(output.read_text(encoding="utf-8"))
        assert sidecar["step_counter_observation"]["causal_explanation"] == "UNKNOWN"
        assert sidecar["endpoint_semantics"]["last_integration_step_relation"] == "UNKNOWN"
        assert sidecar["read_policy"]["h5_opened"] is False

        malformed_run_out = root / "malformed-Run.out"
        malformed_run_out.write_text("Steps of simulation..............: 91,713\n", encoding="utf-8")
        expect_rejected(lambda: MODULE.parse_run_out(malformed_run_out), "Run.out without PART table")
        malformed_runparts = root / "malformed-RunPARTs.csv"
        malformed_runparts.write_text(
            "Part;TimeStep [s];Steps;DtMin [s];DtMax [s]\n"
            "0;0;0;0;0\n"
            "2;0.1;1;0.1;0.1\n", encoding="utf-8"
        )
        expect_rejected(lambda: MODULE.parse_runparts(malformed_runparts), "RunPARTs part sequence gap")

    print("stage2 F2 fine endpoint semantic counters/bounds/source counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
