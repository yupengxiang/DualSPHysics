"""ROOT213 metadata-only parent builder coverage.

The fixture deliberately keeps the deferred result tiny while declaring a
larger product.  The builder must stat that product, but must not hash or
open it before a parent reservation.  The command-line path is exercised in a
subprocess so this covers the actual bounded admission entry point.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root213_portable_typed_parent_v1.py"


def _load():
    spec = importlib.util.spec_from_file_location("root213_builder_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _full_stat(path: Path) -> dict[str, int]:
    info = path.stat()
    return {
        "bytes": info.st_size,
        "mode_bits": info.st_mode & 0o7777,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
    }


def _file_binding(path: Path, *, sha_key: str = "file_sha256", **extra):
    value = {"path": str(path), sha_key: _sha(path)}
    value.update(extra)
    return value


def _fixture(tmp_path: Path, module):
    source = tmp_path / "source"
    source.mkdir()

    # These are bounded metadata files.  The result file is intentionally not
    # a valid V16 result: it is a deferred product whose content belongs to a
    # later reserved child.  Its declared size is independently checked.
    result = _write(source / "products" / "v16-result.json", b"x")
    current = _write(source / "evidence" / "CURRENT.json", '{"case":78}\n')
    sidecar = _write(source / "evidence" / "v12-sidecar.json", '{"schema":"sidecar.v1"}\n')
    nested = _write(source / "evidence" / "nested-report.json", '{"schema":"report.v2"}\n')
    inner = source / "evidence" / "root200-inner.json"
    wrapper = _write(source / "evidence" / "root200-wrapper.json", '{"schema":"wrapper.v1"}\n')
    receipt = _write(source / "evidence" / "root200-receipt.json", '{"status":"COMPLETE"}\n')
    checkpoint = _write(source / "evidence" / "root200-checkpoint.json", '{"status":"PASS"}\n')
    proof = _write(source / "evidence" / "root200-proof.json", '{"schema":"proof.v1"}\n')
    producer_request = _write(source / "producer" / "179c-request.json", '{"schema":"request.v1"}\n')
    producer_receipt = _write(source / "producer" / "179c-receipt.json", '{"status":"COMPLETE"}\n')
    producer_report = _write(source / "producer" / "179c-report.json", '{"status":"COMPLETE"}\n')
    producer_proof = _write(source / "producer" / "179c-proof.json", '{"schema":"proof.v1"}\n')
    frozen = _write(source / "frozen-v15.json", '{"schema":"ds02.stage2.f2-s1-replay-request.v15"}\n')
    runtime = _write(source / "runtime" / "runtime-v6.py", "RUNTIME = True\n")
    pyvenv = _write(source / "environment" / "pyvenv.cfg", "home = /usr\nversion = 3.10\n")
    interpreter = _write(source / "environment" / "python", b"#!/bin/sh\nexit 0\n")
    interpreter.chmod(0o755)

    nested_binding = {"path": str(nested), "sha256": _sha(nested)}
    sidecar_binding = {"path": str(sidecar), "sha256": _sha(sidecar)}
    current_binding = {"path": str(current), "sha256": _sha(current)}

    inner_value = {
        "schema": module.ROOT200_INNER_SCHEMA,
        "current_manifest_binding": current_binding,
        "v12_forward": {"semantic_sidecar": sidecar_binding,
                         "source_request": {"path": "/provenance/producer-request.json",
                                             "sha256": "a" * 64}},
        "v66_parent_binding": {"nested_worker_report": nested_binding},
    }
    inner_value["sha256"] = module._canonical(inner_value)
    inner.write_text(json.dumps(inner_value, sort_keys=True) + "\n", encoding="utf-8")

    inner_binding = _file_binding(
        inner, canonical_sha256=inner_value["sha256"], schema=module.ROOT200_INNER_SCHEMA)
    result_stat = _full_stat(result)
    root200 = {
        "inner_request": inner_binding,
        "outer_wrapper": _file_binding(wrapper),
        "completed_execution_receipt": _file_binding(receipt),
        "actual_verification_checkpoint": _file_binding(checkpoint),
        "fresh_v12_proof": _file_binding(proof),
        "result": {"path": str(result), "sha256": "b" * 64, "bytes": result_stat["bytes"],
                   "stat": result_stat},
        "typed_h5": {"path": str(source / "products" / "typed.h5"),
                      "sha256": "c" * 64, "bytes": 1234},
    }

    producer = {
        "request": _file_binding(producer_request, schema="producer.request.v1"),
        "completed_receipt": _file_binding(producer_receipt),
        "parent_report": _file_binding(producer_report),
        "root_proof": _file_binding(producer_proof),
        "same_source_case": "ROOT179C",
    }
    runtime_closure = {
        "schema": "fixture.runtime-closure.v1",
        "import_mode": "PRIVATE_COPIED_RUNTIME",
        "original_worktree_fallback": "FORBIDDEN",
        "preferred_entrypoint": "runtime-v6.py",
        "roles": [{"role": "runtime_v6", "path": str(runtime), "sha256": _sha(runtime)}],
        "literal_interpreter": {
            "invocation_path": str(interpreter),
            "do_not_resolve_argv0": True,
            "target_stat": _full_stat(interpreter),
            "pyvenv_cfg": {"path": str(pyvenv), "sha256": _sha(pyvenv)},
        },
    }
    root191 = {
        "schema": module.ROOT191_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "product_mode": "TYPED_ONLY_LABELS",
        "model_invoked": False,
        "cfd_invoked": False,
        "ledger_mutated": False,
        "old_proof_reuse": False,
        "fresh_cold_credit": False,
        "qualification": dict(module.UNKNOWN),
        "quality": dict(module.UNKNOWN),
        "execution": {"raw_opened": False, "read_hdf5_or_bi4": False},
        "root191_primary_builder": {"runtime_closure": runtime_closure},
        "root200_binding": root200,
        "producer_179c_binding": producer,
        "source_frozen_request": {"path": str(frozen), "file_sha256": _sha(frozen),
                                   "schema": module.V15_SCHEMA},
    }
    root191["sha256"] = module._canonical(root191)
    root_path = tmp_path / "root191.json"
    root_path.write_text(json.dumps(root191, sort_keys=True) + "\n", encoding="utf-8")
    return root_path, result, result_stat


def test_root213_cli_build_validate_is_metadata_only(tmp_path: Path):
    module = _load()
    root191, result, result_stat = _fixture(tmp_path, module)
    output = tmp_path / "root213.json"
    fresh_root = tmp_path / "ROOT213-FRESH"
    command = [sys.executable, str(SCRIPT), "build-request",
               "--root191-request", str(root191), "--output", str(output),
               "--fresh-output-root", str(fresh_root), "--case-id", "ROOT213-FIXTURE",
               "--attempt-id", "f2-s1-root213-fixture-root-forward-030-001"]
    built = subprocess.run(command, check=True, capture_output=True, text=True)
    summary = json.loads(built.stdout)
    assert summary["payload_read"] is False
    assert summary["deferred_result_bytes"] == result_stat["bytes"]
    checked = subprocess.run([sys.executable, str(SCRIPT), "validate", "--request", str(output)],
                             check=True, capture_output=True, text=True)
    report = json.loads(checked.stdout)
    assert report["status"] == "ROOT213_METADATA_VALIDATED_READY_FOR_PARENT"
    request = json.loads(output.read_text(encoding="utf-8"))
    assert request["source_content_read_by_builder"] is False
    assert request["deferred_products"]["v16_result"]["content_read_by_builder"] is False
    assert request["v2_interface"]["parent_reservation_before_deferred_result_read"] is True
    assert request["portable_cold_replay_credit"] == "NOT_CLAIMED"
    assert result.read_bytes() == b"x"  # only the fixture assertion reads this tiny deferred file


def test_root213_rejects_deferred_result_stat_drift(tmp_path: Path):
    module = _load()
    root191, result, _ = _fixture(tmp_path, module)
    output = tmp_path / "root213.json"
    module.build_request(root191_request=root191, output=output,
                         fresh_output_root=tmp_path / "fresh", case_id="ROOT213-FIXTURE",
                         attempt_id="f2-s1-root213-fixture-root-forward-030-001")
    result.write_bytes(b"y")
    with pytest.raises(module.Root213Error, match="stat changed"):
        module.validate_request(output)
