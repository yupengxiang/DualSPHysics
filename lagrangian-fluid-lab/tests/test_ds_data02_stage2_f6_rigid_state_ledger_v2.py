import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f6_rigid_state_ledger_v2.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("rigid_state_ledger_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

ADAPTER = Path(__file__).parents[1] / "campaigns/ds-data-02/stage2/requests/f6-rigid-state-ledger-v2/f6-rigid-state-ledger-v2-input-manifest.json"
PRODUCER_OUTPUT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/STAGE2_F6_STATIC_KABSCH_COMBINED_V5/f6-static-kabsch-combined-v5-primary-001/f6-static-kabsch-combined.json")
PRODUCER_RECEIPT = PRODUCER_OUTPUT.parent / "execution-receipt.json"


def test_real_v5_adapter_exposes_conversion_report_without_h5_input():
    path, adapter, producer, rows = MODULE.validate_adapter(ADAPTER)
    assert path == ADAPTER.resolve()
    assert adapter["schema"] == MODULE.ADAPTER_SCHEMA
    assert {row["physical_case_id"] for row in rows} == MODULE.EXPECTED_CASES
    assert all("conversion_report" in row for row in rows)
    assert all("trajectory_h5" in row and row["physical_case_id"] in adapter["h5_metadata_not_input"] for row in rows)
    assert adapter["adapter_contract"]["original_manifest_modified"] is False


def test_real_v5_output_and_receipt_are_the_bound_producer_pair():
    output = json.loads(PRODUCER_OUTPUT.read_text(encoding="utf-8"))
    receipt = json.loads(PRODUCER_RECEIPT.read_text(encoding="utf-8"))
    adapter = json.loads(ADAPTER.read_text(encoding="utf-8"))
    assert output["status"] == "completed"
    assert receipt["status"] == "completed"
    assert output["bundle"]["path"] == adapter["producer_manifest"]["path"]
    assert output["bundle"]["sha256"] == adapter["producer_manifest"]["sha256"]
    assert receipt["request"]["case_id"] == "STAGE2_F6_STATIC_KABSCH_COMBINED_V5"
    assert receipt["request"]["attempt_id"] == "f6-static-kabsch-combined-v5-primary-001"


def test_adapter_keeps_h5_metadata_out_of_input_contract():
    adapter = json.loads(ADAPTER.read_text(encoding="utf-8"))
    assert all(not str(path).lower().endswith((".h5", ".hdf5", ".obi4", ".bi4")) for path in adapter.get("input_files", []))
    assert all(value["registered_as_input"] is False and value["content_opened"] is False for value in adapter["h5_metadata_not_input"].values())
