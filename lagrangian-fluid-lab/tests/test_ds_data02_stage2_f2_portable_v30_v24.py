from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/ds_data02_stage2_f2_consistent_chain_v30.py"


def _load():
    spec = importlib.util.spec_from_file_location("ds02_chain_v30_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sources(v30):
    # Follow the immutable V26 forward edge across integration worktree roots;
    # its path and SHA are the source identity, while the local checkout root
    # is only an execution location.
    frozen_v25 = Path(json.loads(v30.V26_V14.read_text())["forward_of"]["path"]).expanduser().resolve()
    graph = v30._v25_graph(frozen_v25)
    frozen_v7 = Path(graph["v7_request"]["path"]).expanduser().resolve()
    frozen_v7_value = json.loads(frozen_v7.read_text())
    frozen_overlay = Path(frozen_v7_value["v5_inputs"]["overlay"]["path"]).expanduser().resolve()
    frozen_plan = Path(frozen_v7_value["storage_plan"]["path"]).expanduser().resolve()
    return {
        "v25_v13": frozen_v25,
        "v26_v14": v30.V26_V14,
        "v25_v7": frozen_v7,
        "overlay": frozen_overlay,
        "plan": frozen_plan,
        "evaluator": v30.EVALUATOR_V3,
    }


def test_v30_builds_v24_outer_and_exact_v29_bundle_contract(tmp_path: Path) -> None:
    v30 = _load()
    sources = _sources(v30)
    before = {name: v30.file_sha(path) for name, path in sources.items()}
    tag = "v30-test-" + uuid.uuid4().hex
    external_root = v30.EXTERNAL / tag
    v15 = tmp_path / "v15.json"
    v24 = tmp_path / "v24.json"
    contract = tmp_path / "contract.json"
    result = v30.build(
        **sources, v15_output=v15, v24_output=v24, contract_output=contract,
        supervisor_root=external_root / "supervisor-v24",
        bundle_root=external_root / "bundle-target-v30",
        products=external_root / "reference-products-v30",
        index_path=v30.EXTERNAL / (tag + "-index.json"),
    )
    request = json.loads(v24.read_text())
    sidecar = json.loads(contract.read_text())
    assert request["status"] == "READY_FOR_PARENT_GUARD"
    assert request["sha256"] == v30.V24.canonical_sha(request)
    assert request["portable_v29_bundle_contract_v30"]["qualification"] == v30.UNKNOWN
    assert request["portable_v29_bundle_contract_v30"]["v29_bundle"]["source_bytes_from_overlay"] == 8644512838
    assert request["portable_v29_bundle_contract_v30"]["v29_bundle"]["overlay_entry_count"] == 443
    assert request["portable_v29_bundle_contract_v30"]["outer_v25"]["entry_timer_before_validation"] is True
    assert request["portable_v29_bundle_contract_v30"]["outputs"]["old_v25_destinations_must_not_be_reused"] is True
    assert sidecar["request_binding"]["canonical_sha256"] == request["sha256"]
    assert sidecar["request_binding"]["file_sha256"] == v30.file_sha(v24)
    assert result["frozen"]["source_bytes"] == 8644512838
    assert {name: v30.file_sha(path) for name, path in sources.items()} == before


def test_v30_rejects_v26_forward_edge_rebinding(tmp_path: Path) -> None:
    v30 = _load()
    frozen_v25 = _sources(v30)["v25_v13"]
    source = json.loads(v30.V26_V14.read_text())
    source["forward_of"] = dict(source["forward_of"])
    source["forward_of"]["path"] = str(frozen_v25.parent / "wrong-frozen-v25.json")
    source["sha256"] = v30.canonical(source)
    bad_v26 = tmp_path / "bad-v26.json"
    bad_v26.write_text(json.dumps(source, sort_keys=True) + "\n")
    with pytest.raises(v30.V30Error, match="V26.forward_of path differs"):
        v30._validate_frozen_inputs(frozen_v25, bad_v26, v30.V25_V7,
                                    v30.V25_OVERLAY, v30.V25_PLAN, v30.EVALUATOR_V3)


def test_v30_rejects_overlay_byte_contract_mutation(tmp_path: Path) -> None:
    v30 = _load()
    sources = _sources(v30)
    frozen_v25 = sources["v25_v13"]
    overlay = json.loads(sources["overlay"].read_text())
    overlay["entries"] = copy.deepcopy(overlay["entries"])
    overlay["entries"][0]["expected_bytes"] += 1
    overlay["sha256"] = v30.canonical(overlay)
    bad_overlay = tmp_path / "bad-overlay.json"
    bad_overlay.write_text(json.dumps(overlay, sort_keys=True) + "\n")
    v7 = json.loads(sources["v25_v7"].read_text())
    v7["v5_inputs"] = copy.deepcopy(v7["v5_inputs"])
    v7["v5_inputs"]["overlay"] = {
        "path": str(bad_overlay.resolve()), "sha256": v30.file_sha(bad_overlay),
    }
    v7["storage_plan"] = copy.deepcopy(v7["storage_plan"])
    v7["input_hashes"] = dict(v7["input_hashes"])
    old_overlay = str(sources["overlay"].resolve())
    v7["input_hashes"].pop(old_overlay, None)
    v7["input_hashes"][str(bad_overlay.resolve())] = v30.file_sha(bad_overlay)
    v7["sha256"] = v30.canonical(v7)
    bad_v7 = tmp_path / "bad-v7.json"
    bad_v7.write_text(json.dumps(v7, sort_keys=True) + "\n")
    with pytest.raises(v30.V30Error, match="source byte total differs"):
        v30._validate_frozen_inputs(frozen_v25, sources["v26_v14"], bad_v7,
                                    bad_overlay, sources["plan"], sources["evaluator"])
