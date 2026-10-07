#!/usr/bin/env python3
"""Counterexamples for the bounded F2-S1 coarse per-MK study."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f2_s1_coarse_grid_permk_v1.py"
SPEC = importlib.util.spec_from_file_location("coarse_grid_permk_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import coarse grid per-MK module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REQUEST_DIR = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/requests/f2-s1-coarse-grid-permk-v1"


def expect_rejected(callback, label: str) -> None:
    try:
        callback()
    except MODULE.ProbeError:
        return
    raise AssertionError(f"manufactured {label} was accepted")


def generated_xml(motion_name: str, dp: str = "0.0125", mass: str = "0.001") -> str:
    return f"""<?xml version="1.0"?>
<case>
  <casedef>
    <geometry><definition dp="{dp}" /></geometry>
    <motion><objreal ref="0"><mvrotfile id="1"><file name="{motion_name}" /></mvrotfile></objreal></motion>
  </casedef>
  <execution>
    <particles np="21114">
      <fluid mkfluid="0" mk="1" begin="0" count="7038" />
      <fluid mkfluid="1" mk="2" begin="7038" count="7038" />
      <fluid mkfluid="2" mk="3" begin="14076" count="7038" />
    </particles>
    <constants><massfluid value="{mass}" /></constants>
  </execution>
</case>
"""


def main() -> int:
    manifest = MODULE.build_manifest()
    assert manifest["study_scope"]["candidate_count"] == 3
    assert manifest["study_scope"]["candidate_dp_m"] == [0.0125, 0.0126, 0.0127]
    assert all(item["spacing_above_dp010_fraction"] >= 0.10 for item in manifest["candidates"])
    assert all(item["semantic_changes"] == [
        "casedef/geometry/definition/@dp",
        "casedef/motion/**/mvrotfile/file/@name",
    ] for item in manifest["candidates"])
    baseline = MODULE.validate_source_baseline()
    assert baseline["generated_xml"]["initial_fluid_sample_mass_kg"] == 21.114
    assert set(baseline["generated_xml"]["by_mkfluid"]) == {"0", "1", "2"}

    request_paths = sorted(REQUEST_DIR.glob("f2_*.json"))
    assert len(request_paths) == 3
    for path in request_paths:
        loaded_path, request, candidate = MODULE.load_request(path)
        bound = MODULE.validate_request_sources(loaded_path, request, candidate)
        assert request["cpu_threads"] == 1
        assert request["omp_threads"] == 1
        assert bound["dp_m"] in (0.0125, 0.0126, 0.0127)
        assert request["scope"]["particle_mass_rescale"] is False
        assert request["scope"]["threshold_widening"] is False

    with tempfile.TemporaryDirectory(prefix="ds02-coarse-grid-permk-v1-tests-") as directory:
        root = Path(directory)
        candidate = MODULE.CANDIDATE_SPECS[0]
        altered_def = root / "altered_Def.xml"
        altered_def.write_text(Path(candidate["definition"]).read_text(encoding="utf-8").replace('size x="0.325"', 'size x="0.326"', 1), encoding="utf-8")
        altered_spec = copy.deepcopy(candidate)
        altered_spec["definition"] = altered_def
        expect_rejected(lambda: MODULE.validate_candidate_spec(altered_spec), "geometry mutation")

        request_path = request_paths[0]
        loaded_path, request, manifest_candidate = MODULE.load_request(request_path)
        expected = MODULE.validate_request_sources(loaded_path, request, manifest_candidate)
        output_root = root / "attempt"
        output_root.mkdir()
        generated = output_root / "generated.xml"
        generated.write_text(generated_xml(MODULE.motion_file_names(Path(expected["definition"]["path"]))[0]), encoding="utf-8")
        receipt = {
            "schema": "ds02.execution-receipt.v1",
            "status": "completed",
            "returncode": 0,
            "request_sha256": MODULE.sha256(loaded_path),
            "request": {key: request[key] for key in ("family_id", "case_id", "attempt_id", "physical_case_id")},
            "input_hashes_at_launch": request["input_hashes"],
            "input_hashes_after_run": request["input_hashes"],
            "command": [
                str(MODULE.GENCASE),
                str(Path(expected["definition"]["path"]).with_suffix("")),
                str(output_root / "generated"),
                "-save:all",
            ],
            "output_root": str(output_root),
            "fluid_particles": 21114,
            "total_particles": 21114,
        }
        receipt_path = root / "execution-receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        sidecar = root / "audit.json"
        result = MODULE.audit(loaded_path, receipt_path, sidecar)
        assert result["status"] == "COMPLETED_GENCASE_PER_MK_DIAGNOSTIC"
        report = json.loads(sidecar.read_text(encoding="utf-8"))
        assert report["whole_initial_mass_gate"]["status"] == "WITHIN_WHOLE_TARGET_1PCT_DIAGNOSTIC"
        assert all(row["status"] == "WITHIN_3PCT_DIAGNOSTIC" for row in report["per_mkfluid_diagnostics"])

        failed = dict(receipt)
        failed["status"] = "failed"
        failed_path = root / "failed-receipt.json"
        failed_path.write_text(json.dumps(failed), encoding="utf-8")
        expect_rejected(lambda: MODULE.audit(loaded_path, failed_path, root / "failed-audit.json"), "non-completed receipt")

        wrong_hash = dict(receipt)
        wrong_hash["request_sha256"] = "0" * 64
        wrong_hash_path = root / "wrong-hash-receipt.json"
        wrong_hash_path.write_text(json.dumps(wrong_hash), encoding="utf-8")
        expect_rejected(lambda: MODULE.audit(loaded_path, wrong_hash_path, root / "wrong-hash-audit.json"), "wrong request digest")

        wrong_dp_root = root / "wrong-dp"
        wrong_dp_root.mkdir()
        (wrong_dp_root / "generated.xml").write_text(generated_xml(MODULE.motion_file_names(Path(expected["definition"]["path"]))[0], dp="0.0126"), encoding="utf-8")
        wrong_dp = dict(receipt)
        wrong_dp["output_root"] = str(wrong_dp_root)
        wrong_dp_path = root / "wrong-dp-receipt.json"
        wrong_dp_path.write_text(json.dumps(wrong_dp), encoding="utf-8")
        expect_rejected(lambda: MODULE.audit(loaded_path, wrong_dp_path, root / "wrong-dp-audit.json"), "generated dp mismatch")

        duplicate_mass = root / "duplicate-mass.xml"
        duplicate_mass.write_text(generated_xml(MODULE.motion_file_names(Path(expected["definition"]["path"]))[0]).replace("<constants>", "<massfluid value=\"0.001\"/><constants>", 1), encoding="utf-8")
        expect_rejected(lambda: MODULE.parse_generated_xml(duplicate_mass), "non-uniform/duplicate mass metadata")

        widened = copy.deepcopy(request)
        widened["scope"]["threshold_widening"] = True
        widened_path = root / "widened-request.json"
        widened_path.write_text(json.dumps(widened), encoding="utf-8")
        expect_rejected(lambda: MODULE.validate_request_sources(widened_path, widened, manifest_candidate), "threshold widening")

    print("stage2 F2-S1 coarse grid per-MK source/mass/receipt counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
