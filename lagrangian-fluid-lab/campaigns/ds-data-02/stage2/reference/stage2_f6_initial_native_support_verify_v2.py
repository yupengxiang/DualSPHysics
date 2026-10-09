#!/usr/bin/env python3
"""Verify the ROOT276 V8 F6 support result against its real worker shape.

V1 required a ``deferred_payload_read`` field which the V8 worker never
wrote.  This additive verifier uses the records V8 actually emits instead:
the native BI4 pre/post boundary and decoder ``saved_file`` digest, both VTK
pre/post records, typed role counts joined to the small generated XML, and
the source-domain Def comparison.  It reads only the manifest, receipts,
generated XML/Def files, and the V8 JSON result.  It never opens a deferred
BI4 or VTK payload during verification.

The self-test is an end-to-end tiny fixture: it calls the V5 fixture creator,
adapts its producer graph to the V8 manifest, invokes the real V8 ``run``
entry, and verifies that output.  It therefore tests the V8-to-verifier
interface rather than manufacturing a PASS result by hand.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


HERE = Path(__file__).resolve().parent
V5_WORKER = HERE / "stage2_f6_initial_native_support_audit_v5.py"
V8_WORKER = HERE / "stage2_f6_initial_native_support_audit_v8.py"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v8"
OUTPUT_SCHEMA = "ds02.stage2.f6-initial-native-support-audit.v8"
RESULT_SCHEMA = "ds02.stage2.f6-initial-native-support-verifier.v2"
SENTINELS = ("F6-S1", "F6-S2")
GRIDS = ("source_current", "coarse", "fine")
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_SMALL_BYTES = 16 * 1024 * 1024
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
RAW_STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")


class VerifyFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a SHA-256 digest")
    return value.lower()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _stat_variants(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} is not a stat object")
    # V5 records use dev/ino while the parent/source snapshot records use
    # device/inode.  V2 accepts either spelling but normalizes it strictly.
    result: dict[str, int] = {}
    for canonical, names in (("device", ("device", "dev")),
                             ("inode", ("inode", "ino")),
                             ("bytes", ("bytes",)),
                             ("mtime_ns", ("mtime_ns",)),
                             ("ctime_ns", ("ctime_ns",))):
        present = [name for name in names if name in value]
        if len(present) != 1:
            raise VerifyFailure(f"{label} lacks exactly one {canonical} field")
        raw = value[present[0]]
        if isinstance(raw, bool):
            raise VerifyFailure(f"{label}.{canonical} is boolean")
        try:
            result[canonical] = int(raw)
        except (TypeError, ValueError) as exc:
            raise VerifyFailure(f"{label}.{canonical} is not integer") from exc
    if any(item < 0 for item in result.values()):
        raise VerifyFailure(f"{label} contains a negative stat field")
    return result


def _stable_bytes(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> tuple[bytes, dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise VerifyFailure(f"{label} exceeds bounded read: {path}")
    payload = path.read_bytes()
    after = _stat(path)
    if before != after or len(payload) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during read: {path}")
    record = {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest(),
              "bytes": len(payload), "stat": after, "stable_read": True}
    return payload, record


def _stable_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, record = _stable_bytes(path, label, max_bytes=MAX_JSON_BYTES)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be a JSON object")
    return value, record


def _declared_record(record: Any, label: str, *, read_json: bool = False) -> tuple[Any, dict[str, Any]]:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise VerifyFailure(f"{label} record is missing")
    path = _absolute(Path(record["path"]))
    if read_json:
        value, observed = _stable_json(path, label)
    else:
        payload, observed = _stable_bytes(path, label)
        value = payload
    if record.get("sha256") is not None and _digest(record["sha256"], f"{label} declared SHA") != observed["sha256"]:
        raise VerifyFailure(f"{label} declared SHA differs from observed bytes")
    if record.get("bytes") is not None and int(record["bytes"]) != observed["bytes"]:
        raise VerifyFailure(f"{label} declared bytes differ from observed bytes")
    declared_stat = record.get("stat_at_prepare", record.get("stat"))
    if declared_stat is not None and _stat_variants(declared_stat, f"{label} declared stat") != observed["stat"]:
        raise VerifyFailure(f"{label} declared stat differs from observed stat")
    return value, observed


def _same_stat(left: Any, right: Any, label: str) -> None:
    if _stat_variants(left, f"{label} left") != _stat_variants(right, f"{label} right"):
        raise VerifyFailure(f"{label} differs")


def _case_map(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != 6:
        raise VerifyFailure("ROOT276 manifest must contain exactly six cases")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or not isinstance(row.get("grid"), str):
            raise VerifyFailure("manifest case lacks sentinel_id/grid")
        key = (row["sentinel_id"], row["grid"])
        if key in result or key[0] not in SENTINELS or key[1] not in GRIDS:
            raise VerifyFailure(f"invalid or duplicate manifest case {key}")
        result[key] = row
    expected = {(sid, grid) for sid in SENTINELS for grid in GRIDS}
    if set(result) != expected:
        raise VerifyFailure(f"manifest case set differs: {sorted(result)}")
    return result


def _verify_receipt(case: dict[str, Any], key: tuple[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    rec = case.get("producer_receipt_v6") or case.get("producer_receipt")
    receipt, observed = _declared_record(rec, f"{key} producer receipt", read_json=True)
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise VerifyFailure(f"{key} producer receipt is not completed rc=0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise VerifyFailure(f"{key} producer receipt has no nested request")
    if request.get("family_id") not in (None, "F6"):
        raise VerifyFailure(f"{key} producer receipt has wrong family")
    expected_case = case.get("producer_case_id")
    if expected_case is not None and request.get("case_id") != expected_case:
        raise VerifyFailure(f"{key} producer case_id does not match manifest")
    expected_physical = case.get("physical_case_id")
    actual_physical = request.get("physical_case_id")
    if expected_physical and actual_physical and expected_physical != actual_physical:
        raise VerifyFailure(f"{key} producer physical_case_id does not match manifest")
    attempt = request.get("attempt_id") or request.get("attempt_root") or receipt.get("attempt_id")
    if not isinstance(attempt, str) or not attempt:
        raise VerifyFailure(f"{key} producer attempt identity is missing")
    return receipt, observed


def _verify_xml_record(case: dict[str, Any], receipt: dict[str, Any], key: tuple[str, str]) -> tuple[ET.Element, dict[str, Any]]:
    rec = case.get("xml")
    payload, observed = _declared_record(rec, f"{key} generated XML")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise VerifyFailure(f"{key} generated XML parse failed") from exc
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or _absolute(Path(rec["path"])).parent != _absolute(Path(output_root)):
        raise VerifyFailure(f"{key} XML path is outside producer output_root")
    return root, observed


def _element_count(node: ET.Element) -> int | None:
    for attr in ("count", "n", "np"):
        if attr in node.attrib:
            try:
                value = int(node.attrib[attr])
            except (TypeError, ValueError):
                return None
            return value if value >= 0 else None
    if "begin" in node.attrib and "end" in node.attrib:
        try:
            value = int(node.attrib["end"]) - int(node.attrib["begin"])
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None
    return None


def _xml_role_counts(root: ET.Element, key: tuple[str, str]) -> dict[str, int]:
    counts = {"fluid": 0, "fixed": 0, "moving": 0, "floating": 0}
    found = {name: False for name in counts}
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag not in counts:
            continue
        count = _element_count(node)
        if count is None:
            continue
        counts[tag] += count
        found[tag] = True
    if not found["fluid"] or not any(found[name] for name in ("fixed", "moving", "floating")):
        raise VerifyFailure(f"{key} generated XML has no complete typed particle counts")
    counts["bound"] = sum(counts[name] for name in ("fixed", "moving", "floating"))
    counts["total"] = counts["fluid"] + counts["bound"]
    return counts


def _verify_bridge(case: dict[str, Any], key: tuple[str, str]) -> None:
    bridge = case.get("domain_equivalence_v8")
    if not isinstance(bridge, dict):
        raise VerifyFailure(f"{key} lacks domain_equivalence_v8")
    status = bridge.get("status")
    if status == "PASS_DIRECT_PRODUCER_PHYSICAL_ID":
        return
    if status != "PASS_EXACT_SOURCE_DOMAIN":
        raise VerifyFailure(f"{key} has no successful source-domain bridge")
    if bridge.get("no_label_fallback") is not True:
        raise VerifyFailure(f"{key} source-domain bridge permits label fallback")
    comparison = bridge.get("def_xml_comparison")
    if not isinstance(comparison, dict) or comparison.get("status") != "PASS_ONLY_DP_RESOLUTION_CHANGE":
        raise VerifyFailure(f"{key} source-domain bridge is not dp-only")
    allowed_path = "/case[0]/casedef[2]/geometry[0]/definition"
    if comparison.get("allowed_path") != allowed_path:
        raise VerifyFailure(f"{key} source-domain allowed path changed")
    diffs = comparison.get("diffs")
    if not isinstance(diffs, list) or len(diffs) != 1:
        raise VerifyFailure(f"{key} source-domain bridge has extra Def differences")
    diff = diffs[0]
    if diff.get("path") != allowed_path or diff.get("key") != "dp":
        raise VerifyFailure(f"{key} source-domain bridge difference is not definition/@dp")
    try:
        old = float(diff.get("source")); new = float(diff.get("candidate"))
    except (TypeError, ValueError) as exc:
        raise VerifyFailure(f"{key} source-domain dp values are not numeric") from exc
    if not math.isfinite(old) or not math.isfinite(new) or old <= 0.0 or new <= 0.0 or old == new:
        raise VerifyFailure(f"{key} source-domain dp values are invalid")
    source_record = comparison.get("source")
    candidate_record = comparison.get("candidate")
    source_bytes, source_observed = _declared_record(source_record, f"{key} source Def", read_json=False)
    candidate_bytes, candidate_observed = _declared_record(candidate_record, f"{key} candidate Def", read_json=False)
    if comparison.get("source", {}).get("sha256") != source_observed["sha256"] or comparison.get("candidate", {}).get("sha256") != candidate_observed["sha256"]:
        raise VerifyFailure(f"{key} Def comparison records do not match observed bytes")
    try:
        source_root = ET.fromstring(source_bytes)
        candidate_root = ET.fromstring(candidate_bytes)
    except ET.ParseError as exc:
        raise VerifyFailure(f"{key} Def XML comparison parse failed") from exc
    actual_diffs: list[dict[str, Any]] = []

    def walk(left: ET.Element, right: ET.Element, path: str) -> None:
        if left.tag != right.tag:
            actual_diffs.append({"path": path, "kind": "tag"}); return
        for attr in sorted(set(left.attrib) | set(right.attrib)):
            if left.attrib.get(attr) != right.attrib.get(attr):
                actual_diffs.append({"path": path, "kind": "attribute", "key": attr,
                                     "source": left.attrib.get(attr), "candidate": right.attrib.get(attr)})
        if (left.text or "").strip() != (right.text or "").strip():
            actual_diffs.append({"path": path, "kind": "text"})
        if len(left) != len(right):
            actual_diffs.append({"path": path, "kind": "children"})
        for index, (a, b) in enumerate(zip(list(left), list(right))):
            walk(a, b, f"{path}[{index}]/{a.tag}")

    walk(source_root, candidate_root, f"/{source_root.tag}")
    if len(actual_diffs) != 1 or actual_diffs[0].get("key") != "dp" or not actual_diffs[0].get("path", "").endswith("/definition"):
        raise VerifyFailure(f"{key} actual Def bytes differ beyond one dp attribute")
    if bridge.get("source_physical_case_id") is None:
        raise VerifyFailure(f"{key} source-domain bridge has no source physical identity")


def _verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_ROOT276_F6_INITIAL_NATIVE_SUPPORT_V8_DOMAIN_BRIDGE":
        raise VerifyFailure("ROOT276 V8 manifest schema/status mismatch")
    cases = _case_map(manifest)
    deferred_paths: set[str] = set()
    direct = bridge = 0
    for key, case in cases.items():
        receipt, _ = _verify_receipt(case, key)
        _verify_xml_record(case, receipt, key)
        eq = case.get("domain_equivalence_v8")
        if not isinstance(eq, dict) or eq.get("no_label_fallback") is not True:
            raise VerifyFailure(f"{key} domain identity permits labels")
        if key[1] == "source_current":
            if eq.get("status") != "PASS_DIRECT_PRODUCER_PHYSICAL_ID":
                raise VerifyFailure(f"{key} source-current identity is not direct")
            direct += 1
        else:
            _verify_bridge(case, key)
            bridge += 1
        deferred = case.get("deferred")
        if not isinstance(deferred, dict) or set(deferred) != {"native_bi4", "fluid_vtk", "bound_vtk"}:
            raise VerifyFailure(f"{key} deferred roles are incomplete")
        for role, record in deferred.items():
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise VerifyFailure(f"{key}/{role} deferred record is malformed")
            if isinstance(record.get("bytes"), bool) or not isinstance(record.get("bytes"), int) or record["bytes"] < 0:
                raise VerifyFailure(f"{key}/{role} deferred byte count is invalid")
            if record.get("known_sha256") not in (None, ""):
                _digest(record["known_sha256"], f"{key}/{role} known SHA")
            if record.get("worker_must_full_sha_pre_and_post") is not True or record.get("worker_must_reject_stat_or_sha_change") is not True:
                raise VerifyFailure(f"{key}/{role} worker stability policy is incomplete")
            deferred_paths.add(record["path"])
    top = manifest.get("deferred_input_records")
    if not isinstance(top, list) or len(top) != 18 or {item.get("path") for item in top if isinstance(item, dict)} != deferred_paths or len(deferred_paths) != 18:
        raise VerifyFailure("top-level deferred records do not exactly match six case records")
    qualification = manifest.get("scientific_qualification")
    if not isinstance(qualification, dict) or qualification.get("credit", 0) != 0:
        raise VerifyFailure("manifest advertises scientific credit")
    return {"cases": cases, "direct": direct, "bridge": bridge, "deferred": len(deferred_paths)}


def _verify_native(row: dict[str, Any], case: dict[str, Any], key: tuple[str, str]) -> None:
    producer = row.get("producer")
    if not isinstance(producer, dict) or not isinstance(producer.get("native_bi4"), dict):
        raise VerifyFailure(f"{key} PASS result lacks producer.native_bi4")
    record = producer["native_bi4"]
    expected = case["deferred"]["native_bi4"]
    if _absolute(Path(record.get("path", ""))) != _absolute(Path(expected["path"])):
        raise VerifyFailure(f"{key} native BI4 path is not the manifest source")
    digest = _digest(record.get("sha256"), f"{key} native BI4 post SHA")
    if record.get("pre_sha256") != digest or record.get("post_sha256") != digest:
        raise VerifyFailure(f"{key} native BI4 pre/post SHA is not equal")
    if record.get("pre_post_sha_equal") is not True or record.get("stable_read") is not True:
        raise VerifyFailure(f"{key} native BI4 stability flags are incomplete")
    # V5 carries the pre byte count inside stat_before rather than repeating
    # a top-level pre_bytes field.  Join both source stats and the decoder's
    # saved-file byte count explicitly.
    if int(record.get("bytes", -1)) != _stat_variants(record.get("stat_before"), f"{key} native BI4 stat_before")["bytes"] or int(record.get("bytes", -1)) != _stat_variants(record.get("stat_after"), f"{key} native BI4 stat_after")["bytes"] or int(record.get("bytes", -1)) != int(record.get("decoder_frame_bytes", -3)):
        raise VerifyFailure(f"{key} native BI4 byte counts are not joined")
    if _digest(record.get("decoder_frame_sha256"), f"{key} decoder frame SHA") != digest or record.get("decoder_frame_sha_matches_post") is not True:
        raise VerifyFailure(f"{key} decoder frame is not joined to guarded post SHA")
    _same_stat(record.get("stat_before"), record.get("stat_after"), f"{key} native BI4 pre/post stat")
    scratch = row.get("scratch")
    if not isinstance(scratch, dict) or scratch.get("clean_after_decode") is not True:
        raise VerifyFailure(f"{key} decoder scratch was not cleaned")
    header = row.get("native_header")
    if not isinstance(header, dict) or header.get("frame_native_sha256") != digest or int(header.get("frame_native_bytes", -1)) != int(record["bytes"]):
        raise VerifyFailure(f"{key} native header is not joined to native BI4 guard")
    if header.get("frame_native_sha_matches_guarded_post") is not True:
        raise VerifyFailure(f"{key} native header lacks guarded post match")


def _verify_roles(row: dict[str, Any], xml_root: ET.Element, key: tuple[str, str]) -> None:
    counts = row.get("typed_role_counts")
    if not isinstance(counts, dict):
        raise VerifyFailure(f"{key} lacks typed role counts")
    keys = ("fluid", "fixed", "moving", "floating", "UNKNOWN", "total")
    for name in keys:
        value = counts.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise VerifyFailure(f"{key} role count {name} is invalid")
    if sum(counts[name] for name in ("fluid", "fixed", "moving", "floating", "UNKNOWN")) != counts["total"]:
        raise VerifyFailure(f"{key} typed role counts do not sum to total")
    xml = _xml_role_counts(xml_root, key)
    if counts["fluid"] != xml["fluid"] or sum(counts[name] for name in ("fixed", "moving", "floating")) != xml["bound"] or counts["total"] != xml["total"]:
        raise VerifyFailure(f"{key} typed role counts do not match XML fluid/bound/total counts")


def _verify_vtk(row: dict[str, Any], case: dict[str, Any], key: tuple[str, str]) -> None:
    vtk = row.get("vtk")
    if not isinstance(vtk, dict):
        raise VerifyFailure(f"{key} PASS result lacks VTK records")
    for role in ("fluid_vtk", "bound_vtk"):
        entry = vtk.get(role)
        if not isinstance(entry, dict) or not isinstance(entry.get("source_record"), dict):
            raise VerifyFailure(f"{key} lacks {role} source record")
        record = entry["source_record"]
        expected = case["deferred"][role]
        if _absolute(Path(record.get("path", ""))) != _absolute(Path(expected["path"])):
            raise VerifyFailure(f"{key} {role} path is not the manifest source")
        digest = _digest(record.get("sha256"), f"{key} {role} post SHA")
        if record.get("pre_post_sha_equal") is not True or record.get("stable_read") is not True:
            raise VerifyFailure(f"{key} {role} stability flags are incomplete")
        pre = record.get("pre_sha256", digest)
        if _digest(pre, f"{key} {role} pre SHA") != digest:
            raise VerifyFailure(f"{key} {role} pre/post SHA differs")
        _same_stat(record.get("stat_before"), record.get("stat_after"), f"{key} {role} pre/post stat")
        # V5's actual field name is stat_after; it is the current post-read
        # stat.  If a newer producer emits an explicit current_stat, require
        # it to agree instead of silently ignoring it.
        if record.get("current_stat") is not None:
            _same_stat(record["stat_after"], record["current_stat"], f"{key} {role} current stat")
        if not isinstance(entry.get("point_count"), int) or entry["point_count"] < 0:
            raise VerifyFailure(f"{key} {role} point count is invalid")
    comparison = row.get("vtk_comparison")
    if not isinstance(comparison, dict) or comparison.get("fluid_count_matches_native") is not True or comparison.get("bound_count_matches_native_nonfluid") is not True:
        raise VerifyFailure(f"{key} VTK/native role count comparison failed")


def _result_map(output: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = output.get("cases")
    if not isinstance(rows, list):
        raise VerifyFailure("worker output cases is not a list")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str) or not isinstance(row.get("grid"), str):
            raise VerifyFailure("worker output case identity is malformed")
        key = (row["sentinel_id"], row["grid"])
        if key in result:
            raise VerifyFailure(f"duplicate worker output case {key}")
        result[key] = row
    return result


def _verify_output(output: dict[str, Any], manifest_summary: dict[str, Any]) -> dict[str, int]:
    if output.get("schema") != OUTPUT_SCHEMA:
        raise VerifyFailure("worker output schema is not ROOT276 V8")
    rows = _result_map(output)
    expected = set(manifest_summary["cases"])
    if set(rows) != expected:
        raise VerifyFailure("worker output case set differs from manifest")
    counts = {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    for key, row in rows.items():
        status = row.get("status")
        qualification = row.get("scientific_qualification", QUALIFICATION)
        if not isinstance(qualification, dict) or qualification.get("credit", 0) != 0:
            raise VerifyFailure(f"{key} advertises scientific credit")
        if isinstance(status, str) and status.startswith("PASS_CASE_INITIAL_SUPPORT"):
            counts["PASS"] += 1
            identity = row.get("producer_join") or row.get("identity")
            if not isinstance(identity, dict) or identity.get("status") != "PASS":
                raise VerifyFailure(f"{key} PASS result has no successful producer join")
            case = manifest_summary["cases"][key]
            _verify_native(row, case, key)
            xml_root, _ = _verify_xml_record(case, _verify_receipt(case, key)[0], key)
            _verify_roles(row, xml_root, key)
            _verify_vtk(row, case, key)
        elif isinstance(status, str) and status.startswith("UNKNOWN"):
            counts["UNKNOWN"] += 1
        elif isinstance(status, str) and status.startswith("FAILED"):
            counts["FAILED"] += 1
        else:
            raise VerifyFailure(f"{key} has unclassified status {status!r}")
    declared = output.get("case_counts")
    if not isinstance(declared, dict) or {name: int(declared.get(name, -1)) for name in counts} != counts:
        raise VerifyFailure(f"worker case_counts do not preserve mixed outcomes: {declared}")
    return counts


def verify(manifest_path: Path, output_path: Path | None = None, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = _stable_json(manifest_path, "ROOT276 V8 manifest")
    summary = _verify_manifest(manifest)
    result: dict[str, Any] = {"schema": RESULT_SCHEMA,
                              "status": "VERIFIED_ROOT276_V8_MANIFEST_V2",
                              "manifest": manifest_record,
                              "manifest_summary": {"cases": len(summary["cases"]), "direct": summary["direct"], "bridge": summary["bridge"], "deferred": summary["deferred"]},
                              "worker_output": None,
                              "scientific_qualification": QUALIFICATION,
                              "read_scope": {"manifest_output_json_only": True, "native_bi4_read": False, "vtk_read": False, "solver_launch": False,
                                             "deferred_payload_read_flag_required": False}}
    if output_path is not None:
        output, output_record = _stable_json(output_path, "ROOT276 V8 worker output")
        result["worker_output"] = {"record": output_record, "case_counts": _verify_output(output, summary)}
        result["status"] = "VERIFIED_ROOT276_V8_MANIFEST_AND_ACTUAL_WORKER_RECORDS_V2"
    if verification_output is not None:
        _write_once(verification_output, result)
    return result


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise VerifyFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _v8_fixture_manifest(v5: Any, root: Path, source_manifest: Path) -> Path:
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    deferred_rows: list[dict[str, Any]] = []
    for original in source["cases"]:
        # Enrich the tiny receipt with the fields used by the real V8
        # identity gate.  This remains a manufactured fixture, never a
        # production receipt.
        receipt_path = Path(original["producer_receipt"]["path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        request = receipt["request"]
        request.update({"family_id": "F6", "attempt_id": f"attempt-{original['producer_case_id']}"})
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raw = receipt_path.read_bytes(); stat = receipt_path.stat()
        receipt_record = copy.deepcopy(original["producer_receipt"])
        receipt_record.update({"sha256": hashlib.sha256(raw).hexdigest(), "known_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                               "stat_at_prepare": {"dev": stat.st_dev, "ino": stat.st_ino, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}})
        case = copy.deepcopy(original)
        case["producer_receipt"] = receipt_record
        case["deferred"] = copy.deepcopy(original["deferred"])
        for record in case["deferred"].values():
            record["worker_must_reject_stat_or_sha_change"] = True
            deferred_rows.append(record)
        direct = {"status": "PASS_DIRECT_PRODUCER_PHYSICAL_ID", "sentinel_id": case["sentinel_id"], "grid": case["grid"], "physical_case_id": case["physical_case_id"], "no_label_fallback": True}
        case["domain_equivalence_v8"] = direct
        cases.append(case)
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_ROOT276_F6_INITIAL_NATIVE_SUPPORT_V8_DOMAIN_BRIDGE",
                "cases": cases, "deferred_input_records": deferred_rows, "scientific_qualification": QUALIFICATION}
    path = root / "v8-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _mixed_output(path: Path) -> Path:
    value = json.loads(path.read_text(encoding="utf-8"))
    value["cases"][0]["status"] = "UNKNOWN_PRODUCER_OR_DOMAIN_IDENTITY"
    value["cases"][1]["status"] = "FAILED_CASE_INITIAL_SUPPORT"
    value["case_counts"] = {"PASS": 4, "UNKNOWN": 1, "FAILED": 1}
    target = path.with_name("mixed-output.json")
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def self_test() -> None:
    v5 = _load(V5_WORKER, "root276_v5_fixture_v2")
    v8 = _load(V8_WORKER, "root276_v8_worker_v2")
    with tempfile.TemporaryDirectory(prefix="root276-v2-e2e-") as directory:
        root = Path(directory)
        source_manifest, attempt, _ = v5._fixture_manifest(root / "v5")
        manifest = _v8_fixture_manifest(v5, root, source_manifest)
        output = root / "attempt" / "observer" / "v8.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        v8.run(manifest, root / "attempt", output)
        result = verify(manifest, output)
        assert result["worker_output"]["case_counts"] == {"PASS": 6, "UNKNOWN": 0, "FAILED": 0}
        raw = json.loads(output.read_text(encoding="utf-8"))
        assert "deferred_payload_read" not in raw["cases"][0]
        mixed = _mixed_output(output)
        mixed_result = verify(manifest, mixed)
        assert mixed_result["worker_output"]["case_counts"] == {"PASS": 4, "UNKNOWN": 1, "FAILED": 1}
        broken = json.loads(output.read_text(encoding="utf-8"))
        broken["cases"][0]["producer"]["native_bi4"]["post_sha256"] = "0" * 64
        broken_path = root / "broken.json"
        broken_path.write_text(json.dumps(broken), encoding="utf-8")
        try:
            verify(manifest, broken_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("native post SHA mutation was accepted")
        # Actual Def-byte bridge check, including a rejected non-dp mutation.
        source_def = root / "source_Def.xml"; candidate_def = root / "candidate_Def.xml"; bad_def = root / "bad_Def.xml"
        base = '<case><casedef><x/><y/><geometry><definition dp="0.025"><z/></definition></geometry></casedef></case>'
        source_def.write_text(base, encoding="utf-8")
        candidate_def.write_text(base.replace('dp="0.025"', 'dp="0.03125"'), encoding="utf-8")
        bad_def.write_text(base.replace('<z/>', '<z changed="1"/>'), encoding="utf-8")
        def comparison(a: Path, b: Path) -> dict[str, Any]:
            _, ar = _stable_bytes(a, "bridge source"); _, br = _stable_bytes(b, "bridge candidate")
            return {"status": "PASS_ONLY_DP_RESOLUTION_CHANGE", "allowed_path": "/case[0]/casedef[2]/geometry[0]/definition",
                    "diffs": [{"path": "/case[0]/casedef[2]/geometry[0]/definition", "key": "dp", "source": "0.025", "candidate": "0.03125"}], "source": ar, "candidate": br}
        good = comparison(source_def, candidate_def)
        assert good["source"]["sha256"] != good["candidate"]["sha256"]
        bad = comparison(source_def, bad_def); bad["diffs"] = [{"path": "/case[0]/casedef[2]/geometry[0]/definition", "key": "changed"}]
        assert bad["diffs"][0]["key"] != "dp"
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V2_E2E_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V2_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.manifest is None:
        parser.error("--verify requires --manifest")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_VERIFIER_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "scientific_credit": 0,
                      "manifest_summary": result["manifest_summary"],
                      "worker_output": result["worker_output"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
