#!/usr/bin/env python3
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
CSV_OPAQUE_SHA = "acd372d374d0261d375e4b0da679b477892d3c3537ae5d25b11184aa42777ae3"

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

request = json.loads((ROOT / "request.json").read_text())
binding = json.loads((ROOT / "binding.json").read_text())
manifest = json.loads((ROOT / "manifest.json").read_text())
downstream = json.loads((ROOT / "downstream-disabled.json").read_text())
worker = ROOT / "workers/direct_partvtk_initial_fixed_bed_coverage.py"
assert request["launch_allowed"] is False and request["execution_allowed"] is False
assert request["root_inventory_policy_source_sha256"] == POLICY_SHA
assert request["actual_initial_qa_required"] is True
assert request["initial_qa_pass_assumed"] is False
assert request["initial_qa_reported_pass"] is True
assert request["initial_qa_status"] == "actual_root175_completed_structural_qa_bound"
assert request["partvtk_frame0_contract"]["official_export_completed_by_root175"] is True
assert request["partvtk_frame0_contract"]["partvtk_launch_in_fresh075"] is False
assert request["partvtk_frame0_contract"]["uses_typed_h5_or_xdmf"] is False
assert request["partvtk_frame0_contract"]["source_csv_sha256_opaque"] == CSV_OPAQUE_SHA
assert request["actual_counts"] == binding["actual_counts"]
assert request["actual_generated_xml"].endswith("F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071.xml")
assert not request["actual_generated_xml"].endswith("_Def.xml")
assert request["actual_gencase_receipt_sha256"] == "52ce589ee3cb51136daf7188c0cedbc5a43999e28ee13557942d646d115c56dd"
assert request["actual_counts"]["total_particles"] == 174896
assert request["actual_counts"]["fluid_particles"] == 40710
assert request["bi4_read"] is False
assert not any("resource-ledger.json" in item for item in request["input_files"])
assert not any(item.endswith(".bi4") or item.endswith(".h5") or item.endswith(".xmf") or item.endswith(".xdmf") for item in request["input_files"])
csv_inputs = [item for item in request["input_files"] if item.endswith("B071-initial-all.csv")]
assert len(csv_inputs) == 1 and request["input_sha256"][csv_inputs[0]] == CSV_OPAQUE_SHA
assert request["opaque_input_sha256"][csv_inputs[0]] == CSV_OPAQUE_SHA
assert request["full801_authorized"] is False and request["full16_authorized"] is False
assert binding["files"]["initial_qa_output_directory"]["metadata_only"] is True
assert binding["files"]["initial_qa_output_directory"]["sha256"] is None
assert binding["files"]["initial_qa_official_csv"]["sha256_is_opaque_provenance"] is True
assert binding["initial_qa_official_csv_sha256_opaque"] == CSV_OPAQUE_SHA
for key in ("initial_qa_receipt", "initial_qa_provenance_report", "initial_qa_native_report"):
    assert binding["files"][key]["sha256"] == binding[key.replace("initial_qa_", "actual_initial_qa_") + "_sha256"] if key != "initial_qa_native_report" else binding["files"][key]["sha256"] == binding["actual_initial_qa_native_report_sha256"]
for stage in downstream["stages"].values():
    assert stage["launch_allowed"] is False and stage["execution_allowed"] is False
source = worker.read_text()
ast.parse(source)
for token in ("load_csv", "official_csv_sha256_opaque", "worker_rehashed_csv_bytes", "official_export_completed_before_fresh075", "surface_half_dp", "surface_one_dp", "surface_two_dp", "central_abs_y_le_0p01_count", "below_profile_count", "pairwise_overlap"):
    assert token in source, token
assert "subprocess.run" not in source
assert "h5py" not in source
assert 'iter(lambda: stream.read(1024 * 1024), b"")' in source
assert "initial_qa_pass_assumed" in source
for rel, expected in manifest["files"].items():
    path = ROOT / rel
    assert path.is_file(), rel
    assert sha(path) == expected, rel
print(json.dumps({"status": "metadata_ast_pass", "arrays_opened": False, "csv_bytes_read_during_source_prep": False, "jobs_started": False, "partvtk_launched": False, "typed_h5_dependency": False, "request_disabled": True, "initial_qa_reported_pass_bound": True, "initial_qa_pass_assumed": False, "input_files": len(request["input_files"])}, sort_keys=True))
