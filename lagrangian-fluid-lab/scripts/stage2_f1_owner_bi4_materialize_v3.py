#!/usr/bin/env python3
"""Materialize F1 solver inputs inside the reserved v8 attempt tree.

The v2 worker left its destination paths in the source worktree.  That made
the copies invisible to the v8 attempt-tree charge and allowed an unaccounted
side effect outside the guarded output.  v3 accepts an explicit ``--attempt-
root`` and only creates ``solver-inputs/<mode>/<prefix>.{bi4,xml}`` below it.

The producer BI4 is read only after the v8 reservation.  A regular copy is
used; hard links and symlinks are rejected.  On a copy or source-integrity
failure partial files are retained under the attempt root and a failure
receipt records them, so the parent charge covers every byte that was
created.  A receipt is written exclusively and is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat as statmod
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ds02.stage2.f1.owner-bi4-copy-materialization.v3"
RECEIPT_SCHEMA = "ds02.stage2.f1.owner-bi4-copy-materialization-receipt.v3"
CHUNK = 8 * 1024 * 1024
STAT_FIELDS = ("device", "inode", "bytes", "mode", "mtime_ns", "ctime_ns", "nlink")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def file_stat(path: Path) -> dict[str, Any]:
    value = path.stat()
    return {
        "path": str(path), "device": int(value.st_dev), "inode": int(value.st_ino),
        "bytes": int(value.st_size), "mode": int(statmod.S_IMODE(value.st_mode)),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "nlink": int(value.st_nlink),
    }


def stable_stat(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return all(before.get(key) == after.get(key) for key in STAT_FIELDS)


def _under(path: Path, root: Path) -> bool:
    return path != root and root in path.parents


def _reject_symlink_components(path: Path, root: Path) -> None:
    """Reject symlinks from the attempt root through the destination leaf."""
    root = root.resolve()
    candidate = path.expanduser()
    if candidate.is_absolute() is False:
        raise ValueError(f"destination must be relative: {path}")
    current = root
    if current.is_symlink():
        raise ValueError(f"attempt root is a symlink: {root}")
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"destination escapes attempt root: {candidate}") from exc
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(f"destination contains symlink: {current}")


def _destination(attempt_root: Path, relative: str) -> Path:
    rel = Path(str(relative))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"invalid attempt-relative destination: {relative}")
    target = (attempt_root / rel).resolve()
    if not _under(target, attempt_root):
        raise ValueError(f"destination escapes attempt root: {relative}")
    _reject_symlink_components(target, attempt_root)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing existing destination: {target}")
    return target


def _regular_source(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"{label} is not a regular file: {path}")
    return path


def atomic_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing existing receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _under(path, path.parent.parent) and path.parent != path.parent.parent:
        raise ValueError("receipt path containment check failed")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Do not use os.replace: an existing receipt must never be replaced.
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing existing receipt: {path}")
        os.link(temporary, path)
        os.unlink(temporary)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _copy_regular(source: Path, destination: Path) -> None:
    """Copy directly so a failed partial remains chargeable and auditable."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _bound_source(item: Mapping[str, Any], label: str) -> tuple[Path, dict[str, Any], str]:
    path = _regular_source(Path(str(item.get("path", ""))), label)
    expected = str(item.get("sha256", ""))
    if len(expected) != 64:
        raise ValueError(f"{label} SHA-256 is incomplete")
    before = file_stat(path)
    digest = sha256_file(path)
    expected_bytes = int(item.get("bytes", before["bytes"]))
    if digest != expected or before["bytes"] != expected_bytes:
        raise ValueError(f"{label} pre-hash/stat differs from bound evidence")
    return path, before, digest


def _destination_record(path: Path, expected: str, *, role: str, mode: str) -> dict[str, Any]:
    record: dict[str, Any] = {"mode": mode, "role": role, "path": str(path)}
    if path.exists() and not path.is_symlink():
        record["stat"] = file_stat(path)
        record["sha256"] = sha256_file(path)
        record["bytes"] = int(record["stat"]["bytes"])
        record["expected_sha256"] = expected
        record["content_match"] = record["sha256"] == expected
    else:
        record["status"] = "PARTIAL_OR_MISSING"
        record["bytes"] = int(path.stat().st_size) if path.exists() else 0
    return record


def _failure_receipt(plan_path: Path, attempt_root: Path, error: BaseException,
                     source: Mapping[str, Any] | None, destinations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA, "status": "FAILED_COPY_SOURCE_BOUND",
        "plan": str(plan_path.resolve()),
        "plan_sha256": sha256_file(plan_path), "attempt_root": str(attempt_root),
        "error": f"{type(error).__name__}: {error}",
        "source": dict(source or {}),
        "destinations": destinations,
        "partial_outputs_preserved": True,
        "source_not_modified": "UNKNOWN_UNTIL_POSTCHECK" if source else "UNKNOWN",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def materialize(plan_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    attempt_root = attempt_root.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not plan_path.is_file() or plan_path.is_symlink():
        raise FileNotFoundError(f"plan is not a regular file: {plan_path}")
    if not attempt_root.is_dir() or attempt_root.is_symlink():
        raise FileNotFoundError(f"attempt root is not a regular directory: {attempt_root}")
    if not _under(output_path, attempt_root):
        raise ValueError("receipt must be inside attempt root")
    _reject_symlink_components(output_path, attempt_root)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"refusing existing receipt: {output_path}")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError(f"unsupported plan schema: {plan.get('schema') if isinstance(plan, dict) else None}")
    source_info = plan.get("source_bi4")
    entries = plan.get("destinations")
    if not isinstance(source_info, dict) or not isinstance(entries, list) or not entries:
        raise ValueError("v3 plan requires source_bi4 and destinations")

    source_path, source_pre, source_digest = _bound_source(source_info, "source BI4")
    source_evidence: dict[str, Any] = {
        "path": str(source_path), "sha256_pre": source_digest,
        "expected_sha256": str(source_info["sha256"]), "stat_pre": source_pre,
        "bytes": int(source_pre["bytes"]),
    }
    destinations: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []
    try:
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("destination entry must be an object")
            mode = str(item.get("mode", ""))
            prefix = str(item.get("prefix_relative", ""))
            if mode not in {"same_cfl", "half_cfl"}:
                raise ValueError(f"unsupported mode: {mode}")
            if not prefix or prefix.endswith(".bi4") or prefix.endswith(".xml"):
                raise ValueError("prefix_relative must be a relative case prefix")
            xml_info = item.get("source_xml")
            if not isinstance(xml_info, dict):
                raise ValueError(f"{mode} lacks source_xml binding")
            xml_path, xml_pre, xml_digest = _bound_source(xml_info, f"{mode} source XML")
            bi4_destination = _destination(attempt_root, prefix + ".bi4")
            xml_destination = _destination(attempt_root, prefix + ".xml")
            planned.extend([
                {"mode": mode, "role": "overlay_bi4", "source": source_path,
                 "destination": bi4_destination, "expected_sha256": source_digest,
                 "expected_bytes": source_pre["bytes"]},
                {"mode": mode, "role": "overlay_xml", "source": xml_path,
                 "destination": xml_destination, "expected_sha256": xml_digest,
                 "expected_bytes": xml_pre["bytes"]},
            ])
            source_evidence.setdefault("xml_sources", []).append({
                "mode": mode, "path": str(xml_path), "sha256_pre": xml_digest,
                "expected_sha256": str(xml_info["sha256"]), "stat_pre": xml_pre,
            })
        for item in planned:
            try:
                _copy_regular(item["source"], item["destination"])
            finally:
                destinations.append(_destination_record(item["destination"], item["expected_sha256"],
                                                        role=item["role"], mode=item["mode"]))
            record = destinations[-1]
            if not record.get("content_match") or record.get("bytes") != item["expected_bytes"]:
                raise ValueError(f"destination content differs: {item['destination']}")
        source_post = file_stat(source_path)
        source_digest_post = sha256_file(source_path)
        source_evidence["stat_post"] = source_post
        source_evidence["sha256_post"] = source_digest_post
        source_evidence["stat_stable_all_fields"] = stable_stat(source_pre, source_post)
        source_evidence["content_stable"] = source_digest_post == source_digest
        if not source_evidence["stat_stable_all_fields"] or not source_evidence["content_stable"]:
            raise ValueError("source BI4 content/stat changed during materialization")
        # Small XML sources are also checked across the copy.
        for xml_info in source_evidence.get("xml_sources", []):
            xml_path = Path(str(xml_info["path"]))
            xml_post = file_stat(xml_path)
            xml_digest_post = sha256_file(xml_path)
            xml_info["stat_post"] = xml_post
            xml_info["sha256_post"] = xml_digest_post
            xml_info["stat_stable_all_fields"] = stable_stat(xml_info["stat_pre"], xml_post)
            xml_info["content_stable"] = xml_digest_post == xml_info["sha256_pre"]
            if not xml_info["stat_stable_all_fields"] or not xml_info["content_stable"]:
                raise ValueError(f"source XML changed during materialization: {xml_path}")
        result = {
            "schema": RECEIPT_SCHEMA, "status": "PASS_COPY_SOURCE_BOUND",
            "plan": str(plan_path), "plan_sha256": sha256_file(plan_path),
            "attempt_root": str(attempt_root), "source": source_evidence,
            "destinations": destinations, "all_outputs_inside_attempt_root": True,
            "source_copied_to_new_namespace": True, "source_not_modified": True,
            "copy_is_not_a_hardlink": True, "partial_outputs_preserved": False,
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
    except BaseException as error:
        result = _failure_receipt(plan_path, attempt_root, error, source_evidence, destinations)
        # Every partial file remains in the charged attempt tree.  The receipt
        # itself is also written there; only an existing receipt is fatal.
        atomic_json_exclusive(output_path, result)
        return result
    atomic_json_exclusive(output_path, result)
    return result


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ds02-f1-v3-selftest-") as td:
        root = Path(td)
        source = root / "source.bi4"
        source.write_bytes(bytes(range(256)) * 32)
        xml = root / "overlay.xml"
        xml.write_text("<case/>\n", encoding="utf-8")
        plan = root / "plan.json"
        plan.write_text(json.dumps({
            "schema": SCHEMA,
            "source_bi4": {"path": str(source), "sha256": sha256_file(source), "bytes": source.stat().st_size},
            "destinations": [{
                "mode": "same_cfl", "prefix_relative": "solver-inputs/same_cfl/case",
                "source_xml": {"path": str(xml), "sha256": sha256_file(xml), "bytes": xml.stat().st_size},
            }],
        }), encoding="utf-8")
        attempt = root / "attempt"
        attempt.mkdir()
        receipt = attempt / "materialization-receipt.json"
        result = materialize(plan, attempt, receipt)
        assert result["status"] == "PASS_COPY_SOURCE_BOUND"
        assert (attempt / "solver-inputs/same_cfl/case.bi4").is_file()
        assert (attempt / "solver-inputs/same_cfl/case.xml").is_file()
        assert result["all_outputs_inside_attempt_root"] is True
        assert file_stat(source)["nlink"] == 1
        try:
            materialize(plan, root / "attempt2", root / "attempt2/receipt.json")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing attempt root was accepted")
        outside_plan = root / "outside.json"
        outside_plan.write_text(json.dumps({
            "schema": SCHEMA,
            "source_bi4": {"path": str(source), "sha256": sha256_file(source), "bytes": source.stat().st_size},
            "destinations": [{
                "mode": "same_cfl", "prefix_relative": "../escape/case",
                "source_xml": {"path": str(xml), "sha256": sha256_file(xml), "bytes": xml.stat().st_size},
            }],
        }), encoding="utf-8")
        attempt3 = root / "attempt3"
        attempt3.mkdir()
        outside_result = materialize(outside_plan, attempt3, attempt3 / "receipt.json")
        assert outside_result["status"] == "FAILED_COPY_SOURCE_BOUND"
        assert not (root / "escape").exists()
        print("PASS F1 owner BI4/XML v3 attempt-tree self-test")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if not args.plan or not args.attempt_root or not args.output:
        parser.error("--plan, --attempt-root and --output are required unless --self-test is used")
    try:
        result = materialize(args.plan.resolve(), args.attempt_root.resolve(), args.output.resolve())
    except Exception as error:
        print(json.dumps({"status": "FAILED_BEFORE_MATERIALIZATION", "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if result["status"] == "PASS_COPY_SOURCE_BOUND" else 1


if __name__ == "__main__":
    raise SystemExit(main())
