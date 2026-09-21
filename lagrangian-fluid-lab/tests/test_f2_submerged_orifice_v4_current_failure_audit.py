from __future__ import annotations

import json

from scripts.f2_submerged_orifice_v4_current_failure_audit import OUTPUT, audit


def test_current_v4_partition_is_gate_only_and_zero_credit():
    value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert value["status"] == "read_only_v4_failure_partition_closed"
    assert value["global"]["zero_boundnor_count"] == 29484
    assert value["global"]["zero_normal_size_count"] == 29484
    assert [(row["mk"], row["zero_boundnor_count"]) for row in value["mk_partitions"]] == [(17, 0), (18, 29484)]
    assert value["qualification_claim"] == "none"
    assert value["matrix_credit"] == 0
    controls = value["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["native_decoder_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0


def test_current_v4_partition_audit_is_repeatable_read_only(tmp_path):
    output = tmp_path / "audit.json"
    value = audit(output=output)
    assert value["mk_partitions"][1]["zero_fraction"] == 1.0
    assert output.is_file()
