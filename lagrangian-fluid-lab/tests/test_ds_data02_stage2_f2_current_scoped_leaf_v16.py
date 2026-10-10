from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_current_scoped_leaf_v16.py"
SPEC = importlib.util.spec_from_file_location("ds02_current_scoped_leaf_v16_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
V16 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V16)


def _role(source: Path, target: Path) -> dict[str, object]:
    info = source.stat()
    return {
        "logical_role": "current_catalog_exact_leaf",
        "source_path_provenance": str(source),
        "source_sha256": V16._sha(source),
        "source_stat_provenance": {
            "bytes": info.st_size,
            "mode_bits": info.st_mode & 0o7777,
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
            "st_dev": info.st_dev,
            "st_ino": info.st_ino,
        },
        "target_relative_path": str(target.relative_to(target.parents[1])),
    }


def test_real_v8_v12_scorer_audit_is_exact_sha_identity_only() -> None:
    audit = V16.audit_consumers()
    assert audit["status"] == "PASS_CURRENT_EXACT_SHA_IDENTITY_ONLY"
    assert {row["role"] for row in audit["roles"]} == {
        "fresh_v16_proof_consumer_v8",
        "fresh_v16_proof_consumer_v12",
        "typed_only_scorer_v1",
    }
    assert all(row["nested_manifest_path_open"] is False for row in audit["roles"])


def test_audit_rejects_a_consumer_that_reads_nested_current_manifest_path(tmp_path: Path) -> None:
    bad = tmp_path / "bad_consumer.py"
    bad.write_text(
        "def consume(current_manifest):\n"
        "    return current_manifest.get(\"path\")\n",
        encoding="utf-8",
    )
    with pytest.raises(V16.CurrentScopedLeafError, match="nested CURRENT manifest"):
        V16.audit_consumers({"bad": bad})


def test_scoped_leaf_rebind_does_not_open_internal_case_manifest(tmp_path: Path) -> None:
    current = tmp_path / "source" / "CURRENT336.json"
    current.parent.mkdir(parents=True)
    # The nested manifest is deliberately absent.  A broad CURRENT recursive
    # walk would fail; the scoped consumer must treat CURRENT as one sealed leaf.
    current.write_text(json.dumps({
        "schema": "fixture.current.v1",
        "cases": [{"manifest": {"path": str(tmp_path / "old" / "E00864.json")}}],
    }) + "\n", encoding="utf-8")
    target_root = tmp_path / "target"
    target_current = target_root / "evidence" / "CURRENT336.json"
    target_current.parent.mkdir(parents=True)
    target_current.write_bytes(current.read_bytes())
    consumer = tmp_path / "consumer.py"
    consumer.write_text("def consume(binding):\n    return binding['sha256']\n", encoding="utf-8")
    contract = V16.build_current_leaf_contract(
        current_path=current,
        expected_sha256=V16._sha(current),
        case_identity={"family_id": "F2", "physical_case_id": "CASE65",
                       "identity_status": "CANONICAL"},
        consumer_sources={"fixture_consumer": consumer},
    )
    value = {"current_manifest_binding": {"path": str(current),
                                           "sha256": V16._sha(current)},
             "case_identity": {"family_id": "F2", "physical_case_id": "CASE65"}}
    result = V16.rebind_scoped_document(
        document=_write_json(tmp_path / "request.json", value),
        root=target_root,
        source_map={str(current): (_role(current, target_current), target_current)},
        contract=contract,
    )
    assert result["status"] == "PASS_CURRENT_LEAF_REBOUND"
    rebased = json.loads(Path(result["target_path"]).read_text(encoding="utf-8"))
    assert rebased["current_manifest_binding"]["path"] == str(target_current)
    assert result["current_manifest_internal_paths_opened"] is False


def test_scoped_leaf_rejects_unresolved_historical_alias(tmp_path: Path) -> None:
    current = tmp_path / "CURRENT.json"
    current.write_text("{}\n", encoding="utf-8")
    with pytest.raises(V16.CurrentScopedLeafError, match="unresolved historical alias"):
        V16.build_current_leaf_contract(
            current_path=current,
            expected_sha256=V16._sha(current),
            case_identity={"family_id": "F2", "physical_case_id": "ROW78",
                           "identity_status": "HISTORICAL_ALIAS_UNRESOLVED"},
            consumer_sources={"fixture": current},
        )


def test_actual_copied_entry_order_is_v14_v13_v11_v15_v16_v2() -> None:
    events: list[str] = []
    stages = {
        name: (lambda name=name: events.append(name) or {"loaded": name})
        for name in V16.CHAIN_ORDER
    }
    result = V16.run_scoped_chain(stages)
    assert result["events"] == ["v14", "v13", "v11", "copied_entry_v15",
                                 "v16_scoped_rebinder", "v2_globals"]
    assert events == result["events"]
    assert result["payload_read"] is False


def test_actual_eight_document_graph_uses_scoped_current_leaf(tmp_path: Path) -> None:
    fixture = V16.build_eight_document_fixture(tmp_path / "eight-docs")
    assert fixture["document_count"] == 8
    result = V16.rebind_scoped_document(
        document=fixture["root_document"], root=fixture["target_root"],
        source_map=fixture["source_map"], contract=fixture["contract"],
        label="eight-docs",
    )
    assert result["status"] == "PASS_CURRENT_LEAF_REBOUND"
    assert result["current_manifest_internal_paths_opened"] is False
    rebound = json.loads(Path(result["target_path"]).read_text(encoding="utf-8"))
    assert rebound["current_manifest_binding"]["path"] == str(
        fixture["target_root"] / "evidence" / "CURRENT336.json")
    assert rebound["source_request"]["path"].startswith(str(fixture["target_root"]))
    # The absent nested manifest is still only a value inside the sealed
    # CURRENT bytes; it was never made into a source-map role.
    assert not any("absent-manifest" in str(path) for path in fixture["target_root"].rglob("*"))


def test_chain_imports_real_entry_modules_in_declared_order() -> None:
    paths = {
        "v14": ROOT / "scripts" / "ds_data02_stage2_f2_root242_portable_typed_executor_v14.py",
        "v13": ROOT / "scripts" / "ds_data02_stage2_f2_root242_portable_typed_executor_v13.py",
        "v11": ROOT / "scripts" / "ds_data02_stage2_f2_root242_portable_typed_executor_v11.py",
        "copied_entry_v15": ROOT / "scripts" / "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py",
        "v16_scoped_rebinder": SCRIPT,
        "v2_globals": ROOT / "scripts" / "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py",
    }
    loaded: list[str] = []

    def stage(name: str):
        def load() -> str:
            path = paths[name]
            spec = importlib.util.spec_from_file_location(
                f"ds02_v16_order_{name}", path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded.append(name)
            return module.__name__
        return load

    result = V16.run_scoped_chain({name: stage(name) for name in V16.CHAIN_ORDER})
    assert loaded == list(V16.CHAIN_ORDER)
    assert result["events"] == list(V16.CHAIN_ORDER)
    assert result["status"] == "PASS_V14_V13_V11_V15_V16_V2_ORDER"


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path
