#!/usr/bin/env python3
"""Build ROOT276 V8 with an explicit source-domain identity bridge.

V6 correctly kept four spatial producer cases UNKNOWN when their request did
not carry ``physical_case_id``.  V8 permits a case to become eligible only
when its immutable request input closure proves that it is a resolution
variant of the already identified source-current product.  The bridge reads
small receipts, requests, proof metadata and XML/Def files; BI4 and VTK
payloads are stat-only and remain deferred to the guarded worker.
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
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V6_BUILDER = HERE / "stage2_f6_initial_native_support_audit_request_v6.py"
V6_WORKER = HERE / "stage2_f6_initial_native_support_audit_v6.py"
V5_WORKER = HERE / "stage2_f6_initial_native_support_audit_v5.py"
WORKER = HERE / "stage2_f6_initial_native_support_audit_v8.py"
CONTRACT = HERE / "stage2_f6_initial_native_support_audit_contract_v8.json"
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v8"
VARIANT_SCHEMA = "ds02.stage2.f6-initial-native-support-request.v8"
V6_SCHEMA = "ds02.stage2.f6-initial-native-support-manifest.v6"
MAX_SMALL = 16 * 1024 * 1024
STAT_FIELDS = ("dev", "ino", "bytes", "mtime_ns", "ctime_ns")
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


class BuildFailure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _record(path: Path, label: str, *, parse_json: bool = False, max_bytes: int = MAX_SMALL) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise BuildFailure(f"{label} exceeds bounded read: {path}")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block); chunks.append(block)
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while read: {path}")
    value: Any = None
    if parse_json:
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildFailure(f"{label} is not JSON: {path}") from exc
        if not isinstance(value, dict):
            raise BuildFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "label": label, "bytes": after["bytes"],
                   "sha256": digest.hexdigest(), "stat": after, "stable_read": True,
                   "payload_read_by_builder": False}


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value, record = _record(path, label, parse_json=True)
    return value, record


def _read_stable_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    """Read one bounded immutable byte image and parse that same image.

    XML comparison must not hash one image and then parse a second open of the
    path.  The final stat is taken after parsing the captured bytes as well,
    so a source replacement during the parse is rejected.
    """
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL:
        raise BuildFailure(f"{label} exceeds bounded read: {path}")
    payload = path.read_bytes()
    read_after = _stat(path)
    if before != read_after or len(payload) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    digest = hashlib.sha256(payload).hexdigest()
    return payload, {"path": str(path), "label": label, "bytes": read_after["bytes"],
                     "sha256": digest, "stat": read_after,
                     "stable_read": True, "payload_read_by_builder": False}


def _map(request: dict[str, Any]) -> dict[str, str]:
    value = request.get("input_hashes", request.get("input_sha256"))
    if not isinstance(value, dict) or not value:
        raise BuildFailure("producer request has no input hash map")
    result = {}
    for path, digest in value.items():
        if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
            result[path] = digest.lower()
    if len(result) != len(value):
        raise BuildFailure("producer request input hash map contains malformed entries")
    return result


def _basename_hash(mapping: dict[str, str], predicate: Any) -> tuple[str, str] | None:
    hits = [(path, digest) for path, digest in mapping.items() if predicate(Path(path).name, path)]
    if len(hits) != 1:
        return None
    return hits[0]


def _receipt(case: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    rec = case.get("producer_receipt_v6") or case.get("producer_receipt")
    if not isinstance(rec, dict) or not isinstance(rec.get("path"), str):
        raise BuildFailure(f"{label} lacks producer receipt record")
    receipt, actual = _read_json(Path(rec["path"]), label)
    if rec.get("sha256") and rec["sha256"] != actual["sha256"]:
        raise BuildFailure(f"{label} record SHA changed")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise BuildFailure(f"{label} lacks nested request")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise BuildFailure(f"{label} is not completed rc=0")
    return receipt, request, actual


def _xml_diff(source: Path, candidate: Path) -> dict[str, Any]:
    source_bytes, source_rec = _read_stable_bytes(source, "source Def XML")
    candidate_bytes, candidate_rec = _read_stable_bytes(candidate, "candidate Def XML")
    try:
        source_root = ET.fromstring(source_bytes)
        candidate_root = ET.fromstring(candidate_bytes)
    except ET.ParseError as exc:
        raise BuildFailure(f"Def XML parse failed: {exc}") from exc
    # The parse used the captured bytes above.  Stat again after parsing to
    # close the source replacement/touch race without opening the file twice.
    if _stat(source) != source_rec["stat"] or _stat(candidate) != candidate_rec["stat"]:
        raise BuildFailure("Def XML changed after stable capture while parsing")
    diffs: list[dict[str, Any]] = []

    def walk(a: ET.Element, b: ET.Element, path: str) -> None:
        if a.tag != b.tag:
            diffs.append({"path": path, "kind": "tag", "source": a.tag, "candidate": b.tag}); return
        if a.attrib != b.attrib:
            keys = sorted(set(a.attrib) | set(b.attrib))
            for key in keys:
                if a.attrib.get(key) != b.attrib.get(key):
                    diffs.append({"path": path, "kind": "attribute", "key": key,
                                  "source": a.attrib.get(key), "candidate": b.attrib.get(key)})
        at = (a.text or "").strip(); bt = (b.text or "").strip()
        if at != bt:
            diffs.append({"path": path, "kind": "text", "source": at, "candidate": bt})
        if len(a) != len(b):
            diffs.append({"path": path, "kind": "children", "source": len(a), "candidate": len(b)})
        for index, (aa, bb) in enumerate(zip(list(a), list(b))):
            walk(aa, bb, f"{path}[{index}]/{aa.tag}")

    walk(source_root, candidate_root, f"/{source_root.tag}")
    allowed_path = "/case[0]/casedef[2]/geometry[0]/definition"
    allowed = len(diffs) == 1 and diffs[0].get("path") == allowed_path and diffs[0].get("kind") == "attribute" and diffs[0].get("key") == "dp"
    if allowed:
        try:
            old = float(diffs[0]["source"]); new = float(diffs[0]["candidate"])
            allowed = math.isfinite(old) and math.isfinite(new) and old > 0.0 and new > 0.0 and old != new
        except (TypeError, ValueError):
            allowed = False
    return {"status": "PASS_ONLY_DP_RESOLUTION_CHANGE" if allowed else "UNKNOWN_DEF_NON_RESOLUTION_CHANGE",
            "source": source_rec, "candidate": candidate_rec, "diffs": diffs,
            "allowed_path": allowed_path}


def _source_identity(source_case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    receipt, request, receipt_rec = _receipt(source_case, "source-current producer receipt")
    physical = request.get("physical_case_id")
    if not isinstance(physical, str) or not physical:
        raise BuildFailure("source-current producer has no physical_case_id")
    xml = source_case.get("xml")
    if not isinstance(xml, dict) or not isinstance(xml.get("path"), str):
        raise BuildFailure("source-current case lacks generated XML record")
    xml_path = Path(xml["path"]).expanduser().absolute()
    if xml_path.parent != Path(str(receipt.get("output_root", ""))).expanduser().absolute():
        raise BuildFailure("source-current generated XML is outside producer output root")
    _, xml_rec = _record(xml_path, "source-current generated XML")
    if xml.get("sha256") and xml["sha256"] != xml_rec["sha256"]:
        raise BuildFailure("source-current generated XML record SHA changed")
    deferred = source_case.get("deferred", {})
    native = deferred.get("native_bi4") if isinstance(deferred, dict) else None
    if not isinstance(native, dict) or not isinstance(native.get("known_sha256"), str) or not isinstance(native.get("path"), str):
        # V6 source case stores the concrete source BI4 SHA in this record.
        raise BuildFailure("source-current generated BI4 authority is not closed")
    source_map = _map(request)
    source_def = request.get("source_definition_sha256")
    if not isinstance(source_def, str) or len(source_def) != 64:
        # Some older F6-S2 requests carry two Def files and omit the
        # ``source_definition_sha256`` scalar.  The source-current case ID
        # selects its exact generated-stem Def; the auxiliary angular Def is
        # deliberately not treated as the owner source.
        case_prefix = str(request.get("case_id", ""))
        source_def_pair = _basename_hash(source_map, lambda name, _: name == f"{case_prefix}_Def.xml")
        if source_def_pair is None:
            source_def_pair = _basename_hash(source_map, lambda name, _: name.endswith("_Def.xml") and "SPATIAL" not in name and "ANGULAR_RELEASE_DP" not in name)
        source_def = source_def_pair[1] if source_def_pair else None
    if not isinstance(source_def, str):
        raise BuildFailure("source-current Def hash is absent")
    source_def_path = None
    for candidate_path, candidate_digest in source_map.items():
        if candidate_digest == source_def and Path(candidate_path).name.endswith("_Def.xml"):
            if source_def_path is not None:
                raise BuildFailure("source-current Def hash has multiple semantic paths")
            source_def_path = candidate_path
    if source_def_path is None:
        raise BuildFailure("source-current Def path for declared hash is absent")
    scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
    identity = {"physical_case_id": physical, "case_id": request.get("case_id"), "attempt_id": request.get("attempt_id"),
                "source_xml": xml_rec, "source_bi4_path": str(Path(native["path"]).expanduser().absolute()), "source_bi4_sha256": native["known_sha256"], "source_def_path": source_def_path, "source_def_sha256": source_def,
                "source_receipt_path": receipt_rec["path"], "source_receipt_sha256": receipt_rec["sha256"], "source_map": source_map, "source_scope": scope,
                "source_request": request, "source_receipt": receipt}
    return identity, request, receipt_rec


def _semantic_input_join(source: dict[str, Any], candidate_map: dict[str, str]) -> dict[str, str]:
    """Join copied source inputs by semantic role, path basename, and SHA.

    A digest appearing somewhere in ``input_sha256`` is insufficient: a
    candidate can otherwise claim a source role with an unrelated file.  The
    role's source basename and digest must each select exactly one candidate
    input.  The actual path is retained for the request audit sidecar.
    """
    roles = {
        "source_generated_xml": (Path(source["source_xml"]["path"]).name, source["source_xml"]["sha256"]),
        "source_generated_bi4": (Path(source["source_bi4_path"]).name, source["source_bi4_sha256"]),
        "source_producer_receipt": (Path(source["source_receipt_path"]).name, source["source_receipt_sha256"]),
        "source_def": (Path(source["source_def_path"]).name, source["source_def_sha256"]),
    }
    joined: dict[str, str] = {}
    for role, (basename, digest) in roles.items():
        hits = [path for path, candidate_digest in candidate_map.items()
                if Path(path).name == basename and candidate_digest == digest]
        if len(hits) != 1:
            raise BuildFailure(f"{role} semantic path/SHA join is not unique")
        joined[role] = hits[0]
    return joined


def _owner_source_records(v6_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Require actual ROOT244/ROOT252 proof/report records before any PASS."""
    result: dict[str, dict[str, Any]] = {}
    for key, label in (("proof", "ROOT244 rigid owner proof"), ("owner_proof", "ROOT252 continuous owner proof")):
        value = v6_manifest.get(key)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
            raise BuildFailure(f"{label} record with path and SHA is required")
        _, actual = _read_json(Path(value["path"]), label)
        if actual["sha256"] != value["sha256"]:
            raise BuildFailure(f"{label} SHA changed")
        result[key] = actual
    return result


def _bridge(source_case: dict[str, Any], candidate_case: dict[str, Any], sentinel: str, grid: str) -> dict[str, Any]:
    try:
        source, source_req, source_receipt_record = _source_identity(source_case)
        receipt, request, receipt_record = _receipt(candidate_case, f"{sentinel}/{grid} producer receipt")
        missing: list[str] = []
        if request.get("physical_case_id"):
            return {"status": "UNKNOWN_DIRECT_ID_ALREADY_PRESENT", "reason": "V6 direct identity should handle this case"}
        if request.get("family_id") != "F6" or request.get("case_id") != candidate_case.get("producer_case_id"):
            missing.append("request.case_id/family_id")
        if not isinstance(request.get("attempt_id"), str) or not request["attempt_id"]:
            missing.append("request.attempt_id")
        output_root = Path(str(receipt.get("output_root", ""))).expanduser().absolute()
        xml_rec = candidate_case.get("xml")
        if not isinstance(xml_rec, dict) or not isinstance(xml_rec.get("path"), str):
            missing.append("generated_xml.record")
        else:
            xml_path = Path(xml_rec["path"]).expanduser().absolute()
            if xml_path.parent != output_root:
                missing.append("generated_xml/output_root")
            _, actual_xml = _record(xml_path, f"{sentinel}/{grid} generated XML")
            if xml_rec.get("sha256") != actual_xml["sha256"]:
                missing.append("generated_xml.sha256")
        candidate_map = _map(request)
        try:
            semantic_paths = _semantic_input_join(source, candidate_map)
        except BuildFailure as exc:
            missing.append(str(exc))
            semantic_paths = {}
        for name, role in (("GenCase_linux64", "GenCase_linux64"), ("ds_data02_runtime_v2.py", "runtime_v2"), ("ds_data02_strict_dispatch_v1.py", "strict_dispatch_v1")):
            candidates = [digest for path, digest in candidate_map.items() if Path(path).name == name]
            source_candidates = [digest for path, digest in source["source_map"].items() if Path(path).name == name]
            if len(candidates) != 1 or len(source_candidates) != 1 or candidates[0] != source_candidates[0]:
                missing.append(role)
        source_case_prefix = str(source["source_request"].get("case_id", ""))
        source_def_pair = _basename_hash(source["source_map"], lambda name, _: name == f"{source_case_prefix}_Def.xml")
        if source_def_pair is None:
            source_def_pair = _basename_hash(source["source_map"], lambda name, _: name.endswith("_Def.xml") and "SPATIAL" not in name and "ANGULAR_RELEASE_DP" not in name)
        candidate_def_pair = _basename_hash(candidate_map, lambda name, _: name.endswith("_Def.xml") and "SPATIAL" in name)
        if source_def_pair is None or candidate_def_pair is None:
            missing.append("source/candidate Def paths")
            def_diff = {"status": "UNKNOWN_DEF_PATH"}
        else:
            def_diff = _xml_diff(Path(source_def_pair[0]), Path(candidate_def_pair[0]))
            if def_diff["status"] != "PASS_ONLY_DP_RESOLUTION_CHANGE":
                missing.append("Def XML non-resolution difference")
        scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
        source_scope = source["source_scope"]
        if scope.get("sentinel_id") != sentinel:
            missing.append("candidate scope sentinel")
        if scope.get("physical_case_id") != source["physical_case_id"]:
            missing.append("candidate scope source physical identity")
        if scope.get("three_spatial_grid_label") != grid:
            missing.append("candidate scope grid")
        status = "PASS_EXACT_SOURCE_DOMAIN" if not missing else "UNKNOWN_DOMAIN_EQUIVALENCE"
        return {
            "status": status, "sentinel_id": sentinel, "grid": grid,
            "source_physical_case_id": source["physical_case_id"], "candidate_case_id": request.get("case_id"),
            "candidate_attempt_id": request.get("attempt_id"), "candidate_physical_case_id": request.get("physical_case_id"),
            "authority": "source_current physical_case_id plus exact generation/control hash bridge",
            "missing": sorted(set(missing)), "source_identity": {k: v for k, v in source.items() if k not in {"source_request", "source_receipt", "source_map"}},
            "candidate_receipt": receipt_record, "candidate_request_sha256": candidate_case.get("producer_receipt_v6", {}).get("sha256"),
            "common_hashes": {"source_generated_xml": source["source_xml"]["sha256"], "source_generated_bi4": source["source_bi4_sha256"], "source_producer_receipt": source["source_receipt_sha256"], "source_def": source["source_def_sha256"]},
            "semantic_input_paths": semantic_paths,
            "def_xml_comparison": def_diff, "owner_proofs": {"rigid": "ROOT244", "continuous_owner": "ROOT252"},
            "no_label_fallback": True,
        }
    except (BuildFailure, OSError, ValueError, KeyError) as exc:
        return {"status": "UNKNOWN_DOMAIN_EQUIVALENCE", "sentinel_id": sentinel, "grid": grid, "missing": [str(exc)], "no_label_fallback": True}


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    v6_manifest, v6_record = _read_json(args.v6_manifest, "ROOT276 V6 manifest")
    if v6_manifest.get("schema") != V6_SCHEMA:
        raise BuildFailure("input manifest is not ROOT276 V6")
    cases = copy.deepcopy(v6_manifest.get("cases"))
    if not isinstance(cases, list) or len(cases) != 6:
        raise BuildFailure("V6 manifest must contain six cases")
    by_key = {(c.get("sentinel_id"), c.get("grid")): c for c in cases if isinstance(c, dict)}
    if len(by_key) != 6:
        raise BuildFailure("V6 cases are not unique sentinel/grid products")
    bridge_records: list[dict[str, Any]] = []
    for case in cases:
        sid, grid = str(case.get("sentinel_id")), str(case.get("grid"))
        if grid == "source_current":
            try:
                source_identity, _, _ = _source_identity(case)
                bridge = {"status": "PASS_DIRECT_PRODUCER_PHYSICAL_ID", "sentinel_id": sid, "grid": grid,
                          "authority": "actual producer physical_case_id plus closed XML/BI4/Def/receipt source roles",
                          "physical_case_id": source_identity["physical_case_id"], "no_label_fallback": True,
                          "source_identity": {key: value for key, value in source_identity.items() if key not in {"source_request", "source_receipt", "source_map"}}}
            except (BuildFailure, OSError, ValueError, KeyError) as exc:
                bridge = {"status": "UNKNOWN_SOURCE_CURRENT_IDENTITY", "sentinel_id": sid, "grid": grid,
                          "missing": [str(exc)], "no_label_fallback": True}
        else:
            bridge = _bridge(by_key[(sid, "source_current")], case, sid, grid)
            if bridge["status"] == "PASS_EXACT_SOURCE_DOMAIN":
                case["physical_case_id"] = bridge["source_physical_case_id"]
                case["producer_identity_v8"] = {"status": "PASS_DOMAIN_EQUIVALENCE", "physical_case_id": bridge["source_physical_case_id"], "source_authority": "ROOT244/ROOT252 plus exact source input bridge"}
                case["identity_status"] = "PASS_DOMAIN_EQUIVALENCE"
            else:
                case["producer_identity_v8"] = bridge
        case["domain_equivalence_v8"] = bridge
        bridge_records.append(bridge)
    owner_records = _owner_source_records(v6_manifest)
    eligible = sum(1 for item in bridge_records if str(item.get("status", "")).startswith("PASS"))
    manifest = copy.deepcopy(v6_manifest)
    manifest.update({"schema": MANIFEST_SCHEMA, "status": "PREPARED_ROOT276_F6_INITIAL_NATIVE_SUPPORT_V8_DOMAIN_BRIDGE",
                     "cases": cases, "domain_equivalence_v8": bridge_records,
                     "prior_v6_manifest": v6_record,
                     "identity_policy": {"physical_case_id_fallback": "FORBIDDEN", "domain_bridge": "exact source-current physical ID and immutable source/control hash evidence only", "unknown_case_no_payload": True, "failed_case_not_success": True},
                     "scientific_qualification": QUALIFICATION,
                     "builder_v8": {"path": str(Path(__file__).absolute()), "source_only": True},
                     "owner_source_records_v8": owner_records})
    manifest_path = args.manifest_output.expanduser().absolute()
    request_path = args.output_request.expanduser().absolute()
    _write_once(manifest_path, manifest)
    _, manifest_record = _record(manifest_path, "ROOT276 V8 manifest", parse_json=True)
    static: dict[str, dict[str, Any]] = {v6_record["path"]: v6_record, manifest_record["path"]: manifest_record}
    for path, label in ((V6_BUILDER, "V6 request builder"), (V6_WORKER, "V6 worker"), (V5_WORKER, "V5 worker"), (WORKER, "V8 worker"), (CONTRACT, "V8 contract")):
        _, rec = _record(path, label); static[rec["path"]] = rec
    # The bridge itself consumed these small source-domain records.  Keep
    # them in the runtime closure so a parent cannot run a worker against a
    # different XML/owner/proof while reusing this manifest.
    for bridge in bridge_records:
        comparison = bridge.get("def_xml_comparison") if isinstance(bridge, dict) else None
        if isinstance(comparison, dict):
            for key in ("source", "candidate"):
                rec = comparison.get(key)
                if isinstance(rec, dict) and isinstance(rec.get("path"), str):
                    static[rec["path"]] = rec
    for key in ("proof", "owner_proof", "owner_report", "prior_v4_failure_proof", "prior_v4_failure_request"):
        rec = v6_manifest.get(key)
        if isinstance(rec, dict) and isinstance(rec.get("path"), str):
            static[rec["path"]] = rec
    for rec in owner_records.values():
        if isinstance(rec, dict) and isinstance(rec.get("path"), str):
            static[rec["path"]] = rec
    for case in cases:
        for key in ("producer_receipt_v6", "xml"):
            rec = case.get(key)
            if isinstance(rec, dict) and isinstance(rec.get("path"), str):
                static[rec["path"]] = rec
        deferred = case.get("deferred", {})
        if isinstance(deferred, dict):
            # Keep payloads deferred; the V6 record is already stat-only and
            # concrete source SHA is used only where V6 had it.
            for item in deferred.values():
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    static[item["path"]] = item
    input_files = sorted(path for path in static if Path(path).suffix.lower() not in {".bi4", ".vtk", ".vtu", ".h5", ".hdf5"})
    request = {
        "schema": REQUEST_SCHEMA, "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F6_INITIAL_NATIVE_SUPPORT_ROOT276_V8_DOMAIN_BRIDGE" if eligible else "WAITING_EXACT_F6_DOMAIN_BRIDGE",
        "kind": "cpu", "cpu_task_kind": "audit", "request_id": "f6-initial-native-support-root276-v8-domain-bridge-001",
        "family_id": "F6", "sentinel_ids": ["F6-S1", "F6-S2"], "case_id": "F6_INITIAL_NATIVE_SUPPORT_AUDIT_ROOT276_V8", "attempt_id": "f6-initial-native-support-audit-root276-v8-001",
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY),
        # The worker has a mutually-exclusive --self-test/--run CLI.  Keep
        # --run explicit in the parent command; omitting it makes the
        # otherwise valid request fail before the source guard is entered.
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", "-B", str(WORKER), "--run", "--manifest", manifest_record["path"], "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f6_initial_native_support_audit_v8.json"],
        "input_files": input_files, "input_sha256": {p: static[p]["sha256"] for p in input_files}, "input_records": {p: static[p] for p in input_files}, "manifest": manifest_record,
        "deferred_input_files": sorted({item["path"] for c in cases if isinstance(c, dict) for item in (c.get("deferred", {}) or {}).values() if isinstance(item, dict) and isinstance(item.get("path"), str)}),
        "deferred_input_records": [item for c in cases if isinstance(c, dict) for item in (c.get("deferred", {}) or {}).values() if isinstance(item, dict)],
        "deferred_input_policy": {"parent_after_reservation_first_sha_and_stat": True, "worker_post_sha_and_stat": True, "known_sha_checked_when_present": True, "source_replace_or_stat_change": "FAIL", "parent_v8_deferred_hash": False},
        "domain_equivalence_v8": bridge_records, "runtime_closure": {"v6_builder": str(V6_BUILDER), "v6_worker": str(V6_WORKER), "v5_worker": str(V5_WORKER), "v8_worker": str(WORKER), "contract": str(CONTRACT)},
        "resources": {"cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 2 * 1024**3, "external_storage_max_bytes": 1024 * 1024**3, "home_storage_max_bytes": 128 * 1024**2, "log_max_bytes": 1024 * 1024, "scratch_max_bytes": 1024 * 1024**3, "parent_guard_required": True},
        "storage_scope": {"native_payload_read": "frame-0 BI4 and Fluid/Bound VTK only for PASS bridge cases", "full_native_tree_scan": False, "hdf5_read": False, "solver_launch": False},
        "scientific_qualification": QUALIFICATION, "launch_disabled": eligible == 0, "execution_allowed": eligible > 0, "solver_started": False, "native_payload_read": False, "hdf5_read": False, "ledger_mutation": False,
        "source_binding": {"root244_rigid_proof": owner_records.get("proof"), "root252_owner_proof": owner_records.get("owner_proof"), "domain_bridge": "exact semantic source-role path/SHA and XML/control evidence; no case-label fallback", "owner_mass_kg": 4851.988676250775, "native_sample_mass_not_continuous": True, "qualification": QUALIFICATION},
    }
    request["sha256"] = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    _write_once(request_path, request)
    return manifest, request


def _self_test() -> None:
    # Exercise the strict XML policy without touching production inputs.
    with tempfile.TemporaryDirectory(prefix="root276-v8-") as td:
        root = Path(td); source = root / "source_Def.xml"; candidate = root / "candidate_Def.xml"; bad = root / "bad_Def.xml"
        base = '<case><casedef><x/><y/><geometry><definition dp="0.025"><z/></definition></geometry></casedef></case>'
        source.write_text(base, encoding="utf-8")
        candidate.write_text(base.replace('dp="0.025"', 'dp="0.03125"'), encoding="utf-8")
        bad.write_text(base.replace('<z/>', '<z a="changed"/>'), encoding="utf-8")
        # The production path is intentionally strict: this fixture has the
        # exact approved geometry/@dp path, while the second mutation must be
        # rejected as a non-resolution change.
        assert _xml_diff(source, candidate)["status"] == "PASS_ONLY_DP_RESOLUTION_CHANGE"
        assert _xml_diff(source, bad)["status"] == "UNKNOWN_DEF_NON_RESOLUTION_CHANGE"
        # A role digest cannot be smuggled in under a different basename.
        source_identity = {
            "source_xml": {"path": "/source/generated.xml", "sha256": "a" * 64},
            "source_bi4_path": "/source/generated.bi4", "source_bi4_sha256": "b" * 64,
            "source_receipt_path": "/source/execution-receipt.json", "source_receipt_sha256": "c" * 64,
            "source_def_path": "/source/source_Def.xml", "source_def_sha256": "d" * 64,
        }
        candidate_map = {
            "/attempt/generated.xml": "a" * 64, "/attempt/generated.bi4": "b" * 64,
            "/attempt/execution-receipt.json": "c" * 64, "/attempt/source_Def.xml": "d" * 64,
        }
        assert len(_semantic_input_join(source_identity, candidate_map)) == 4
        wrong = dict(candidate_map); wrong["/attempt/other.xml"] = wrong.pop("/attempt/generated.xml")
        try:
            _semantic_input_join(source_identity, wrong)
        except BuildFailure:
            pass
        else:
            raise AssertionError("semantic source-role basename mismatch was accepted")
        # Exercise the actual --run entry with an UNKNOWN/no-case manifest.
        manifest = root / "empty-manifest.json"; output = root / "empty-output.json"; attempt = root / "attempt"
        manifest.write_text(json.dumps({"schema": MANIFEST_SCHEMA, "cases": []}), encoding="utf-8")
        completed = subprocess.run([str(PYTHON), "-B", str(WORKER), "--run", "--manifest", str(manifest), "--attempt-root", str(attempt), "--output", str(output)], capture_output=True, text=True, check=False)
        assert completed.returncode == 2, completed.stdout + completed.stderr
        assert output.is_file(), completed.stdout + completed.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["case_counts"] == {"PASS": 0, "UNKNOWN": 0, "FAILED": 0}
    print("PASS_F6_INITIAL_NATIVE_SUPPORT_REQUEST_V8_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--self-test", action="store_true"); group.add_argument("--build", action="store_true")
    parser.add_argument("--v6-manifest", type=Path); parser.add_argument("--manifest-output", type=Path); parser.add_argument("--output-request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if args.v6_manifest is None or args.manifest_output is None or args.output_request is None:
        parser.error("--build requires --v6-manifest, --manifest-output, and --output-request")
    try:
        _, request = build(args)
    except Exception as exc:
        print(f"FAILED_F6_INITIAL_NATIVE_SUPPORT_REQUEST_V8: {exc}")
        return 2
    print(json.dumps({"status": request["status"], "manifest": str(args.manifest_output.absolute()), "request": str(args.output_request.absolute()), "payload_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
