"""Synthetic Linux FD-passing invariants for the future V13 snapshot broker.

These tests establish descriptor transport behavior only.  They do not mint a
trusted snapshot/capability, exercise fs-verity, or authorize a worker.
"""

from __future__ import annotations

import array
import fcntl
import os
from pathlib import Path
import socket


def _receive_one_fd(channel: socket.socket) -> int:
    data, ancillary, flags, _ = channel.recvmsg(
        1, socket.CMSG_SPACE(array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC
    )
    assert data == b"f"
    assert not flags & socket.MSG_CTRUNC
    descriptors = array.array("i")
    for level, kind, value in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            descriptors.frombytes(value[:len(value) - len(value) % descriptors.itemsize])
    assert len(descriptors) == 1
    return descriptors[0]


def test_scm_rights_preserves_readonly_open_file_description_after_path_replacement(
    tmp_path: Path,
) -> None:
    payload = b"synthetic-snapshot-original"
    path = tmp_path / "snapshot.bin"
    moved = tmp_path / "snapshot.original"
    writer = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        assert os.write(writer, payload) == len(payload)
        os.fsync(writer)
    finally:
        os.close(writer)

    source_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    received_fd: int | None = None
    try:
        before = os.fstat(source_fd)
        sender.sendmsg(
            [b"f"],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [source_fd]))],
        )
        received_fd = _receive_one_fd(receiver)
        after_receive = os.fstat(received_fd)

        assert (before.st_dev, before.st_ino) == (
            after_receive.st_dev, after_receive.st_ino
        )
        assert (fcntl.fcntl(received_fd, fcntl.F_GETFL) & os.O_ACCMODE) == os.O_RDONLY
        assert fcntl.fcntl(received_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC

        # SCM_RIGHTS transfers a reference to the same open-file description,
        # not a separately reopened descriptor.
        os.lseek(source_fd, 5, os.SEEK_SET)
        assert os.read(received_fd, 1) == payload[5:6]

        # Replacing the pathname cannot redirect the descriptor already held
        # by the receiving side.
        os.rename(path, moved)
        path.write_bytes(b"replacement-at-original-path")
        after_replace = os.fstat(received_fd)
        assert (before.st_dev, before.st_ino) == (
            after_replace.st_dev, after_replace.st_ino
        )
        assert after_replace.st_nlink == 1
        os.lseek(received_fd, 0, os.SEEK_SET)
        assert os.read(received_fd, len(payload)) == payload
    finally:
        if received_fd is not None:
            os.close(received_fd)
        os.close(source_fd)
        receiver.close()
        sender.close()
