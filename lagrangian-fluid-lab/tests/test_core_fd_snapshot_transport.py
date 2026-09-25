"""Synthetic Linux FD-passing invariants for the future V13 snapshot broker.

These tests establish descriptor transport behavior only.  They do not mint a
trusted snapshot/capability, exercise fs-verity, or authorize a worker.
"""

from __future__ import annotations

import array
import fcntl
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys

import pytest


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


def test_rootless_bwrap_peercred_pidfd_binds_namespaced_worker_process(
    tmp_path: Path,
) -> None:
    bwrap = shutil.which("bwrap")
    if bwrap is None or not hasattr(os, "pidfd_open") or not hasattr(socket, "SO_PEERCRED"):
        pytest.skip("requires bubblewrap, Linux SO_PEERCRED, and pidfd_open")
    namespace_probe = subprocess.run(
        [bwrap, "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/", "/bin/true"],
        capture_output=True, text=True, check=False,
    )
    if namespace_probe.returncode != 0:
        pytest.skip(f"rootless user/PID namespaces unavailable: {namespace_probe.stderr.strip()}")

    socket_path = tmp_path / "broker.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    listener.listen(1)
    listener.settimeout(10)
    child_code = (
        "import socket,sys; "
        "s=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET); "
        "s.connect(sys.argv[1]); s.sendall(b'R'); s.recv(1); s.close()"
    )
    worker = subprocess.Popen([
        bwrap, "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/",
        sys.executable, "-c", child_code, str(socket_path),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    connection: socket.socket | None = None
    pidfd: int | None = None
    try:
        connection, _ = listener.accept()
        connection.settimeout(10)
        assert connection.recv(1) == b"R"
        credentials = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
        peer_pid, peer_uid, peer_gid = struct.unpack("3i", credentials)
        nspids = next(
            line.split()[1:]
            for line in Path(f"/proc/{peer_pid}/status").read_text().splitlines()
            if line.startswith("NSpid:")
        )
        pidfd = os.pidfd_open(peer_pid)

        assert peer_pid != worker.pid
        assert int(nspids[0]) == peer_pid
        assert len(nspids) >= 2
        assert peer_uid == os.getuid()
        assert peer_gid == os.getgid()
        assert fcntl.fcntl(pidfd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC

        connection.sendall(b"x")
        assert worker.wait(timeout=10) == 0, worker.stderr.read()
    finally:
        if connection is not None:
            connection.close()
        if pidfd is not None:
            os.close(pidfd)
        listener.close()
        if worker.poll() is None:
            worker.kill()
            worker.wait()
