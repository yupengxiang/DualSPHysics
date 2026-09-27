from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import f8_r008_attempt_output_binding_diagnostic_v1 as diagnostic


def _process_generation(pid: int = 101) -> dict[str, object]:
    return {
        "pid_namespace_inode_hex": "0000000000000001",
        "pid": pid,
        "start_monotonic_ns_hex": "0000000000000002",
        "kernel_starttime_ticks_hex": "0000000000000003",
        "birth_seq_hex": "0000000000000004",
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _manifest(root: Path, files: dict[str, bytes], *, attempt_id: str = "attempt-a",
              nonce_hex: str = "a" * 64, process_pid: int = 101) -> bytes:
    root_stat = root.stat()
    process = _process_generation(process_pid)
    file_entries: list[dict[str, object]] = []
    for name, payload in sorted(files.items()):
        path = root / name
        path.write_bytes(payload)
        file_stat = path.stat()
        file_entries.append({
            "relative_path": name,
            "writer_id": "writer-main",
            "attempt_id": attempt_id,
            "nonce_hex": nonce_hex,
            "process_generation": process,
            "dev_hex": f"{file_stat.st_dev:016x}",
            "ino_hex": f"{file_stat.st_ino:016x}",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    document = {
        "schema": diagnostic.INPUT_SCHEMA,
        "attempt_id": attempt_id,
        "nonce_hex": nonce_hex,
        "process_generation": process,
        "solver_binary_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "definition_sha256": "3" * 64,
        "control_sha256": "4" * 64,
        "initial_state_sha256": "5" * 64,
        "context": {
            "case_np": 10752,
            "root_metadata_sha256": _sha("same-root-metadata"),
        },
        "output_root": {
            "dev_hex": f"{root_stat.st_dev:016x}",
            "ino_hex": f"{root_stat.st_ino:016x}",
            "preexisting": False,
            "created_by_attempt": True,
            "restart_declared": False,
            "append_declared": False,
        },
        "writers": [{
            "writer_id": "writer-main",
            "writer_role": "native-output",
            "attempt_id": attempt_id,
            "nonce_hex": nonce_hex,
            "process_generation": process,
            "root_dev_hex": f"{root_stat.st_dev:016x}",
            "root_ino_hex": f"{root_stat.st_ino:016x}",
            "files": file_entries,
        }],
    }
    return _canonical(document)


def _base_root(tmp_path: Path) -> tuple[Path, bytes]:
    root = tmp_path / "fresh-output-root"
    root.mkdir()
    files = {
        "PartOut_0000.obi4": b"synthetic-partout-a\n",
        "RunPARTs.csv": b"synthetic-runparts-a\n",
    }
    return root, _manifest(root, files)


def test_success_binds_exact_attempt_root_writers_and_files(tmp_path: Path) -> None:
    root, manifest = _base_root(tmp_path)

    result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(manifest, root)

    assert set(result) == diagnostic._OUTPUT_FIELDS
    assert result["binding_status"] == "synthetic_structural_binding_verified"
    assert result["rejection_reason"] is None
    assert result["attempt_id"] == "attempt-a"
    assert result["nonce_hex"] == "a" * 64
    assert result["case_np"] == 10752
    assert result["artifact_count"] == 2
    assert result["artifact_bytes"] == len(b"synthetic-partout-a\n") + len(b"synthetic-runparts-a\n")
    assert [item["relative_path"] for item in result["artifacts"]] == [
        "PartOut_0000.obi4", "RunPARTs.csv",
    ]
    assert result["writers"][0]["files"] == ["PartOut_0000.obi4", "RunPARTs.csv"]
    for flag in (
        "attempt_identity_bound",
        "process_generation_bound",
        "configuration_hashes_bound",
        "fresh_output_root_bound",
        "writer_identity_bound",
        "artifact_identity_bound",
        "artifact_bytes_bound",
        "artifact_sha256_bound",
    ):
        assert result[flag] is True
    assert result["source_authenticated"] is False
    assert result["runtime_authenticated"] is False
    assert result["native_integrity_evaluated"] is False
    assert result["T1_numerical"] is False
    assert result["gate_decision_eligible"] is False
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize("field", ["preexisting", "restart_declared", "append_declared"])
def test_rejects_preexisting_restart_and_append_declarations(tmp_path: Path, field: str) -> None:
    root, manifest = _base_root(tmp_path)
    document = json.loads(manifest)
    document["output_root"][field] = True

    result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(
        _canonical(document), root,
    )

    assert result["binding_status"] == "rejected"
    assert field in result["rejection_reason"]
    assert result["source_authenticated"] is False
    assert result["gate_decision_eligible"] is False
    assert result["qualification_credit"] == 0


def test_rejects_cross_attempt_concat_with_same_names_case_np_and_root_metadata(
    tmp_path: Path,
) -> None:
    root, manifest_a = _base_root(tmp_path)
    document_a = json.loads(manifest_a)
    mixed = copy.deepcopy(document_a)
    process_b = _process_generation(202)
    mixed["writers"][0]["attempt_id"] = "attempt-b"
    mixed["writers"][0]["nonce_hex"] = "b" * 64
    mixed["writers"][0]["process_generation"] = process_b
    for artifact in mixed["writers"][0]["files"]:
        artifact["attempt_id"] = "attempt-b"
        artifact["nonce_hex"] = "b" * 64
        artifact["process_generation"] = process_b

    result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(
        _canonical(mixed), root,
    )

    assert result["binding_status"] == "rejected"
    assert "crosses attempt_id" in result["rejection_reason"]
    assert result["gate_decision_eligible"] is False
    assert result["qualification_credit"] == 0


def test_rejects_inconsistent_writer_identity(tmp_path: Path) -> None:
    root, manifest = _base_root(tmp_path)
    document = json.loads(manifest)
    document["writers"][0]["files"][0]["writer_id"] = "writer-other"

    result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(
        _canonical(document), root,
    )

    assert result["binding_status"] == "rejected"
    assert "inconsistent writer identity" in result["rejection_reason"]
    assert result["writer_identity_bound"] is False


def test_rejects_file_byte_hash_or_identity_drift(tmp_path: Path) -> None:
    root, manifest = _base_root(tmp_path)
    (root / "RunPARTs.csv").write_bytes(b"modified-after-manifest\n")

    result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(manifest, root)

    assert result["binding_status"] == "rejected"
    assert "differs from manifest" in result["rejection_reason"]
    assert result["artifact_bytes_bound"] is False
    assert result["artifact_sha256_bound"] is False


def test_rejects_unexpected_or_noncanonical_manifest_fields(tmp_path: Path) -> None:
    root, manifest = _base_root(tmp_path)
    document = json.loads(manifest)
    document["unexpected"] = True

    extra_result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(
        _canonical(document), root,
    )
    assert extra_result["binding_status"] == "rejected"
    assert "exact input schema" in extra_result["rejection_reason"]

    noncanonical = json.dumps(json.loads(manifest), indent=2).encode()
    noncanonical_result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(
        noncanonical, root,
    )
    assert noncanonical_result["binding_status"] == "rejected"
    assert "canonical JSON" in noncanonical_result["rejection_reason"]


def test_rejects_symlink_or_unlisted_output_entry(tmp_path: Path) -> None:
    root, manifest = _base_root(tmp_path)
    (root / "unexpected.tmp").write_bytes(b"unlisted")
    result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(manifest, root)
    assert result["binding_status"] == "rejected"
    assert "file inventory" in result["rejection_reason"]

    (root / "unexpected.tmp").unlink()
    (root / "RunPARTs.csv").unlink()
    os.symlink("PartOut_0000.obi4", root / "RunPARTs.csv")
    symlink_result = diagnostic.diagnose_synthetic_attempt_output_binding_v1(manifest, root)
    assert symlink_result["binding_status"] == "rejected"
    assert "symlink" in symlink_result["rejection_reason"]
