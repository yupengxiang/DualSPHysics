from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = (
    ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v2/contract.json",
    ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/observation-parser-v1/contract.json",
)


def test_v2_reference_and_parser_contracts_are_hash_closed_and_non_admitting() -> None:
    for contract_path in CONTRACTS:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        assert contract["qualification_credit"] == 0
        assert contract["status"].startswith("static_")
        controls = contract["execution_controls"]
        assert all(value is False for value in controls.values() if isinstance(value, bool))
        assert all(value == 0 for key, value in controls.items() if key.endswith("_mutation"))
        for binding in contract["bindings"].values():
            if "sha256" not in binding:
                continue
            path = ROOT / binding["path"]
            assert path.is_file(), binding["path"]
            assert path.stat().st_size == binding["bytes"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]
