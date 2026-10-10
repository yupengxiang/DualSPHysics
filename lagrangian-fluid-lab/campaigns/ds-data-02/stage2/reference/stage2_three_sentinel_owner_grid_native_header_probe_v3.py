#!/usr/bin/env python3
"""Bounded-drain wrapper for the consumed native-header probe V2.

V2 calls ``Popen.communicate()`` and truncates the collected output only after
the decoder exits.  That is not a memory bound: a noisy or stuck custom BI4
adapter can fill the worker memory before the slice happens.  This additive
wrapper drains stdout/stderr incrementally, keeps at most ``LOG_CAP`` bytes
per stream, kills and reaps the whole decoder process group on timeout,
parent death, log overflow, or scratch overflow, and then delegates the
unchanged V2 XML/header parsing.  It never calls the decoder in its own
self-test; the self-test uses tiny manufactured subprocesses only.

The executable is the project adapter around JBinaryData, not an official
DualSPHysics tool.  Native mass/role values remain diagnostic and all QI/QN/QE
credit remains UNKNOWN.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v2.py"
LOG_CAP = 64 * 1024
SCRATCH_CAP = 256 * 1024 * 1024
TIMEOUT_S = 300.0
SCHEMA = "ds02.stage2.native-header-probe.v3"


class BoundedProbeFailure(RuntimeError):
    pass


def _load_v2() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_native_header_probe_v2_for_v3", V2_PATH)
    if spec is None or spec.loader is None:
        raise BoundedProbeFailure(f"cannot load consumed probe V2: {V2_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()


def _stat_tree_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += int(path.stat().st_size)
        except FileNotFoundError:
            continue
        if total > SCRATCH_CAP:
            return total
    return total


def _kill_reap(process: subprocess.Popen[bytes], *, force: bool = False) -> None:
    """Terminate the decoder group and always reap the direct child."""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired as exc:
            raise BoundedProbeFailure("decoder process group could not be reaped") from exc


def _bounded_capture(command: list[str], scratch: Path, *, timeout_s: float = TIMEOUT_S) -> dict[str, Any]:
    """Run one decoder command with bounded pipes and process cleanup."""
    scratch.mkdir(parents=True, exist_ok=True)
    # Remember our supervisor, not our own PID.  A direct ``getppid() !=
    # getpid()`` comparison would classify every normal child process as an
    # already-orphaned worker and mask the real decoder error.
    parent_pid = os.getppid()
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    selector = selectors.DefaultSelector()
    tails: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    counts = {"stdout": 0, "stderr": 0}
    streams = ((process.stdout, "stdout"), (process.stderr, "stderr"))
    try:
        for stream, name in streams:
            if stream is None:
                continue
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            if os.getppid() != parent_pid:
                _kill_reap(process)
                raise BoundedProbeFailure("parent died while decoder was running")
            elapsed = time.monotonic() - started
            if elapsed > timeout_s:
                _kill_reap(process)
                raise BoundedProbeFailure("decoder timed out; process group reaped")
            if _stat_tree_bytes(scratch) > SCRATCH_CAP:
                _kill_reap(process)
                raise BoundedProbeFailure("decoder scratch exceeded bounded cap; process group reaped")
            events = selector.select(timeout=min(0.1, max(0.01, timeout_s - elapsed)))
            for key, _ in events:
                stream = key.fileobj
                name = str(key.data)
                try:
                    chunk = os.read(stream.fileno(), 16 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(stream)
                    except (KeyError, ValueError):
                        pass
                    continue
                counts[name] += len(chunk)
                # The tail is bounded; overflow is a hard worker failure so a
                # malicious adapter cannot silently hide an unbounded log.
                if counts[name] > LOG_CAP:
                    _kill_reap(process)
                    raise BoundedProbeFailure(f"decoder {name} exceeded {LOG_CAP} byte cap; process group reaped")
                tails[name].extend(chunk)
        rc = process.wait(timeout=2.0)
        return {"returncode": rc, "stdout_tail": bytes(tails["stdout"]).decode(errors="replace"),
                "stderr_tail": bytes(tails["stderr"]).decode(errors="replace"),
                "stdout_bytes_seen": counts["stdout"], "stderr_bytes_seen": counts["stderr"],
                "bounded_log_cap": LOG_CAP, "scratch_cap_bytes": SCRATCH_CAP}
    except BaseException:
        if process.poll() is None:
            _kill_reap(process)
        raise
    finally:
        try:
            selector.close()
        finally:
            for stream, _ in streams:
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass


def _run_decoder(decoder: Path, native: Path, scratch: Path) -> tuple[Path, dict[str, Any]]:
    """V2-compatible decoder result using bounded pipe draining."""
    decoder = V2._regular(decoder, "project BI4 adapter")
    scratch = scratch.absolute()
    scratch.mkdir(parents=True, exist_ok=True)
    prefix = scratch / "decoded"
    command = [str(decoder), str(native), str(prefix)]
    try:
        capture = _bounded_capture(command, scratch)
        if capture["returncode"] != 0:
            raise BoundedProbeFailure(
                f"project BI4 adapter failed rc={capture['returncode']}: {capture['stderr_tail'][-1000:]}"
            )
        xml_path = V2._find_decoder_xml(prefix)
        values, xml_guard = V2._parse_decoder_xml(xml_path)
        return xml_path, {"command": command, **capture, "xml": xml_guard, "values": values,
                          "bounded_drain": True, "decoder_tool_authority": "project_custom_jbinarydata_adapter"}
    except BaseException:
        # A failed diagnostic must not leave decoder output as a hidden
        # unbounded scratch payload for a later task.
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def run(manifest_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    """Run V2's worker with this module's decoder runner substituted."""
    original = V2._run_decoder
    V2._run_decoder = _run_decoder
    output_path = output_path.absolute()
    if output_path.exists() or output_path.is_symlink():
        raise BoundedProbeFailure(f"refusing overwrite: {output_path}")
    # V2 writes its own schema before returning.  Let it write an immutable
    # temporary result, then publish the additive V3 envelope atomically so
    # the on-disk report cannot claim V2 while the caller sees V3.
    temporary_output = output_path.with_name(f".{output_path.name}.{os.getpid()}.v2tmp")
    try:
        payload = V2.run(manifest_path, attempt_root, temporary_output)
    finally:
        V2._run_decoder = original
        # V2 normally leaves its report in place after returning.  If it
        # raised, do not leave a partial report that a later parent could
        # mistake for a V3 result.
        if temporary_output.exists():
            try:
                temporary_output.unlink()
            except OSError:
                pass
    payload["schema"] = SCHEMA
    payload["bounded_decoder"] = {
        "log_cap_bytes": LOG_CAP, "scratch_cap_bytes": SCRATCH_CAP,
        "pipe_drain": "incremental", "killpg_reap": True,
        "payload_read_by_self_test": False,
    }
    # V2's temporary file was removed by the finally block; retain the same
    # cap check over the serialized V3 envelope before publication.
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(serialized.encode("utf-8")) > V2.JSON_CAP:
        raise BoundedProbeFailure("V3 result exceeds bounded JSON cap")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_tmp = output_path.with_name(f".{output_path.name}.{os.getpid()}.v3tmp")
    final_tmp.write_text(serialized, encoding="utf-8")
    final_tmp.replace(output_path)
    return payload


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="native-header-v3-bounded-") as td:
        root = Path(td)
        spam = root / "spam.py"
        spam.write_text(
            "import sys,time\n"
            "sys.stdout.buffer.write(b'x' * (65536 + 1)); sys.stdout.flush(); time.sleep(10)\n",
            encoding="utf-8")
        try:
            _bounded_capture([sys.executable, str(spam)], root / "spam-scratch", timeout_s=2.0)
        except BoundedProbeFailure as exc:
            assert "cap" in str(exc), exc
        else:
            raise AssertionError("log-overflow decoder was accepted")
        assert not any(p.name == "spam.py.child" for p in root.iterdir())

        sleepy = root / "sleepy.py"
        sleepy.write_text("import time; time.sleep(10)\n", encoding="utf-8")
        try:
            _bounded_capture([sys.executable, str(sleepy)], root / "sleep-scratch", timeout_s=0.1)
        except BoundedProbeFailure as exc:
            assert "timed out" in str(exc), exc
        else:
            raise AssertionError("timeout decoder was accepted")

        ok = root / "ok.py"
        ok.write_text("import sys,pathlib; pathlib.Path(sys.argv[2] + '.xml').write_text('<data/>')\n", encoding="utf-8")
        ok_result = _bounded_capture([sys.executable, str(ok), "native", str(root / "ok-scratch" / "decoded")],
                                     root / "ok-scratch", timeout_s=2.0)
        assert ok_result["returncode"] == 0 and ok_result["stdout_bytes_seen"] == 0
    print("PASS_NATIVE_HEADER_PROBE_V3_BOUNDED_DRAIN_REAP_FIXTURE_NO_PRODUCTION_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.manifest is None or args.attempt_root is None or args.output is None:
            parser.error("--run requires --manifest, --attempt-root, and --output")
        run(args.manifest, args.attempt_root, args.output)
        return 0
    except (BoundedProbeFailure, OSError, ValueError) as exc:
        print(f"FAILED_NATIVE_HEADER_PROBE_V3: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
