from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from ds_data02_f1_eccentric_root_gpu_request_guard import (  # noqa: E402
    RequestValidationError,
    validate_request,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(tmp_path: Path, *, directory_prefix: bool = False, bad_xml_hash: bool = False) -> dict[str, object]:
    stem = tmp_path / "case"
    xml = stem.with_suffix(".xml")
    bi4 = stem.with_suffix(".bi4")
    xml.write_bytes(b"xml")
    bi4.write_bytes(b"bi4")
    prefix = stem
    if directory_prefix:
        prefix.mkdir()
        command_prefix = str(prefix)
        request_xml = str(xml)
        request_bi4 = str(bi4)
    else:
        command_prefix = str(prefix)
        request_xml = str(xml)
        request_bi4 = str(bi4)
    xml_sha = _sha256(xml)
    bi4_sha = _sha256(bi4)
    if bad_xml_hash:
        xml_sha = "0" * 64
    return {
        "command": ["solver", command_prefix],
        "gencase_prefix": str(prefix),
        "gencase_xml": request_xml,
        "gencase_bi4": request_bi4,
        "input_sha256": {request_xml: xml_sha, request_bi4: bi4_sha},
        "native_source_hashes": {"generated_xml": xml_sha, "bi4": bi4_sha},
    }


def test_accepts_file_stem_and_matching_xml_bi4_hashes(tmp_path: Path) -> None:
    report = validate_request(_request(tmp_path))
    assert report["valid"] is True
    assert report["prefix_is_directory"] is False


def test_rejects_directory_prefix(tmp_path: Path) -> None:
    request = _request(tmp_path, directory_prefix=True)
    with pytest.raises(RequestValidationError, match="directory"):
        validate_request(request, check_file_hashes=False)


def test_rejects_generated_xml_hash_mismatch(tmp_path: Path) -> None:
    request = _request(tmp_path, bad_xml_hash=True)
    with pytest.raises(RequestValidationError, match="generated XML SHA-256 mismatch"):
        validate_request(request)
