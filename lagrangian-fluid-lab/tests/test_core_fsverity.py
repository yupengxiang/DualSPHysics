from __future__ import annotations

import fcntl
import os
from pathlib import Path
import sys

import pytest

from scripts.core_fsverity import (FS_VERITY_HASH_ALG_SHA256, FsVerityError,
                                   FsVerityMeasurement,
                                   FsVerityNotEnabledError, FsVerityUnsupportedError,
                                   enable_fd, fd_identity, measure_fd, verify_fd)


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.uname().machine != "x86_64",
    reason="tested Linux x86_64 fs-verity UAPI",
)


def _readonly_synthetic_file(tmp_path: Path) -> tuple[Path, int]:
    path = tmp_path / "synthetic-snapshot.bin"
    writer = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
    try:
        payload = b"synthetic fs-verity fixture\n" * 97
        assert os.write(writer, payload) == len(payload)
        os.fsync(writer)
    finally:
        os.close(writer)
    return path, os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)


def test_fsverity_measurement_has_stable_algorithm_and_digest_encoding():
    measurement = FsVerityMeasurement(FS_VERITY_HASH_ALG_SHA256, bytes(range(32)))
    assert measurement.to_bytes() == b"\x00\x01\x00\x20" + bytes(range(32))
    with pytest.raises(ValueError):
        FsVerityMeasurement(True, bytes(32))


def test_fd_identity_includes_kernel_mount_id(tmp_path):
    path, fd = _readonly_synthetic_file(tmp_path)
    try:
        identity = fd_identity(fd)
        info = os.fstat(fd)
        assert identity.device == info.st_dev
        assert identity.inode == info.st_ino
        assert identity.size == info.st_size
        assert identity.link_count == 1
        assert identity.mount_id > 0
    finally:
        os.close(fd)


def test_fsverity_enable_measures_or_fails_closed_without_path_fallback(tmp_path):
    path, fd = _readonly_synthetic_file(tmp_path)
    try:
        before = fd_identity(fd)
        try:
            expected = enable_fd(fd)
        except FsVerityUnsupportedError:
            # This host's /home and root ext4 superblocks currently reject the
            # enable ioctl.  Unsupported is an explicit hold, never a digest fallback.
            with pytest.raises((FsVerityUnsupportedError, FsVerityNotEnabledError)):
                measure_fd(fd)
            return

        assert expected.algorithm == FS_VERITY_HASH_ALG_SHA256
        assert len(expected.digest) == 32
        after_enable = fd_identity(fd)
        assert (before.device, before.inode, before.mount_id, before.size, before.link_count) == (
            after_enable.device, after_enable.inode, after_enable.mount_id,
            after_enable.size, after_enable.link_count,
        )
        assert measure_fd(fd) == expected
        assert verify_fd(fd, expected) == expected
        with pytest.raises(FsVerityError, match="measurement mismatch"):
            verify_fd(fd, FsVerityMeasurement(FS_VERITY_HASH_ALG_SHA256, bytes(32)))
        with pytest.raises(OSError):
            os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    finally:
        os.close(fd)


def test_fsverity_fd_rejects_writable_and_multilink_files(tmp_path):
    path = tmp_path / "snapshot.bin"
    writer = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC, 0o600)
    os.write(writer, b"synthetic")
    os.fsync(writer)
    with pytest.raises(ValueError, match="O_RDONLY"):
        fd_identity(writer)
    os.close(writer)

    alias = tmp_path / "snapshot-alias.bin"
    os.link(path, alias)
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        with pytest.raises(ValueError, match="single-link"):
            fd_identity(fd)
    finally:
        os.close(fd)


def test_fsverity_fd_requires_close_on_exec(tmp_path):
    path, fd = _readonly_synthetic_file(tmp_path)
    try:
        os.set_inheritable(fd, True)
        with pytest.raises(ValueError, match="close-on-exec"):
            fd_identity(fd)
    finally:
        os.close(fd)
