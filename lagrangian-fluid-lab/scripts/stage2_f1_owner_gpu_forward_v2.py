#!/usr/bin/env python3
"""Bind F1 owner solver requests to the v3 attempt-tree copy worker.

This forward builder preserves the c3c8ee225 request builder and its
historical paths.  It creates fresh v3 CPU copy plans and fresh external-v5
solver requests.  The CPU request is bound to an explicit attempt ID; every
BI4/XML destination is then derived below that attempt's ``solver-inputs``
directory.  The solver request cannot accidentally point at the old
worktree-side overlay directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-02"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REQUEST_DIR = CAMPAIGN_ROOT / "stage2/requests/stage2-f1-s1-owner-gpu-v6"
V2_DIR = CAMPAIGN_ROOT / "stage2/requests/stage2-f1-s1-owner-matched-solver-v2"
QA_PROOF = CAMPAIGN_ROOT / "stage2/checkpoints/F1_TWO_OWNER_RUNGS_INITIAL_NATIVE_QA_V2_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
LEDGER = DATA_ROOT / "runtime/resource-ledger.json"
EXTERNAL_ROOT = Path("/var/tmp/ds02-stage2")
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
SOLVER = OFFICIAL_ROOT / "DualSPHysics5.4_linux64"
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DISPATCH_V8 = SCRIPT_DIR / "ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = SCRIPT_DIR / "ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = SCRIPT_DIR / "ds_data02_runtime_v8.py"
RUNTIME_V6 = SCRIPT_DIR / "ds_data02_runtime_v6.py"
RUNTIME_V2 = SCRIPT_DIR / "ds_data02_runtime_v2.py"
MATERIALIZER_V3 = SCRIPT_DIR / "stage2_f1_owner_bi4_materialize_v3.py"
OLD_BUILDER_PATH = SCRIPT_DIR / "stage2_f1_owner_gpu_forward_v1.py"
SCHEMA = "ds02.request.v1"
EXTERNAL_SCHEMA = "ds02.stage2.external-solver-request.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PROTECTED_GPU6 = {
    "index": 6, "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689, "action": "do_not_touch",
}


def _load_old_builder():
    spec = importlib.util.spec_from_file_location("stage2_f1_owner_gpu_forward_v1", OLD_BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import consumed forward builder: {OLD_BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = _load_old_builder()


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return OLD.sha256_file(path)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return OLD.canonical_sha(value)


def load_json(path: Path) -> dict[str, Any]:
    return OLD.load_json(path)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT_DIR.parent.parent,
                          check=True, capture_output=True, text=True).stdout.strip()


def _plan(output: Path, rung: str, v2_files: list[Path], proof: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    source_path = Path(str(proof["native_source"]["path"])).expanduser().resolve()
    source_sha = str(proof["native_source"]["sha256"])
    source_bytes = int(proof["native_source"]["bytes"])
    destinations: list[dict[str, Any]] = []
    for v2_path in sorted(v2_files):
        value = load_json(v2_path)
        mode = "same_cfl" if "same_cfl" in v2_path.name else "half_cfl"
        material = value.get("materialization", {})
        prefix = Path(str(material.get("overlay_prefix", ""))).expanduser().resolve()
        xml = Path(str(material.get("overlay_xml", ""))).expanduser().resolve()
        if not prefix.name or not xml.is_file():
            raise BuildError(f"F1 {rung} overlay XML is unavailable: {xml}")
        destinations.append({
            "mode": mode,
            "prefix_relative": f"solver-inputs/{mode}/{prefix.name}",
            "source_xml": {"path": str(xml), "sha256": sha256_file(xml), "bytes": xml.stat().st_size},
            "consumed_request": str(v2_path.resolve()),
            "consumed_request_sha256": sha256_file(v2_path),
        })
    plan_value = {
        "schema": "ds02.stage2.f1.owner-bi4-copy-materialization.v3",
        "status": "READY_PARENT_CPU_V8_COPY_AFTER_RESERVATION",
        "family_id": "F1", "sentinel_id": "F1-S1", "rung": rung,
        "source_bi4": {"path": str(source_path), "sha256": source_sha, "bytes": source_bytes,
                       "source_role": "actual QA native BI4; immutable producer"},
        "destinations": destinations,
        "copy_policy": {
            "mode": "byte_for_byte_regular_copy", "hardlink_forbidden": True,
            "source_pre_post_stat_all_fields_equal": True,
            "destination_must_have_distinct_inode": True,
            "all_destinations_relative_to_attempt_root": True,
            "partial_outputs_preserved_and_charged_on_failure": True,
            "receipt_overwrite_forbidden": True,
        },
        "qa_proof": {"path": str(QA_PROOF.resolve()), "sha256": sha256_file(QA_PROOF),
                     "rung_source_sha256": source_sha},
    }
    plan_path = output / "materialization" / f"{rung.lower()}_copy_plan_v3.json"
    if plan_path.exists():
        raise BuildError(f"refusing existing plan: {plan_path}")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan_value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan_path, plan_value


def _copy_attempt_binding(rung: str, attempt_id: str) -> tuple[str, str, Path]:
    if not SAFE_ID.fullmatch(attempt_id):
        raise BuildError(f"unsafe copy attempt ID: {attempt_id}")
    case_id = f"F1_S1_OWNER_{rung}_BI4_COPY_V3"
    attempt_root = DATA_ROOT / "families" / "F1" / case_id / attempt_id
    return case_id, attempt_id, attempt_root


def _copy_request(output_dir: Path, rung: str, plan_path: Path, plan: Mapping[str, Any], launch_commit: str,
                  copy_attempt_id: str) -> tuple[dict[str, Any], Path]:
    case_id, attempt_id, attempt_root = _copy_attempt_binding(rung, copy_attempt_id)
    source = Path(str(plan["source_bi4"]["path"])).expanduser().resolve()
    input_paths = [MATERIALIZER_V3, plan_path, DISPATCH_V8, STRICT_V8, RUNTIME_V8,
                   RUNTIME_V6, source, QA_PROOF]
    input_paths.extend(Path(str(item["source_xml"]["path"])) for item in plan["destinations"])
    input_files: list[str] = []
    input_hashes: dict[str, str] = {}
    for path in input_paths:
        path = path.expanduser().resolve()
        if path not in [Path(p) for p in input_files]:
            input_files.append(str(path))
        input_hashes[str(path)] = str(plan["source_bi4"]["sha256"]) if path == source else sha256_file(path)
    estimated = int(plan["source_bi4"]["bytes"]) * 2
    estimated += sum(int(item["source_xml"]["bytes"]) for item in plan["destinations"])
    estimated += 64 * 1024**2
    request = {
        "schema": SCHEMA, "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": case_id, "attempt_id": attempt_id, "launch_commit": launch_commit,
        "command": [str(VENV_PYTHON), str(MATERIALIZER_V3), "--plan", str(plan_path.resolve()),
                     "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/materialization-receipt.json"],
        "cwd": str(SCRIPT_DIR.parent.parent), "worktree_root": str(SCRIPT_DIR.parent.parent),
        "input_files": input_files, "input_hashes": input_hashes,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600,
        "estimated_input_read_bytes": int(plan["source_bi4"]["bytes"]) +
        sum(int(item["source_xml"]["bytes"]) for item in plan["destinations"]),
        "estimated_storage_bytes": estimated, "estimated_peak_memory_bytes": 1024**3,
        "estimated_cpu_core_hours": 0.5,
        "execution_allowed": True, "launch_disabled": False,
        "solver_started": False, "solver_launch": False, "gencase_launch": False,
        "hdf5_read": False, "bi4_read": True,
        "output": "v3 attempt-tree BI4/XML copy and materialization receipt only",
        "resource_guard": {
            "owner": "stage2-reference-preparation", "runner": str(DISPATCH_V8),
            "strict_guard": str(STRICT_V8), "runtime": str(RUNTIME_V8),
            "runtime_v6_dependency": str(RUNTIME_V6), "launch_commit": launch_commit,
            "gpu": "none", "solver_launch": "forbidden",
            "source_output_protection": "all copies and receipt remain under this attempt tree",
            "partial_failure_charge": True,
        },
        "parent_resource_binding": OLD.parent_binding(),
        "source_binding": {
            "copy_plan": str(plan_path.resolve()), "copy_plan_sha256": sha256_file(plan_path),
            "source_sha256": plan["source_bi4"]["sha256"], "source_bytes": plan["source_bi4"]["bytes"],
            "attempt_root": str(attempt_root), "all_destinations_inside_attempt_root": True,
            "hardlink_forbidden": True, "receipt_overwrite_forbidden": True,
        },
        "qualification": dict(UNKNOWN),
    }
    out = output_dir / "materialization" / f"f1_s1_owner_{rung.lower()}_bi4_copy_v3.json"
    return request, out


def _replace_string(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_string(item, old, new) for item in value]
    if isinstance(value, dict):
        # Paths occur both as values (argv/input_files) and as keys
        # (input_sha256/input_content_scope).  Rebinding values only leaves a
        # stale source key behind, so recurse over keys as well as values.
        rebound: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = _replace_string(key, old, new) if isinstance(key, str) else key
            rebound[new_key] = _replace_string(item, old, new)
        return rebound
    return value


def _normalise_external_input_bindings(base: dict[str, Any], *, source: str,
                                       old_materializer: str, materializer: Path,
                                       old_prefix: str, new_bi4: Path, new_xml: Path,
                                       source_sha: str, xml_sha: str) -> dict[str, Any]:
    """Close the v5 actionable-input maps after path rebinding.

    The consumed v2/v6 request carries several historical maps.  Keeping a
    key that is not in ``input_files`` makes the strict v5 validator reject
    the request; keeping the old materializer digest would also bind the
    request to a file that is no longer executed.  This helper deliberately
    reconstructs both maps from the final actionable file list.  The future
    BI4/XML copies are represented by their already-bound plan digests and
    are never opened by this builder.
    """
    source = str(Path(source).expanduser().resolve())
    old_materializer = str(Path(old_materializer).expanduser().resolve())
    old_overlay_bi4 = str(Path(old_prefix + ".bi4").expanduser().resolve())
    old_overlay_xml = str(Path(old_prefix + ".xml").expanduser().resolve())
    new_bi4 = new_bi4.expanduser().resolve()
    new_xml = new_xml.expanduser().resolve()
    materializer = materializer.expanduser().resolve()
    new_bi4_key = str(new_bi4)
    new_xml_key = str(new_xml)
    materializer_key = str(materializer)

    final_paths: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for raw in base.get("input_files", []):
        path = str(Path(str(raw)).expanduser().resolve())
        # The producer BI4 is retained only in materialization metadata.  Any
        # old overlay BI4 is replaced by the copy under the new attempt root.
        if path in {source, old_overlay_bi4, old_overlay_xml, old_materializer}:
            dropped.append(path)
            continue
        if path.lower().endswith(".bi4") and path != new_bi4_key:
            dropped.append(path)
            continue
        if path not in seen:
            seen.add(path)
            final_paths.append(path)

    # The copied XML/BI4 and the actual v3 materializer are required bindings,
    # even if a predecessor omitted one of them from its input_files list.
    for required in (new_bi4_key, new_xml_key, materializer_key):
        if required not in seen:
            seen.add(required)
            final_paths.append(required)

    old_scopes = base.get("input_content_scope", {})
    if not isinstance(old_scopes, Mapping):
        old_scopes = {}
    hashes: dict[str, str] = {}
    scopes: dict[str, str] = {}
    for path_value in final_paths:
        path = Path(path_value)
        if path_value == new_bi4_key:
            # This is an expected post-copy digest from the QA proof; do not
            # read the future copy here.
            digest = source_sha
            scope = "post_reservation_hash"
        elif path_value == new_xml_key:
            # The tiny source XML was hashed while building the copy plan; the
            # attempt-tree destination is not present until the CPU copy task.
            digest = xml_sha
            scope = "post_reservation_hash"
        elif path_value == materializer_key:
            digest = sha256_file(materializer)
            scope = "post_reservation_hash"
        else:
            if not path.is_file() or path.is_symlink():
                raise BuildError(f"actionable external input is unavailable: {path}")
            # Existing small bindings are re-hashed from their actual source;
            # stale predecessor values are not carried into the v3 request.
            digest = sha256_file(path)
            scope = str(old_scopes.get(path_value, "post_reservation_hash"))
        hashes[path_value] = str(digest)
        scopes[path_value] = scope

    base["input_files"] = final_paths
    base["input_sha256"] = hashes
    base["input_content_scope"] = scopes
    base["input_binding_audit"] = {
        "schema": "ds02.stage2.f1.actionable-input-binding-audit.v3",
        "actionable_files_only": True,
        "input_sha256_keys_equal_input_files": list(hashes) == final_paths,
        "input_content_scope_keys_equal_input_files": list(scopes) == final_paths,
        "source_bi4_excluded_from_actionable_inputs": source not in final_paths,
        "stale_paths_removed": sorted(set(dropped)),
        "materializer": {"path": materializer_key, "sha256": hashes[materializer_key]},
        "deferred_copy_bindings": {
            new_bi4_key: {"sha256": source_sha, "content_scope": "post_reservation_hash",
                          "payload_read_by_builder": False},
            new_xml_key: {"sha256": xml_sha, "content_scope": "post_reservation_hash",
                          "payload_read_by_builder": False},
        },
    }
    return base


def _solver_request(v2: dict[str, Any], v2_path: Path, proof: Mapping[str, Any], rung: str, mode: str,
                    plan_path: Path, plan: Mapping[str, Any], copy_root: Path,
                    launch_commit: str) -> dict[str, Any]:
    # Reuse the consumed builder's schema checks and v5 external closure, then
    # replace only the materialized input prefix with the guarded attempt path.
    base = OLD._prepare_base_v6(v2, proof, rung, mode, dict(plan), plan_path, launch_commit)
    old_prefix = str(Path(str(v2["materialization"]["overlay_prefix"])).expanduser().resolve())
    destination = next(item for item in plan["destinations"] if item["mode"] == mode)
    new_prefix = (copy_root / destination["prefix_relative"]).resolve()
    base["materialization"]["copy_plan"] = str(plan_path.resolve())
    base["materialization"]["copy_plan_sha256"] = sha256_file(plan_path)
    base = OLD._externalize(base, rung, mode, launch_commit)
    base = _replace_string(base, old_prefix, str(new_prefix))
    old_materializer = str(OLD.MATERIALIZER.expanduser().resolve())
    base = _replace_string(base, old_materializer, str(MATERIALIZER_V3.expanduser().resolve()))
    new_xml = Path(str(new_prefix) + ".xml")
    new_bi4 = Path(str(new_prefix) + ".bi4")
    base["schema"] = EXTERNAL_SCHEMA
    base["case_id"] = f"f1-s1-owner-{rung.lower()}-{mode}-savedt-nvme-v2"
    base["attempt_id"] = f"f1-s1-owner-{rung.lower()}-{mode}-savedt-v5-copy-v3-root-001"
    base["cwd"] = str(new_prefix.parent)
    base["command"] = [str(SOLVER), "-gpu:0", str(new_prefix), "{output_root}/solver_output",
                        "-tmax:1.600082994772861", "-tout:0.005"]
    base.pop("output_root", None)
    output_root = EXTERNAL_ROOT / "F1" / f"F1_S1_OWNER_{rung}_{mode.upper()}_NVME_SAVEDT_V2" / base["attempt_id"]
    base["storage_scope"]["output_root"] = str(output_root)
    base["materialization"].update({
        "mode": "regular_copy_prepared_by_parent_v8_v3",
        "copy_attempt_root": str(copy_root),
        "copy_receipt": str(copy_root / "materialization-receipt.json"),
        "overlay_prefix": str(new_prefix), "overlay_bi4": str(new_bi4), "overlay_xml": str(new_xml),
        "all_destinations_inside_copy_attempt_root": True,
        "copy_receipt_required_before_v5": True,
    })
    base["source_provenance"].update({
        "bi4_copy_required_before_external_v5": True,
        "original_bi4_excluded_from_post_copy_solver_inputs": True,
        "copy_receipt_required_before_v5": True,
        "copy_attempt_root": str(copy_root),
        "solver_prefix_is_copy_attempt_child": True,
    })
    base["preconditions"] = list(base.get("preconditions", [])) + [{
        "required": "PASS_COPY_SOURCE_BOUND", "copy_receipt": str(copy_root / "materialization-receipt.json"),
        "copy_attempt_root": str(copy_root), "overlay_bi4": str(new_bi4), "overlay_xml": str(new_xml),
        "must_be_inside_attempt_root": True,
    }]
    # Rebuild the strict v5 actionable-input maps from the final paths.  This
    # removes stale v2 materializer/source keys and records the actual v3
    # materializer digest while leaving the future copy payload unopened.
    source = str(plan["source_bi4"]["path"])
    base = _normalise_external_input_bindings(
        base, source=source, old_materializer=old_materializer,
        materializer=MATERIALIZER_V3, old_prefix=old_prefix,
        new_bi4=new_bi4, new_xml=new_xml,
        source_sha=str(plan["source_bi4"]["sha256"]),
        xml_sha=str(destination["source_xml"]["sha256"]),
    )
    base["launch_commit"] = launch_commit
    base["forward_of"] = {
        "consumed_request": str(v2_path.resolve()), "consumed_request_sha256": sha256_file(v2_path),
        "copy_builder": str(OLD_BUILDER_PATH.resolve()),
        "reason": "v3 attempt-tree copy; no unaccounted worktree-side BI4/XML destination",
    }
    base["sha256"] = canonical_sha(base)
    return base


def build(output_dir: Path, *, copy_attempts: Mapping[str, str], launch_commit: str | None = None) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    launch_commit = launch_commit or git_commit()
    for rung in ("DP005", "DP0025"):
        if rung not in copy_attempts:
            raise BuildError(f"explicit copy attempt ID required for {rung}")
    cases = OLD.proof_cases()
    OLD.parent_binding()
    manifest: dict[str, Any] = {
        "schema": "ds02.stage2.f1.owner-gpu-forward-manifest.v2",
        "status": "READY_FOR_PARENT_REVIEW", "launch_commit": launch_commit,
        "source_qa_proof": str(OLD.QA_PROOF), "external_runner": str(OLD.EXTERNAL_V5),
        "copy_worker": str(MATERIALIZER_V3), "files": [], "rungs": {},
    }
    for rung in ("DP005", "DP0025"):
        v2_files = sorted(V2_DIR.glob(f"f1_s1_owner_{rung.lower()}_*_savedt_dense_v1.json"))
        if len(v2_files) != 2:
            raise BuildError(f"expected two consumed v2 requests for {rung}")
        sample = load_json(v2_files[0])
        source = Path(str(sample["materialization"]["source_bi4"])).expanduser().resolve()
        proof = cases.get(str(source))
        if proof is None:
            raise BuildError(f"actual QA proof missing for {source}")
        plan_path, plan = _plan(output_dir, rung, v2_files, proof)
        copy_request, copy_path = _copy_request(output_dir, rung, plan_path, plan, launch_commit, copy_attempts[rung])
        if copy_path.exists():
            raise BuildError(f"refusing existing copy request: {copy_path}")
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_text(json.dumps(copy_request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest["files"].extend([str(plan_path), str(copy_path)])
        _, _, copy_root = _copy_attempt_binding(rung, copy_attempts[rung])
        solver_files: list[str] = []
        for v2_path in v2_files:
            mode = "same_cfl" if "same_cfl" in v2_path.name else "half_cfl"
            request = _solver_request(load_json(v2_path), v2_path, proof, rung, mode,
                                      plan_path, plan, copy_root, launch_commit)
            target = output_dir / f"f1_s1_owner_{rung.lower()}_{mode}_savedt_external_v5_v2.json"
            if target.exists():
                raise BuildError(f"refusing existing solver request: {target}")
            target.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            solver_files.append(str(target))
            manifest["files"].append(str(target))
        manifest["rungs"][rung] = {
            "copy_attempt_id": copy_attempts[rung], "copy_attempt_root": str(copy_root),
            "copy_plan": str(plan_path), "copy_request": str(copy_path),
            "solver_requests": solver_files,
            "external_product_reserved_bytes": (20 if rung == "DP005" else 132) * 1024**3,
            "copy_storage_reserved_bytes": copy_request["estimated_storage_bytes"],
            "serial_solver_policy": True,
        }
    manifest["files"] = [str(Path(path).resolve()) for path in manifest["files"]]
    manifest["request_count"] = 4
    manifest["copy_request_count"] = 2
    manifest["source_integrity"] = "v8 copy pre/post full source stat+SHA; v5 hashes only new attempt-tree copy after reservation"
    manifest["no_unaccounted_side_effect"] = True
    manifest["sha256"] = canonical_sha(manifest)
    manifest_path = output_dir / "f1_s1_owner_gpu_forward_manifest_v2.json"
    if manifest_path.exists():
        raise BuildError(f"refusing existing manifest: {manifest_path}")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REQUEST_DIR)
    parser.add_argument("--copy-attempt-dp005", required=True)
    parser.add_argument("--copy-attempt-dp0025", required=True)
    parser.add_argument("--launch-commit")
    args = parser.parse_args(argv)
    try:
        result = build(args.output_dir, copy_attempts={"DP005": args.copy_attempt_dp005,
                                                        "DP0025": args.copy_attempt_dp0025},
                       launch_commit=args.launch_commit)
    except (BuildError, OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "request_count": result["request_count"],
                      "copy_request_count": result["copy_request_count"],
                      "manifest": str((args.output_dir / "f1_s1_owner_gpu_forward_manifest_v2.json").resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
