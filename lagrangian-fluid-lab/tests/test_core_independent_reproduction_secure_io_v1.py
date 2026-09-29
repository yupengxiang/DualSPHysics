"""Negative tests for the descriptor-bound A8 evidence readers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import core_cross_host_root_review as cross_host
from scripts import core_independent_reproduction_secure_io_v1 as secure_io


def test_symlinked_input_is_rejected_before_bytes_are_read(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"schema":"synthetic"}', encoding="utf-8")
    link = tmp_path / "input.json"
    link.symlink_to(target)

    with pytest.raises(secure_io.SecureReadError) as caught:
        secure_io.read_bounded_json_object(
            link, label="projection", max_bytes=1024
        )

    assert caught.value.code == "FILE_OPEN_FAILED"


def test_parent_symlink_is_rejected_before_bytes_are_read(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "input.json").write_text('{"ok":true}', encoding="utf-8")
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(secure_io.SecureReadError) as caught:
        secure_io.read_bounded_json_object(
            link / "input.json", label="projection", max_bytes=1024
        )

    assert caught.value.code == "FILE_OPEN_FAILED"


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(secure_io.SecureReadError) as caught:
        secure_io.read_bounded_json_object(path, label="projection", max_bytes=1024)
    assert caught.value.code == "INVALID_JSON"


def test_cached_identity_detects_replacement_without_rehashing_large_bytes(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"first")
    cache = {}
    cross_host._file_identity(path, cache)

    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"second")
    replacement.replace(path)

    with pytest.raises(cross_host.ReviewError) as caught:
        cross_host._file_identity(path, cache)
    assert caught.value.code == "ARTIFACT_CHANGED_DURING_REVIEW"


def test_bounded_reader_rejects_size_before_returning_object(tmp_path: Path) -> None:
    path = tmp_path / "oversized.json"
    path.write_text('{"value":"too-large"}', encoding="utf-8")

    with pytest.raises(secure_io.SecureReadError) as caught:
        secure_io.read_bounded_json_object(path, label="projection", max_bytes=8)

    assert caught.value.code == "INPUT_TOO_LARGE"
