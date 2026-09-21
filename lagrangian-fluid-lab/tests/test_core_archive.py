import hashlib
import json
import pytest
from scripts.core_archive import archive_job, selected_outputs


def job_fixture(tmp_path):
    source = tmp_path / "attempt"
    source.mkdir()
    (source / "data.bin").write_bytes(b"measured-output")
    output = {"path": "data.bin", "bytes": 15,
              "sha256": hashlib.sha256(b"measured-output").hexdigest()}
    return {"job_id": "case-1", "status": "succeeded", "attempt_dir": str(source),
            "spec": {"host": "local"}, "result": {"job_id": "case-1",
            "execution_status": "succeeded", "outputs": [output]}}


def test_publish_idempotent_and_reject_corrupted_archive(tmp_path):
    job = job_fixture(tmp_path)
    destination = tmp_path / "archive"
    assert archive_job(job, {"local": {}}, destination)["status"] == "published"
    assert archive_job(job, {"local": {}}, destination)["status"] == "already_verified"
    (destination / "case-1/data.bin").write_bytes(b"broken")
    with pytest.raises(ValueError, match="integrity"):
        archive_job(job, {"local": {}}, destination)


def test_corrupt_source_never_publishes_partial_archive(tmp_path):
    job = job_fixture(tmp_path)
    (tmp_path / "attempt/data.bin").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        archive_job(job, {"local": {}}, tmp_path / "archive")
    assert not list((tmp_path / "archive").iterdir())


def test_scheduler_selected_uses_frozen_allocation_host(tmp_path):
    job = job_fixture(tmp_path)
    job["spec"]["host"] = "scheduler-selected"
    job["allocation"] = {"_host": "local"}
    manifest = archive_job(job, {"local": {}}, tmp_path / "archive")
    assert manifest["status"] == "published"
    archive = json.loads((tmp_path / "archive/case-1/archive.json").read_text())
    assert archive["source_host"] == "local"


def test_nonterminal_and_traversal_are_rejected(tmp_path):
    job = job_fixture(tmp_path)
    job["status"] = "running"
    with pytest.raises(ValueError, match="terminal"):
        archive_job(job, {"local": {}}, tmp_path / "archive")
    job["result"]["outputs"][0]["path"] = "../escape"
    with pytest.raises(ValueError, match="unsafe"):
        selected_outputs(job["result"])
