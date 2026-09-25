"""Minimal Linux fs-verity FD primitives for the future Core snapshot service.

This module can enable and measure file content integrity, but does not
authenticate who produced a file, pin a trusted digest, or mint a capability.
Unsupported filesystems fail closed; callers must never fall back to a path.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import os
import stat
import struct
import sys

try:
    import fcntl
except ImportError:  # Keep importing the rest of Core usable off Linux.
    fcntl = None


FS_VERITY_HASH_ALG_SHA256 = 1
FS_VERITY_HASH_ALG_SHA512 = 2
_FS_IOC_ENABLE_VERITY = None
_FS_IOC_MEASURE_VERITY = None
_ENABLE_ARG = struct.Struct("=IIIIQIIQ11Q")
_DIGEST_HEADER = struct.Struct("=HH")
_MEASUREMENT_HEADER = struct.Struct(">HH")
_MAX_DIGEST_BYTES = 64
_UNSUPPORTED_ERRNOS = {errno.EOPNOTSUPP, errno.ENOTTY}


class FsVerityError(RuntimeError):
    """An fs-verity operation failed; formal callers must keep the gate closed."""


class FsVerityUnsupportedError(FsVerityError):
    """The kernel or mounted filesystem does not support the requested ioctl."""


class FsVerityNotEnabledError(FsVerityError):
    """The descriptor does not refer to an fs-verity-enabled file."""


@dataclass(frozen=True)
class FsVerityMeasurement:
    algorithm: int
    digest: bytes

    def __post_init__(self):
        if type(self.algorithm) is not int or type(self.digest) is not bytes:
            raise ValueError("fs-verity measurement requires builtin int and bytes")
        expected = {FS_VERITY_HASH_ALG_SHA256: 32, FS_VERITY_HASH_ALG_SHA512: 64}
        if self.algorithm not in expected or len(self.digest) != expected[self.algorithm]:
            raise ValueError("unsupported fs-verity measurement algorithm or digest length")

    def to_bytes(self) -> bytes:
        """Stable encoding for pinning the complete algorithm+digest measurement."""
        return _MEASUREMENT_HEADER.pack(self.algorithm, len(self.digest)) + self.digest


@dataclass(frozen=True)
class FsVerityFileIdentity:
    device: int
    inode: int
    mount_id: int
    size: int
    link_count: int
    mtime_ns: int
    ctime_ns: int


def _ioc(direction: int, number: int, size: int) -> int:
    # Linux asm-generic ioctl encoding used by this host's UAPI headers.
    return (direction << 30) | (size << 16) | (ord("f") << 8) | number


if sys.platform.startswith("linux"):
    _FS_IOC_ENABLE_VERITY = _ioc(1, 133, _ENABLE_ARG.size)
    # The UAPI declares a four-byte flexible-array header; the ioctl accepts the
    # caller's larger buffer up to the digest bytes negotiated in that header.
    _FS_IOC_MEASURE_VERITY = _ioc(3, 134, _DIGEST_HEADER.size)


def _require_linux_support() -> None:
    if (not sys.platform.startswith("linux") or fcntl is None
            or _FS_IOC_ENABLE_VERITY is None or _FS_IOC_MEASURE_VERITY is None):
        raise FsVerityUnsupportedError("Linux fs-verity ioctls are unavailable")


def _stat_key(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _validate_fd(fd: int) -> os.stat_result:
    _require_linux_support()
    if type(fd) is not int or fd < 0:
        raise ValueError("fs-verity requires a builtin nonnegative FD")
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        info = os.fstat(fd)
    except OSError as error:
        raise ValueError("fs-verity FD is not open") from error
    if flags & os.O_ACCMODE != os.O_RDONLY:
        raise ValueError("fs-verity requires an O_RDONLY FD")
    if not descriptor_flags & fcntl.FD_CLOEXEC:
        raise ValueError("fs-verity requires a close-on-exec FD")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("fs-verity requires a single-link regular file")
    return info


def _mount_id_for_fd(fd: int) -> int:
    """Read Linux's mount ID for a still-held FD; do not resolve its file path."""
    info = _validate_fd(fd)
    fdinfo = os.open(f"/proc/self/fdinfo/{fd}", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fdinfo).st_mode):
            raise FsVerityError("FD info is not a regular procfs record")
        raw = bytearray()
        while len(raw) <= 4096:
            block = os.read(fdinfo, min(1024, 4097 - len(raw)))
            if not block:
                break
            raw.extend(block)
        if len(raw) > 4096:
            raise FsVerityError("FD info exceeded its strict byte bound")
    finally:
        os.close(fdinfo)
    if _stat_key(info) != _stat_key(os.fstat(fd)):
        raise FsVerityError("FD identity changed while reading its mount ID")
    try:
        lines = raw.decode("ascii", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise FsVerityError("FD info was not ASCII") from error
    values = [line.partition(":")[2].strip() for line in lines if line.startswith("mnt_id:")]
    if (len(values) != 1 or not values[0].isascii() or not values[0].isdigit()
            or len(values[0]) > 20):
        raise FsVerityError("FD info has no unique numeric mount ID")
    mount_id = int(values[0])
    if not 0 < mount_id < 2**64:
        raise FsVerityError("FD info mount ID is outside its unsigned range")
    return mount_id


def fd_identity(fd: int) -> FsVerityFileIdentity:
    """Return the plan's FD identity tuple, including mount ID and metadata."""
    info = _validate_fd(fd)
    mount_id = _mount_id_for_fd(fd)
    if _stat_key(info) != _stat_key(os.fstat(fd)):
        raise FsVerityError("FD metadata changed while reading identity")
    return FsVerityFileIdentity(info.st_dev, info.st_ino, mount_id, info.st_size,
                                info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def measure_fd(fd: int) -> FsVerityMeasurement:
    """Get the complete kernel fs-verity measurement from an O_RDONLY FD."""
    _validate_fd(fd)
    buffer = bytearray(_DIGEST_HEADER.pack(0, _MAX_DIGEST_BYTES) + bytes(_MAX_DIGEST_BYTES))
    try:
        fcntl.ioctl(fd, _FS_IOC_MEASURE_VERITY, buffer, True)
    except OSError as error:
        if error.errno in _UNSUPPORTED_ERRNOS:
            raise FsVerityUnsupportedError("filesystem cannot measure fs-verity") from error
        if error.errno in (errno.ENODATA, errno.EINVAL):
            raise FsVerityNotEnabledError("fs-verity is not enabled for this file") from error
        raise FsVerityError("FS_IOC_MEASURE_VERITY failed") from error
    algorithm, digest_size = _DIGEST_HEADER.unpack_from(buffer)
    return FsVerityMeasurement(algorithm, bytes(buffer[_DIGEST_HEADER.size:
                                                      _DIGEST_HEADER.size + digest_size]))


def enable_fd(fd: int, *, block_size: int = 1024) -> FsVerityMeasurement:
    """Enable SHA-256 fs-verity on a closed-to-writers snapshot and measure it.

    The caller must finish writing, fsync, close every writable FD, then open
    this FD read-only. The kernel enforces the no-writable-opener condition.
    """
    _validate_fd(fd)
    page_size = os.sysconf("SC_PAGE_SIZE")
    if (type(block_size) is not int or block_size < 1024
            or block_size > page_size or block_size & (block_size - 1)):
        raise ValueError("fs-verity block size must be a power of two within the page size")
    argument = _ENABLE_ARG.pack(
        1, FS_VERITY_HASH_ALG_SHA256, block_size, 0, 0, 0, 0, 0, *([0] * 11)
    )
    try:
        fcntl.ioctl(fd, _FS_IOC_ENABLE_VERITY, argument)
    except OSError as error:
        if error.errno in _UNSUPPORTED_ERRNOS:
            raise FsVerityUnsupportedError("kernel/filesystem does not support fs-verity here") from error
        raise FsVerityError("FS_IOC_ENABLE_VERITY failed; snapshot remains non-qualifying") from error
    return measure_fd(fd)


def verify_fd(fd: int, expected: FsVerityMeasurement) -> FsVerityMeasurement:
    """Compare an FD's measured digest and identity before/after measurement."""
    if type(expected) is not FsVerityMeasurement:
        raise ValueError("expected measurement must be an exact FsVerityMeasurement")
    before = fd_identity(fd)
    observed = measure_fd(fd)
    after = fd_identity(fd)
    if before != after:
        raise FsVerityError("FD identity changed while measuring fs-verity")
    if observed != expected:
        raise FsVerityError("fs-verity measurement mismatch")
    return observed
