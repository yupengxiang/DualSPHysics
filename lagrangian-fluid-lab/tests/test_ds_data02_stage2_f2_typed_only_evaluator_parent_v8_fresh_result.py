from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_evaluator_parent_v8_fresh_result.py"
BASE = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-parent-v2-current-root-061-001.json"
TYPED = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-typed-evaluator-v2-current-root-061-001.json"
CURRENT = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = _load(SCRIPT, "typed_only_parent_v8_fresh_result_test")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fresh_typed(tmp_path: Path) -> Path:
    value = json.loads(TYPED.read_text(encoding="utf-8"))
    # Copy only the small dependency graph to new paths.  The result itself is
    # a tiny stand-in: V8 must bind its stat/SHA and defer content verification
    # rather than read a real 62 MB result.
    for key in ("producer_report", "proof_request", "proof", "source_contract", "frozen_request"):
        item = dict(value[key])
        source = Path(str(item["path"]))
        target = tmp_path / f"fresh-{key}.json"
        shutil.copyfile(source, target)
        copied = json.loads(target.read_text(encoding="utf-8"))
        copied["v8_test_copy"] = key
        target.write_text(json.dumps(copied, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        item["path"] = str(target)
        item["sha256"] = _sha(target)
        value[key] = item
    result = tmp_path / "fresh-result.json"
    result.write_text('{"fresh": true}\n', encoding="utf-8")
    result_stat = result.stat()
    value["result"] = {
        "path": str(result), "sha256": _sha(result), "bytes": result_stat.st_size,
        "content_sha_verified": False, "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "stat": {"bytes": result_stat.st_size, "mtime_ns": result_stat.st_mtime_ns,
                 "mode_bits": result_stat.st_mode & 0o777},
    }
    value["sha256"] = P.canonical_sha(value)
    path = tmp_path / "fresh-typed-request.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _build(tmp_path: Path, fresh: Path) -> tuple[Path, dict]:
    external = Path("/var/tmp/ds02-stage2")
    target_root = external / f"pytest-v8-fresh-{tmp_path.name}"
    output_root = target_root / "products"
    result_path = tmp_path / "v8-request.json"
    value = P.build_forward_request(
        base_request=BASE, current_binding=CURRENT, fresh_typed_request=fresh,
        output=result_path, parent_attempt_id=f"pytest-v8-{tmp_path.name}",
        supervisor_output_root=output_root, home_receipt=tmp_path / "home-receipt.json",
        max_wall_seconds=30.0, allow_missing_parent=True)
    return result_path, value


def test_v8_binds_fresh_graph_without_result_payload_hash(tmp_path: Path) -> None:
    fresh = _fresh_typed(tmp_path)
    request_path, summary = _build(tmp_path, fresh)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert summary["status"] == "READY_V8_FRESH_TYPED_RESULT_PARENT_GUARD"
    assert request["sha256"] == P.canonical_sha(request)
    assert request["typed_request"]["path"] == str(fresh.resolve())
    assert request["v8_fresh_result_forward"]["result_content_hash_during_build"] is False
    assert request["v8_fresh_result_forward"]["old_proof_reuse"] == "FORBIDDEN"
    assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    roles = [item["role"] for item in request["static_bindings"]]
    assert roles.count("typed_evaluator_request") == 1
    assert "typed_only_parent_v8_fresh_result" in roles
    assert "typed_only_parent_v7_current_bound" in roles


def test_v8_rejects_old_typed_product_path(tmp_path: Path) -> None:
    with pytest.raises(P.TypedParentV8FreshResultError, match="old product path"):
        P.build_forward_request(
            base_request=BASE, current_binding=CURRENT, fresh_typed_request=TYPED,
            output=tmp_path / "must-not-write.json", parent_attempt_id="pytest-v8-old",
            supervisor_output_root=Path("/var/tmp/ds02-stage2") / f"pytest-v8-old-{tmp_path.name}",
            home_receipt=tmp_path / "old-home-receipt.json", max_wall_seconds=30.0,
            allow_missing_parent=True)
