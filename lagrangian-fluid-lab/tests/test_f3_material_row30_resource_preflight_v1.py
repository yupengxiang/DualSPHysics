from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_resource_preflight_v1 as preflight


def test_current_preflight_is_read_only_and_retains_historical_budget_block() -> None:
    value = preflight.build()
    assert value["status"] == "blocked_no_worker_authorized"
    assert value["candidate"]["seeds"] == 4096
    assert value["candidate"]["substeps"] == 4
    assert value["proposed_execution_contract"]["reuse_of_prior_s2_or_any_prior_output"] == "forbidden"
    assert value["execution_controls"] == {
        "material_worker_started": False, "solver_started": False, "gpu_started": False,
        "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "T2_credit": 0,
    }
    assert any("expired" in reason for reason in value["blockers"])
    assert any("CPU" in reason for reason in value["blockers"])


def test_write_is_immutable(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    value = preflight.write(output)
    assert json.loads(output.read_text()) == value
    with pytest.raises(FileExistsError, match="immutable row30 resource preflight"):
        preflight.write(output)
