#!/usr/bin/env python3
"""Reserved-parent F3 exact forcing copy and GenCase worker (V2).

The source-prepared F3 package cannot list the future staged forcing copy in
runtime-v8 input_files before reservation.  This worker runs after reservation,
checks the original owner control source, copies it to a new attempt-contained
inode beside a copied candidate Def, and invokes GenCase from that directory.
Preparation never launches GenCase or reads the production forcing payload.

V2 fixes the official GenCase output-prefix ABI.  The third argument is a
*prefix*, so ``generated`` produces ``generated.xml``,
``generated_Fluid.vtk``, ``generated_Bound.vtk`` and ``generated.bi4`` beside
the prefix; it is not a directory.  The parent runtime owns the eventual
``execution-receipt.json`` at the attempt root.  This worker reports that
receipt as an expected parent artifact and never fabricates it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

SCHEMA = "ds02.stage2.three-sentinel.f3-staged-gencase-worker.v3"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT = "three-sentinel-owner-grid-gencase-producer-f3force-staged-v3"
SMALL_CAP = 10 * 1024 * 1024
LOG_CAP = 64 * 1024
CHUNK = 1024 * 1024
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}


class WorkerFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha_valid(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise WorkerFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _compare_stat(expected: Any, actual: dict[str, int], label: str) -> None:
    if not isinstance(expected, dict):
        raise WorkerFailure(f"{label} has no expected stat")
    aliases = {"device": ("device", "st_dev"), "inode": ("inode", "st_ino"),
               "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",),
               "ctime_ns": ("ctime_ns",)}
    for key, names in aliases.items():
        name = next((item for item in names if item in expected), None)
        if name is not None and int(expected[name]) != actual[key]:
            raise WorkerFailure(f"{label} {key} differs from expected stat")


def _compare_copied_payload_stat(owner_stat: Any, actual: dict[str, int], label: str) -> None:
    """Compare source-equivalent payload facts while preserving new inode/stat identity."""
    if not isinstance(owner_stat, dict) or "bytes" not in owner_stat:
        raise WorkerFailure(f"{label} lacks owner byte count")
    if int(owner_stat["bytes"]) != actual["bytes"]:
        raise WorkerFailure(f"{label} byte count differs from owner source")


def _assert_stat_equal(before: Any, after: Any, label: str) -> None:
    """Require the same full identity/stat tuple across worker phases."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise WorkerFailure(f"{label} lacks complete before/after stat")
    fields = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
    missing = [field for field in fields if field not in before or field not in after]
    if missing:
        raise WorkerFailure(f"{label} missing full stat fields: {','.join(missing)}")
    for field in fields:
        if int(before[field]) != int(after[field]):
            raise WorkerFailure(f"{label} {field} changed between worker phases")


def _digest_stable(path: Path, label: str) -> tuple[str, dict[str, int], dict[str, int]]:
    path = _regular(path, label)
    before = _stat(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            block = source.read(CHUNK)
            if not block:
                break
            digest.update(block)
    after = _stat(path)
    if before != after:
        raise WorkerFailure(f"{label} changed during SHA pass")
    return digest.hexdigest(), before, after


def _expected(record: Any, label: str) -> tuple[Path, str, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise WorkerFailure(f"{label} lacks path")
    if not _sha_valid(record.get("sha256")):
        raise WorkerFailure(f"{label} lacks concrete SHA")
    path = _regular(Path(record["path"]), label)
    expected_stat = record.get("stat_after", record.get("stat_before", record.get("stat")))
    _compare_stat(expected_stat, _stat(path), label)
    return path, str(record["sha256"]).lower(), expected_stat


def _source_pre(record: dict[str, Any], label: str) -> dict[str, Any]:
    path, expected_sha, expected_stat = _expected(record, label)
    digest, before, after = _digest_stable(path, f"{label} pre")
    if digest != expected_sha:
        raise WorkerFailure(f"{label} pre SHA differs from owner SHA")
    _compare_stat(expected_stat, before, f"{label} pre")
    _compare_stat(expected_stat, after, f"{label} pre-after")
    return {"path": str(path), "sha256": digest, "stat_before": before,
            "stat_after": after, "expected_stat": expected_stat}


def _source_post(record: dict[str, Any], label: str, expected_sha: str,
                 expected_stat: dict[str, Any]) -> dict[str, Any]:
    path = _regular(Path(str(record["path"])), label)
    digest, before, after = _digest_stable(path, f"{label} post")
    if digest != expected_sha:
        raise WorkerFailure(f"{label} post SHA differs from owner SHA")
    _compare_stat(expected_stat, before, f"{label} post")
    _compare_stat(expected_stat, after, f"{label} post-after")
    return {"path": str(path), "sha256": digest, "stat_before": before,
            "stat_after": after, "expected_stat": expected_stat}


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise WorkerFailure(f"{label} exceeds metadata cap")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise WorkerFailure(f"{label} changed during read")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerFailure(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkerFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                   "bytes": before["bytes"], "stat_before": before, "stat_after": after}


def _tail(buffer: bytearray, chunk: bytes) -> None:
    buffer.extend(chunk)
    if len(buffer) > LOG_CAP:
        del buffer[:-LOG_CAP]


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)


def _run_child(argv: list[str], cwd: Path, timeout: float) -> dict[str, Any]:
    proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    output = bytearray(); started = time.monotonic(); old: dict[int, Any] = {}
    def cancel(signum: int, frame: Any) -> None:
        _kill_group(proc)
        raise WorkerFailure(f"worker received signal {signum}")
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            old[sig] = signal.getsignal(sig); signal.signal(sig, cancel)
        assert proc.stdout is not None
        selector = selectors.DefaultSelector(); selector.register(proc.stdout, selectors.EVENT_READ)
        while True:
            if time.monotonic() - started > timeout:
                _kill_group(proc); raise WorkerFailure(f"GenCase exceeded {timeout:g}s")
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fd, CHUNK)
                if chunk:
                    _tail(output, chunk)
                else:
                    selector.unregister(key.fileobj)
            if proc.poll() is not None and not selector.get_map():
                break
        return {"argv": argv, "cwd": str(cwd), "returncode": int(proc.returncode),
                "elapsed_seconds": time.monotonic() - started,
                "stdout_tail_utf8": bytes(output).decode("utf-8", errors="replace"),
                "stdout_tail_bytes": len(output), "log_cap_bytes": LOG_CAP}
    finally:
        for sig, handler in old.items(): signal.signal(sig, handler)
        if proc.poll() is None: _kill_group(proc)


def _product(path: Path, label: str) -> dict[str, Any]:
    if not path.exists() or path.is_symlink() or not path.is_file():
        return {"path": str(path), "status": "MISSING", "label": label}
    return {"path": str(path), "status": "PRESENT", "label": label,
            "stat": _stat(path), "sha256": None, "hash_status": "PARENT_PRODUCT_HASH_POLICY",
            "payload_read": False}


def _require_products(products: dict[str, dict[str, Any]]) -> None:
    missing = [name for name, item in products.items()
               if item.get("status") != "PRESENT"]
    if missing:
        raise WorkerFailure("GenCase returned successfully but required products are missing: "
                            + ", ".join(sorted(missing)))


def run(request_path: Path, attempt_root: Path, report_path: Path) -> dict[str, Any]:
    request, request_record = _read_json(request_path, "worker request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("request_variant") != REQUEST_VARIANT:
        raise WorkerFailure("worker request schema/variant mismatch")
    if request.get("execution_allowed") is not True:
        raise WorkerFailure("worker requires parent-normalized execution_allowed=true")
    if request.get("gencase_launch") is not True or request.get("solver_launch") is not False:
        raise WorkerFailure("invalid worker launch contract")
    root = attempt_root.expanduser().absolute(); root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink(): raise WorkerFailure("attempt root must not be symlink")
    contract = request.get("staged_gencase_worker")
    if not isinstance(contract, dict): raise WorkerFailure("missing staged worker contract")
    owner_record = contract.get("owner_forcing"); candidate_record = contract.get("candidate_def")
    source, owner_sha, owner_stat = _expected(owner_record, "owner forcing")
    candidate, candidate_sha, candidate_stat = _expected(candidate_record, "prepared candidate Def")
    input_files = request.get("input_files")
    input_sha = request.get("input_sha256", request.get("input_hashes", {}))
    if not isinstance(input_files, list) or str(source) not in {str(item) for item in input_files}:
        raise WorkerFailure("owner forcing is not in the parent runtime input_files closure")
    if not isinstance(input_sha, dict) or str(input_sha.get(str(source), "")).lower() != owner_sha:
        raise WorkerFailure("parent runtime input_files lacks the owner forcing SHA")
    grid = str(request.get("grid_label"))
    if grid not in {"original", "coarse", "fine"}: raise WorkerFailure("invalid F3 grid")
    input_dir = root / "inputs" / "F3_S1" / grid; input_dir.mkdir(parents=True, exist_ok=True)
    staged_def = input_dir / candidate.name; staged_forcing = input_dir / "CaseSloshingAccData.csv"
    if staged_def.exists() or staged_forcing.exists(): raise WorkerFailure("staged destination already exists")
    source_pre = _source_pre(owner_record, "owner forcing")
    candidate_pre, candidate_stat_pre, candidate_stat_post = _digest_stable(candidate, "prepared candidate Def")
    if candidate_pre != candidate_sha: raise WorkerFailure("candidate Def changed before copy")
    with candidate.open("rb") as src, staged_def.open("xb") as dst:
        while True:
            block = src.read(CHUNK)
            if not block: break
            dst.write(block)
        dst.flush(); os.fsync(dst.fileno())
    staged_def_sha, staged_def_before, staged_def_after = _digest_stable(staged_def, "staged candidate Def")
    if staged_def_sha != candidate_sha: raise WorkerFailure("staged candidate Def differs")
    with source.open("rb") as src, staged_forcing.open("xb") as dst:
        while True:
            block = src.read(CHUNK)
            if not block: break
            dst.write(block)
        dst.flush(); os.fsync(dst.fileno())
    staged_sha, staged_before, staged_after = _digest_stable(staged_forcing, "staged owner forcing")
    if staged_sha != owner_sha: raise WorkerFailure("staged owner forcing differs from owner SHA")
    _compare_copied_payload_stat(owner_stat, staged_before, "staged owner forcing pre")
    _compare_copied_payload_stat(owner_stat, staged_after, "staged owner forcing post")
    if staged_before["inode"] == _stat(source)["inode"]: raise WorkerFailure("hardlink/shared inode detected")
    gencase = request.get("gencase")
    if not isinstance(gencase, dict): raise WorkerFailure("missing GenCase contract")
    binary, binary_sha, _ = _expected(gencase.get("binary"), "GenCase binary")
    if binary_sha != str(gencase.get("binary_sha256", "")).lower(): raise WorkerFailure("GenCase binary SHA mismatch")
    # Official GenCase takes an output *prefix*.  It creates prefix.xml,
    # prefix_Fluid.vtk, prefix_Bound.vtk and prefix.bi4 in the prefix parent.
    output_prefix = root / "generated"
    if output_prefix.exists() or output_prefix.is_symlink():
        raise WorkerFailure("refusing existing generated output prefix")
    argv = [str(binary), str(staged_def.with_suffix("")), str(output_prefix)]
    extra = gencase.get("extra_args", ["-save:all", "-threads:1"])
    if not isinstance(extra, list) or not all(isinstance(x, str) for x in extra): raise WorkerFailure("malformed GenCase args")
    argv.extend(extra)
    child = _run_child(argv, input_dir, float(request.get("max_wall_seconds", 1800)))
    post_error = None; source_post = None; staged_post = None
    staged_def_post = None; staged_def_post_error = None
    try:
        source_post = _source_post(owner_record, "owner forcing", owner_sha, owner_stat)
        staged_post_sha, staged_post_before, staged_post_after = _digest_stable(
            staged_forcing, "staged owner forcing post")
        if staged_post_sha != owner_sha:
            raise WorkerFailure("staged owner forcing post SHA differs from owner SHA")
        _compare_copied_payload_stat(owner_stat, staged_post_before, "staged owner forcing post")
        _compare_copied_payload_stat(owner_stat, staged_post_after, "staged owner forcing post-after")
        _assert_stat_equal(staged_before, staged_post_before, "staged owner forcing pre/post")
        _assert_stat_equal(staged_after, staged_post_after, "staged owner forcing pre/post-after")
        staged_post = {"path": str(staged_forcing), "sha256": staged_post_sha,
                       "stat_before": staged_post_before, "stat_after": staged_post_after,
                       "expected_stat": owner_stat}
    except WorkerFailure as exc:
        post_error = str(exc)
    try:
        staged_def_post_sha, staged_def_post_before, staged_def_post_after = _digest_stable(
            staged_def, "staged candidate Def post")
        if staged_def_post_sha != candidate_sha:
            raise WorkerFailure("staged candidate Def post SHA differs from source Def")
        _assert_stat_equal(staged_def_before, staged_def_post_before, "staged candidate Def pre/post")
        _assert_stat_equal(staged_def_after, staged_def_post_after, "staged candidate Def pre/post-after")
        staged_def_post = {"path": str(staged_def), "sha256": staged_def_post_sha,
                           "stat_before": staged_def_post_before,
                           "stat_after": staged_def_post_after,
                           "expected_sha256": candidate_sha}
    except WorkerFailure as exc:
        staged_def_post_error = str(exc)
    products = {
        "generated_xml": _product(Path(str(output_prefix) + ".xml"), "generated_xml"),
        "fluid_vtk": _product(Path(str(output_prefix) + "_Fluid.vtk"), "fluid_vtk"),
        "bound_vtk": _product(Path(str(output_prefix) + "_Bound.vtk"), "bound_vtk"),
        "native_bi4": _product(Path(str(output_prefix) + ".bi4"), "native_bi4"),
    }
    products["parent_execution_receipt"] = {
        "path": str(root / "execution-receipt.json"),
        "status": "PARENT_RUNTIME_RECEIPT_EXPECTED",
        "owner": "parent_runtime",
        "payload_read": False,
    }
    product_error = None
    try:
        _require_products({name: item for name, item in products.items()
                           if name != "parent_execution_receipt"})
    except WorkerFailure as exc:
        product_error = str(exc)
    candidate_post_error = None
    candidate_post = None
    try:
        candidate_post_sha, candidate_post_before, candidate_post_after = _digest_stable(
            candidate, "prepared candidate Def post")
        if candidate_post_sha != candidate_sha:
            raise WorkerFailure("candidate Def changed after GenCase")
        _compare_stat(candidate_stat, candidate_post_before, "prepared candidate Def post")
        _compare_stat(candidate_stat, candidate_post_after, "prepared candidate Def post-after")
        candidate_post = {"path": str(candidate), "sha256": candidate_post_sha,
                          "stat_before": candidate_post_before,
                          "stat_after": candidate_post_after,
                          "expected_stat": candidate_stat}
    except WorkerFailure as exc:
        candidate_post_error = str(exc)
    report = {"schema": SCHEMA,
              "status": "COMPLETED" if child["returncode"] == 0 and post_error is None else "FAILED",
              "sentinel_id": request.get("sentinel_id"), "grid_label": grid,
              "request": request_record, "request_path": str(request_path.absolute()),
              "request_file_sha256": request_record["sha256"], "actual_argv": child["argv"],
              "actual_cwd": child["cwd"], "child": child,
              "source_original": {"pre": source_pre, "post": source_post,
                                   "expected_sha256": owner_sha, "expected_stat": owner_stat},
              "staged_source": {"pre": {"path": str(staged_forcing), "sha256": staged_sha,
                                           "stat_before": staged_before, "stat_after": staged_after},
                                "post": staged_post, "expected_sha256": owner_sha,
                                "expected_stat": owner_stat, "new_inode": staged_before["inode"],
                                "source_inode": _stat(source)["inode"]},
              "candidate_def": {"source_sha256": candidate_sha, "staged_sha256": staged_def_sha,
                                "source_stat": candidate_stat_pre, "staged_stat_before": staged_def_before,
                                "staged_stat_after": staged_def_after, "path": str(staged_def),
                                "source_pre": {"sha256": candidate_pre,
                                                "stat_before": candidate_stat_pre,
                                                "stat_after": candidate_stat_post},
                                "source_post": candidate_post,
                                "expected_sha256": candidate_sha,
                                "expected_stat": candidate_stat},
              "products": products, "native_header_probe": {"status": "NOT_BOUND",
                  "massfluid": UNKNOWN, "massbound": UNKNOWN, "dp": UNKNOWN, "scientific_credit": 0},
              "post_error": post_error,
              "candidate_post_error": candidate_post_error,
              "staged_def_post": staged_def_post,
              "staged_def_post_error": staged_def_post_error,
              "product_error": product_error,
              "output_prefix": str(output_prefix),
              "parent_execution_receipt": {"path": str(root / "execution-receipt.json"),
                                            "status": "PARENT_RUNTIME_RECEIPT_EXPECTED",
                                            "worker_does_not_fabricate": True},
              "source_integrity": {"original_pre_post_equal_owner": source_post is not None and source_pre["sha256"] == source_post["sha256"],
                                    "staged_pre_post_equal_owner": staged_post is not None and staged_sha == staged_post["sha256"],
                                    "parent_input_files_include_original": True,
                                    "staged_destination_created_after_worker_entry": True,
                                    "new_inode_required": True},
              "scientific_qualification": QUALIFICATION,
              "production_eligible": bool(request.get("production_eligible", True))}
    report["status"] = ("COMPLETED" if child["returncode"] == 0 and post_error is None
                         and candidate_post_error is None and staged_def_post_error is None
                         and product_error is None else "FAILED")
    report_path = report_path.expanduser().absolute(); report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists() or report_path.is_symlink(): raise WorkerFailure("refusing report overwrite")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    if child["returncode"] != 0: raise WorkerFailure(f"GenCase child returned {child['returncode']}")
    if post_error is not None: raise WorkerFailure(post_error)
    if candidate_post_error is not None: raise WorkerFailure(candidate_post_error)
    if staged_def_post_error is not None: raise WorkerFailure(staged_def_post_error)
    if product_error is not None: raise WorkerFailure(product_error)
    return report


def _write_stub(path: Path, *, tamper: bool = False, missing: bool = False,
                tamper_def: bool = False, touch_def: bool = False,
                touch_forcing: bool = False) -> None:
    path.write_text("""#!/usr/bin/env python3
import argparse, json, pathlib
p=argparse.ArgumentParser(); p.add_argument('stem'); p.add_argument('out'); a, _=p.parse_known_args()
if %r: pathlib.Path.cwd().joinpath('CaseSloshingAccData.csv').write_bytes(b'tampered')
if %r: pathlib.Path(str(a.stem)+'.xml').write_bytes(b'tampered-def')
if %r: pathlib.Path(str(a.stem)+'.xml').touch()
if %r: pathlib.Path.cwd().joinpath('CaseSloshingAccData.csv').touch()
out=pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
if not %r: pathlib.Path(str(out)+'.xml').write_text('<generated/>\\n')
if not %r: pathlib.Path(str(out)+'_Fluid.vtk').write_text('tiny\\n')
if not %r: pathlib.Path(str(out)+'_Bound.vtk').write_text('tiny\\n')
if not %r: pathlib.Path(str(out)+'.bi4').write_bytes(b'tiny-bi4')
""" % (tamper, tamper_def, touch_def, touch_forcing,
       missing, missing, missing, missing), encoding="utf-8")
    path.chmod(0o755)


def _record(path: Path) -> dict[str, Any]:
    path = _regular(path, "fixture source")
    before = _stat(path); raw = path.read_bytes(); after = _stat(path)
    if before != after: raise WorkerFailure("fixture changed")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": before["bytes"], "stat_before": before, "stat_after": after}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f3-staged-worker-") as td:
        root = Path(td); source = root / "owner" / "CaseSloshingAccData.csv"; source.parent.mkdir(parents=True)
        source.write_bytes(b"exact-owner-control-bytes\n")
        candidate = root / "candidate" / "tiny_Def.xml"; candidate.parent.mkdir(parents=True)
        candidate.write_text('<case><definition dp="0.1"/><acctimesfile value="CaseSloshingAccData.csv"/></case>\n')
        binary = root / "GenCase_linux64"; _write_stub(binary)
        owner = _record(source); candidate_rec = _record(candidate); binary_rec = _record(binary)
        req = {"schema": REQUEST_SCHEMA, "request_variant": REQUEST_VARIANT, "execution_allowed": True,
               "gencase_launch": True, "solver_launch": False, "sentinel_id": "F3-S1", "grid_label": "coarse",
               "max_wall_seconds": 30, "staged_gencase_worker": {"owner_forcing": owner, "candidate_def": candidate_rec},
               "gencase": {"binary": binary_rec, "binary_sha256": binary_rec["sha256"], "extra_args": ["-save:all", "-threads:1"]},
               "input_files": [owner["path"]], "input_sha256": {owner["path"]: owner["sha256"]},
               "production_eligible": False}
        req_path = root / "request.json"; req_path.write_text(json.dumps(req), encoding="utf-8")
        report = root / "attempt" / "report.json"
        run1 = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--run", "--request", str(req_path),
                               "--attempt-root", str(root / "attempt"), "--report", str(report)], capture_output=True, text=True)
        if run1.returncode != 0: raise AssertionError(f"positive worker failed: {run1.stdout} {run1.stderr}")
        value = json.loads(report.read_text()); assert value["status"] == "COMPLETED"
        assert value["actual_argv"][0] == str(binary)
        assert value["output_prefix"].endswith("/generated")
        assert value["products"]["generated_xml"]["path"].endswith("generated.xml")
        assert value["products"]["fluid_vtk"]["path"].endswith("generated_Fluid.vtk")
        assert value["products"]["parent_execution_receipt"]["status"] == "PARENT_RUNTIME_RECEIPT_EXPECTED"
        assert value["source_integrity"]["original_pre_post_equal_owner"]
        assert value["source_integrity"]["staged_pre_post_equal_owner"]
        assert value["staged_source"]["new_inode"] != value["staged_source"]["source_inode"]
        tamper = root / "GenCase_tamper"; _write_stub(tamper, tamper=True)
        bad = json.loads(json.dumps(req)); bad["gencase"]["binary"] = _record(tamper); bad["gencase"]["binary_sha256"] = bad["gencase"]["binary"]["sha256"]
        bad_path = root / "bad.json"; bad_path.write_text(json.dumps(bad), encoding="utf-8")
        run2 = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--run", "--request", str(bad_path),
                               "--attempt-root", str(root / "bad-attempt"), "--report", str(root / "bad-attempt/report.json")], capture_output=True, text=True)
        if run2.returncode == 0 or "post SHA differs" not in run2.stderr: raise AssertionError("tamper was accepted")
        missing = root / "GenCase_missing"; _write_stub(missing, missing=True)
        bad_missing = json.loads(json.dumps(req)); bad_missing["gencase"]["binary"] = _record(missing)
        bad_missing["gencase"]["binary_sha256"] = bad_missing["gencase"]["binary"]["sha256"]
        missing_path = root / "missing.json"; missing_path.write_text(json.dumps(bad_missing), encoding="utf-8")
        run3 = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--run", "--request", str(missing_path),
                               "--attempt-root", str(root / "missing-attempt"), "--report", str(root / "missing-attempt/report.json")], capture_output=True, text=True)
        if run3.returncode == 0 or "required products are missing" not in run3.stderr:
            raise AssertionError("missing official-prefix product was accepted")
        def expect_failure(stub: Path, suffix: str, expected: str, **flags: bool) -> None:
            _write_stub(stub, **flags)
            value = json.loads(json.dumps(req)); value["gencase"]["binary"] = _record(stub)
            value["gencase"]["binary_sha256"] = value["gencase"]["binary"]["sha256"]
            request_file = root / (suffix + ".json"); request_file.write_text(json.dumps(value), encoding="utf-8")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--run", "--request", str(request_file),
                                     "--attempt-root", str(root / (suffix + "-attempt")),
                                     "--report", str(root / (suffix + "-attempt/report.json"))],
                                    capture_output=True, text=True)
            if result.returncode == 0 or expected not in result.stderr:
                raise AssertionError(f"{suffix} mutation was accepted: {result.stderr}")
        expect_failure(root / "GenCase_def_tamper", "def-tamper",
                       "staged candidate Def post SHA differs", tamper_def=True)
        expect_failure(root / "GenCase_def_touch", "def-touch",
                       "staged candidate Def pre/post mtime_ns changed", touch_def=True)
        expect_failure(root / "GenCase_forcing_touch", "forcing-touch",
                       "staged owner forcing pre/post mtime_ns changed", touch_forcing=True)
    print("PASS_THREE_SENTINEL_OWNER_GRID_F3_STAGED_GENCASE_WORKER_V3_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true"); g.add_argument("--run", action="store_true")
    p.add_argument("--request", type=Path); p.add_argument("--attempt-root", type=Path); p.add_argument("--report", type=Path)
    args = p.parse_args(argv)
    try:
        if args.self_test: _self_test(); return 0
        if args.request is None or args.attempt_root is None or args.report is None: p.error("--run requires request/attempt-root/report")
        result = run(args.request, args.attempt_root, args.report)
        print(json.dumps({"status": result["status"], "report": str(args.report.absolute()), "scientific_credit": 0}, sort_keys=True)); return 0
    except (WorkerFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_F3_STAGED_GENCASE_WORKER_V3: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
