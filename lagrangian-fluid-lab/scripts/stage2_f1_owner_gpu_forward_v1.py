#!/usr/bin/env python3
"""Forward F1 owner solver requests to the verified external v5 GPU entry.

The consumed F1 owner-matched requests point at the CPU-only v8 runner and
therefore cannot execute a ``qualification`` solver request.  This additive
builder keeps those JSON files immutable and emits two predecessor CPU-v8
copy requests plus four parent-ready solver requests:

* both rungs use the existing external v5 runner, whose reservation happens
  before the expensive input-content hash;
* DP005 and DP0025 both use serial NVMe output namespaces, with only a small
  Home receipt reservation.

The CPU predecessor copies the QA-proven BI4 after reservation.  A hard link
is intentionally forbidden because it mutates the producer inode ctime and
link count.  This module never reads a BI4; it takes the content SHA/size
from the actual QA proof and leaves the parent v8 copy worker and external v5
runner to hash the new regular copy after their respective reservations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-02"
REQUEST_DIR = CAMPAIGN_ROOT / "stage2" / "requests" / "stage2-f1-s1-owner-gpu-v5"
V2_DIR = CAMPAIGN_ROOT / "stage2" / "requests" / "stage2-f1-s1-owner-matched-solver-v2"
QA_PROOF = CAMPAIGN_ROOT / "stage2" / "checkpoints" / "F1_TWO_OWNER_RUNGS_INITIAL_NATIVE_QA_V2_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
DATA_ROOT = LEDGER.parent.parent
EXTERNAL_ROOT = Path("/var/tmp/ds02-stage2")
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
SOLVER = OFFICIAL_ROOT / "DualSPHysics5.4_linux64"
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

DISPATCH_V8 = SCRIPT_DIR / "ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = SCRIPT_DIR / "ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = SCRIPT_DIR / "ds_data02_runtime_v8.py"
DISPATCH_V6 = SCRIPT_DIR / "ds_data02_stage2_dispatch_v6.py"
STRICT_V6 = SCRIPT_DIR / "ds_data02_strict_dispatch_v6.py"
RUNTIME_V6 = SCRIPT_DIR / "ds_data02_runtime_v6.py"
RUNTIME_V2 = SCRIPT_DIR / "ds_data02_runtime_v2.py"
EXTERNAL_V1 = SCRIPT_DIR / "ds_data02_stage2_external_solver_v1.py"
EXTERNAL_V4 = SCRIPT_DIR / "ds_data02_stage2_external_solver_v4.py"
EXTERNAL_V5 = SCRIPT_DIR / "ds_data02_stage2_external_solver_v5.py"
EXTERNAL_V6 = SCRIPT_DIR / "ds_data02_stage2_external_solver_v6.py"
MATERIALIZER = SCRIPT_DIR / "stage2_f1_owner_bi4_materialize_v2.py"

SCHEMA = "ds02.request.v1"
EXTERNAL_SCHEMA = "ds02.stage2.external-solver-request.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PROTECTED_GPU6 = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {k: v for k, v in value.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildError(f"JSON object required: {path}")
    return value


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT_DIR.parent.parent,
                              check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError(f"cannot bind launch commit: {exc}") from exc


def parent_binding() -> dict[str, Any]:
    ledger = load_json(LEDGER)
    limits = ledger.get("limits", {})
    required = ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts",
                "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")
    if any(k not in limits for k in required):
        raise BuildError("parent ledger is missing live limits")
    return {
        "ledger_path": str(LEDGER), "data_root": str(DATA_ROOT),
        "campaign_id": ledger.get("campaign_id"), "deadline_utc": ledger.get("deadline_utc"),
        "ledger_reset": False, "no_new_data_root": True,
        "limits": {k: limits[k] for k in required},
    }


def proof_cases() -> dict[str, dict[str, Any]]:
    proof = load_json(QA_PROOF)
    if proof.get("status") != "PASS_ACTUAL_TWO_F1_GENCASE_NATIVE_INITIAL_FIELDS_AND_SAMPLE_MASS":
        raise BuildError("F1 QA proof is not the actual two-rung PASS")
    if proof.get("solver_started") is not False or proof.get("H5_BI4_read_by_root") is not False:
        raise BuildError("F1 QA proof is outside the no-solver/no-root-BI4-read scope")
    result: dict[str, dict[str, Any]] = {}
    for item in proof.get("cases", []):
        source = item.get("native_source", {})
        path = str(source.get("path", ""))
        if not path or len(str(source.get("sha256", ""))) != 64:
            raise BuildError("F1 QA proof lacks a complete native source digest")
        result[path] = dict(item)
    if len(result) != 2:
        raise BuildError("F1 QA proof does not contain exactly two owner rungs")
    return result


def _existing_hash(path: Path, expected: str | None = None) -> str:
    path = path.expanduser().resolve()
    if expected is not None:
        if len(expected) != 64:
            raise BuildError(f"invalid expected digest for {path}")
        return expected
    if not path.is_file():
        raise BuildError(f"bound input is missing: {path}")
    return sha256_file(path)


def _add_hash(request: dict[str, Any], path: Path, digest: str) -> None:
    p = str(path.expanduser().resolve())
    request.setdefault("input_files", [])
    request.setdefault("input_hashes", {})
    if p not in request["input_files"]:
        request["input_files"].append(p)
    request["input_hashes"][p] = digest


def _replace_root(path_value: str) -> str:
    """Keep source/reference paths from the consumed request unchanged."""
    return str(Path(path_value).expanduser().resolve())


def _materialization_plan(v2: dict[str, Any], rung: str, proof: dict[str, Any], out: Path) -> dict[str, Any]:
    material = v2.get("materialization")
    if not isinstance(material, Mapping):
        raise BuildError("consumed request has no materialization declaration")
    source = Path(str(material.get("source_bi4", ""))).expanduser().resolve()
    expected = str(proof["native_source"]["sha256"])
    expected_bytes = int(proof["native_source"]["bytes"])
    if source != Path(str(proof["native_source"]["path"])).expanduser().resolve():
        raise BuildError(f"{rung} request source differs from actual QA source")
    prefix = Path(str(material.get("overlay_prefix", ""))).expanduser().resolve()
    destinations = []
    for mode in ("same_cfl", "half_cfl"):
        mode_prefix = prefix.parent.parent / mode / prefix.name.replace("same_cfl", mode)
        # The consumed request has the exact mode-specific path; derive it from
        # each v2 input rather than guessing a filename for the predecessor.
        mode_file = V2_DIR / f"f1_s1_owner_{rung.lower()}_{mode}_savedt_dense_v1.json"
        md = load_json(mode_file)
        exact = Path(str(md["materialization"]["overlay_prefix"])).expanduser().resolve()
        destinations.append({
            "mode": mode,
            "overlay_prefix": str(exact),
            "path": str(exact) + ".bi4",
        })
    plan = {
        "schema": "ds02.stage2.f1.owner-bi4-copy-materialization.v2",
        "status": "READY_PARENT_CPU_V8_COPY_AFTER_RESERVATION",
        "family_id": "F1", "sentinel_id": "F1-S1", "rung": rung,
        "source_bi4": {"path": str(source), "sha256": expected, "bytes": expected_bytes,
                       "source_role": "actual QA native BI4; immutable producer"},
        "destinations": destinations,
        "copy_policy": {
            "mode": "byte_for_byte_regular_copy",
            "hardlink_forbidden": True,
            "source_pre_post_stat_all_fields_equal": True,
            "destination_must_have_distinct_inode": True,
            "parent_reservation_includes_copy_bytes": expected_bytes,
        },
        "qa_proof": {"path": str(QA_PROOF.resolve()), "sha256": sha256_file(QA_PROOF),
                     "rung_source_sha256": expected},
        "solver_dependency": "parent must complete this receipt before invoking strict v6 GPU request",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise BuildError(f"refusing existing plan: {out}")
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def _cpu_copy_request(rung: str, plan_path: Path, plan: dict[str, Any], launch_commit: str) -> dict[str, Any]:
    source = Path(str(plan["source_bi4"]["path"])).expanduser().resolve()
    inputs = [MATERIALIZER, plan_path, DISPATCH_V8, STRICT_V8, RUNTIME_V8, RUNTIME_V6, source, QA_PROOF]
    hashes = {}
    for path in inputs:
        expected = str(plan["source_bi4"]["sha256"]) if path == source else None
        hashes[str(path.resolve())] = _existing_hash(path, expected)
    attempt = f"f1-s1-owner-{rung.lower()}-bi4-copy-v2-001"
    return {
        "schema": SCHEMA, "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": f"F1_S1_OWNER_{rung}_BI4_COPY",
        "attempt_id": attempt, "launch_commit": launch_commit,
        "command": [str(VENV_PYTHON), str(MATERIALIZER), "--plan", str(plan_path.resolve()),
                     "--output", "{attempt_root}/materialization-receipt.json"],
        "cwd": str(SCRIPT_DIR), "worktree_root": str(SCRIPT_DIR.parent.parent),
        "input_files": [str(p.resolve()) for p in inputs], "input_hashes": hashes,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "estimated_input_read_bytes": int(plan["source_bi4"]["bytes"]),
        # One CPU predecessor materializes both same-CFL and half-CFL copies.
        # Reserve both regular-copy destinations; a single-source read estimate
        # remains separate from the destination storage reservation.
        "estimated_storage_bytes": int(plan["source_bi4"]["bytes"]) * len(plan["destinations"]) + 64 * 1024**2,
        "estimated_peak_memory_bytes": 512 * 1024**2,
        "estimated_cpu_core_hours": 0.25,
        "execution_allowed": True, "launch_disabled": False,
        "solver_started": False, "solver_launch": False, "gencase_launch": False,
        "hdf5_read": False, "bi4_read": True,
        "output": "copy materialization receipt only",
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH_V8), "strict_guard": str(STRICT_V8),
            "runtime": str(RUNTIME_V8), "runtime_v6_dependency": str(RUNTIME_V6),
            "launch_commit": launch_commit, "gpu": "none",
            "solver_launch": "forbidden", "source_output_protection": "new receipt only",
        },
        "source_binding": {
            "copy_plan": str(plan_path.resolve()),
            "copy_plan_sha256": sha256_file(plan_path),
            "source_sha256": plan["source_bi4"]["sha256"],
            "source_bytes": plan["source_bi4"]["bytes"],
            "hardlink_forbidden": True,
        },
        "qualification": dict(UNKNOWN),
    }


def _common_v6_bindings(request: dict[str, Any], launch_commit: str, *, external: bool) -> None:
    request["resource_guard"] = {
        "owner": "stage2-reference-preparation", "runner": str(DISPATCH_V6),
        "strict_guard": str(STRICT_V6), "runtime": str(RUNTIME_V6),
        "launch_commit": launch_commit, "gpu_uuid_lease": "parent fresh UUID only",
        "protected_gpu6": PROTECTED_GPU6, "source_output_protection": "new attempt only",
    }
    request["launch_policy"] = {
        "launch_disabled": False, "execution_allowed": True,
        "solver_launch_owner": "root", "primary_gpu_dispatch_required": True,
        "gpu_uuid_authorization": "PARENT_FRESH_UUID_LEASE_REQUIRED",
        "protected_external_gpu": PROTECTED_GPU6,
    }
    request["execution_allowed"] = True
    request["launch_disabled"] = False
    request["solver_started"] = False
    request["gpu_started"] = False
    request["hdf5_read"] = False
    request["native_raw_hdf5_open"] = False
    request["actual_gpu_uuid_from_parent_runtime"] = True
    request["cfd_invoked"] = False
    request["model_invoked"] = False
    request["qualification"] = dict(UNKNOWN)
    request["preconditions"] = list(request.get("preconditions", []))
    request["preconditions"].append({
        "required": "PASS_COPY_SOURCE_BOUND",
        "copy_receipt_not_an_input": True,
        "copy_plan": request["materialization"]["copy_plan"],
        "copy_plan_sha256": request["materialization"]["copy_plan_sha256"],
        "source_sha256": request["materialization"]["source_bi4_sha256"],
        "destination_policy": "new regular copy, distinct inode, source stat unchanged",
    })


def _prepare_base_v6(v2: dict[str, Any], proof: dict[str, Any], rung: str, mode: str,
                     plan: dict[str, Any], plan_path: Path, launch_commit: str) -> dict[str, Any]:
    request = json.loads(json.dumps(v2))
    if request.get("schema") != SCHEMA or request.get("kind") != "qualification":
        raise BuildError("unexpected consumed F1 solver request")
    source = Path(str(plan["source_bi4"]["path"])).expanduser().resolve()
    overlay_prefix = Path(str(request["materialization"]["overlay_prefix"])).expanduser().resolve()
    overlay_xml = Path(str(request["materialization"]["overlay_xml"])).expanduser().resolve()
    overlay_bi4 = Path(str(overlay_prefix) + ".bi4")
    source_sha = str(plan["source_bi4"]["sha256"])
    # v6 performs the actual content hash after reservation.  The builder only
    # consumes the already-recorded QA digest for both the source and copy.
    for path in (source, overlay_bi4):
        _add_hash(request, path, source_sha)
    _add_hash(request, overlay_xml, sha256_file(overlay_xml))
    for path in (DISPATCH_V6, STRICT_V6, RUNTIME_V6, MATERIALIZER, plan_path):
        _add_hash(request, path, sha256_file(path))
    request["input_hashes"] = {str(Path(k).expanduser().resolve()): v
                                for k, v in request["input_hashes"].items()}
    # Replace only placeholder hashes.  Do not re-read the BI4.
    for key in list(request["input_hashes"]):
        value = request["input_hashes"][key]
        if value in {"PARENT_V8_GUARD_REQUIRED", "PARENT_V6_GPU_GUARD_REQUIRED"}:
            path = Path(key)
            request["input_hashes"][key] = source_sha if path.suffix == ".bi4" else _existing_hash(path)
    request["launch_commit"] = launch_commit
    request["resource_guard"] = {}
    request["materialization"] = {
        "mode": "copy",
        "copy_plan": str(plan_path.resolve()),
        "copy_plan_sha256": sha256_file(plan_path),
        "source_bi4": str(source), "source_bi4_sha256": source_sha,
        "source_bi4_bytes": int(plan["source_bi4"]["bytes"]),
        "overlay_prefix": str(overlay_prefix), "overlay_bi4": str(overlay_bi4),
        # Retain the consumed request's XML overlay in the forward material-
        # ization block.  External v6 builds this field after this block is
        # replaced, so omitting it makes the request non-buildable.
        "overlay_xml": str(overlay_xml),
        "required_receipt_status": "PASS_COPY_SOURCE_BOUND",
        "hardlink_forbidden": True,
        "source_pre_post_stat_all_fields_equal": True,
    }
    request["source_binding"]["generated_source"]["bi4"]["sha256"] = source_sha
    request["source_binding"]["generated_source"]["bi4"]["bytes"] = int(plan["source_bi4"]["bytes"])
    _common_v6_bindings(request, launch_commit, external=False)
    request["input_scope"] = {str(p): "post_reservation_hash" for p in request["input_files"]}
    request["input_scope"][str(source)] = "post_reservation_hash"
    request["input_scope"][str(overlay_bi4)] = "post_reservation_hash"
    request["input_scope"][str(plan_path.resolve())] = "post_reservation_hash"
    request["command"][0] = str(SOLVER)
    request["estimated_storage_bytes"] = 20 * 1024**3 if rung == "DP005" else 132 * 1024**3
    request["materialization"]["mode_name"] = mode
    request["parent_gpu_entry"] = {
        "runner": "ds_data02_stage2_dispatch_v6.py",
        "strict_runner": "ds_data02_strict_dispatch_v6.py",
        "runtime": "ds_data02_runtime_v6.py",
        "requires_fresh_uuid_lease": True,
        "gpu6_protected": PROTECTED_GPU6,
    }
    return request


def _externalize(request: dict[str, Any], rung: str, mode: str, launch_commit: str) -> dict[str, Any]:
    """Convert one consumed v2 request to the existing external v5 contract.

    The v5 runner deliberately validates file metadata before reservation and
    hashes actionable content only after the reservation is registered.  The
    producer BI4 is therefore kept in ``materialization`` metadata but is
    removed from ``input_files``.  The regular copy created by the preceding
    v8 task is the only BI4 presented to v5.
    """
    out = json.loads(json.dumps(request))
    attempt = f"f1-s1-owner-{rung.lower()}-{mode}-savedt-v5-root-001"
    source = Path(str(out["materialization"]["source_bi4"])).expanduser().resolve()
    source_sha = str(out["materialization"]["source_bi4_sha256"])
    prefix = Path(str(out["materialization"]["overlay_prefix"])).expanduser().resolve()
    overlay_bi4 = Path(str(prefix) + ".bi4")
    xml = Path(str(out["materialization"]["overlay_xml"])).expanduser().resolve()

    # Start from the consumed small-file closure, dropping the producer BI4
    # and all old v6-only fields.  The copied BI4 is added below with the QA
    # digest; it does not get opened by this builder.
    old_files = [Path(str(p)).expanduser().resolve() for p in out.get("input_files", [])]
    old_hashes = {str(Path(str(k)).expanduser().resolve()): str(v)
                  for k, v in out.get("input_hashes", {}).items()}
    files: list[Path] = []
    hashes: dict[str, str] = {}
    for path in old_files:
        if path == source:
            continue
        if path == Path(str(SOLVER)).expanduser().resolve():
            # The external v5 binding supplies the official executable; retain
            # it in the closure with its real digest, not the v8 placeholder.
            digest = sha256_file(path)
        else:
            digest = old_hashes.get(str(path))
            if digest in {None, "PARENT_V8_GUARD_REQUIRED", "PARENT_V6_GPU_GUARD_REQUIRED"}:
                digest = sha256_file(path)
        if path not in files:
            files.append(path)
            hashes[str(path)] = str(digest)
    for path in (xml, overlay_bi4):
        if path not in files:
            files.append(path)
        hashes[str(path)] = sha256_file(xml) if path == xml else source_sha
    # v5 needs its own v1/v4/v5/runtime and official-library bindings in the
    # validated input closure.  Paths are resolved from the parent worktree at
    # build time; none of these additions opens a native BI4.
    for path in (RUNTIME_V2, EXTERNAL_V1, EXTERNAL_V4, EXTERNAL_V5,
                 OFFICIAL_ROOT / "libdsphchrono.so", OFFICIAL_ROOT / "libChronoEngine.so"):
        path = path.expanduser().resolve()
        if path not in files:
            files.append(path)
        hashes[str(path)] = sha256_file(path)

    out["schema"] = EXTERNAL_SCHEMA
    out["status"] = "READY_FOR_PARENT_GUARD"
    out["role"] = "DEVELOPMENT"
    out["case_id"] = f"f1-s1-owner-{rung.lower()}-{mode}-savedt-nvme"
    out["attempt_id"] = attempt
    out["runner_schema"] = EXTERNAL_SCHEMA
    out["runner_script"] = str(EXTERNAL_V5)
    out["runtime_binding"] = {"path": str(RUNTIME_V2), "role": "shared_runtime_v2",
                               "sha256": sha256_file(RUNTIME_V2)}
    out["v1_runner_binding"] = {"path": str(EXTERNAL_V1), "sha256": sha256_file(EXTERNAL_V1)}
    out["v4_runner_binding"] = {"path": str(EXTERNAL_V4), "sha256": sha256_file(EXTERNAL_V4)}
    out["v5_runner_binding"] = {"path": str(EXTERNAL_V5), "sha256": sha256_file(EXTERNAL_V5)}
    out.pop("v6_runner_binding", None)
    out["resource_guard"] = {
        "owner": "stage2-reference-preparation",
        "runner": str(EXTERNAL_V5),
        "runtime": str(RUNTIME_V2),
        "reservation_order": "parent external-v5 reserve then content hash then UUID lease-bound launch",
        "launch_commit": launch_commit,
        "gpu_uuid_lease": "parent fresh UUID only",
        "protected_gpu6": PROTECTED_GPU6,
        "source_output_protection": "new attempt output only",
    }
    out["launch_policy"] = {
        "launch_disabled": False, "execution_allowed": True,
        "solver_launch_owner": "root", "primary_gpu_dispatch_required": True,
        "gpu_uuid_authorization": "PARENT_FRESH_UUID_LEASE_REQUIRED",
        "runner": str(EXTERNAL_V5), "protected_external_gpu": PROTECTED_GPU6,
    }
    out.pop("parent_gpu_entry", None)
    out["input_files"] = [str(path) for path in files]
    out.pop("input_hashes", None)
    out["input_sha256"] = hashes
    out["input_content_scope"] = {str(path): "post_reservation_hash" for path in files}
    out["input_content_scope"][str(overlay_bi4)] = "post_reservation_hash"
    out["input_content_scope"][str(xml)] = "post_reservation_hash"
    out["materialization"] = {
        "mode": "regular_copy_prepared_by_parent_v8",
        "copy_plan": str(out["materialization"]["copy_plan"]),
        "copy_plan_sha256": out["materialization"]["copy_plan_sha256"],
        "source_bi4": str(source), "source_bi4_sha256": source_sha,
        "source_bi4_bytes": int(out["materialization"].get("source_bi4_bytes", 0) or 0),
        "source_bi4_excluded_from_v5_input_files": True,
        "overlay_prefix": str(prefix), "overlay_bi4": str(overlay_bi4),
        "overlay_xml": str(xml),
        "required_receipt_status": "PASS_COPY_SOURCE_BOUND",
        "copy_receipt_required_before_v5": True,
        "hardlink_forbidden": True,
        "source_pre_post_stat_all_fields_equal": True,
        "destination_must_have_distinct_inode": True,
    }
    out["command"] = [str(SOLVER), "-gpu:0", str(prefix),
                       "{output_root}/solver_output", "-tmax:1.600082994772861", "-tout:0.005"]
    out.pop("solver_input_materialization", None)
    product = (20 if rung == "DP005" else 132) * 1024**3
    receipt = 8 * 1024**2
    out_root = EXTERNAL_ROOT / "F1" / f"F1_S1_OWNER_{rung}_{mode.upper()}_NVME_SAVEDT" / attempt
    parent = parent_binding()
    out["parent_resource_binding"] = parent
    out["storage_scope"] = {
        "external_filesystem": str(EXTERNAL_ROOT), "output_root": str(out_root),
        "external_product_reserved_bytes": product,
        "home_receipt_reserved_bytes": receipt,
        "new_storage_bytes": product + receipt,
        "home_min_free_bytes": int(parent["limits"]["home_min_free_bytes"]),
        "external_min_free_bytes": 1,
        "serial_policy": True,
        "do_not_reserve_pair_together": True,
    }
    out["gpu"] = {"required": True, "gpu_uuid": None,
                   "selection_policy": "parent_runtime_selected_uuid_must_be_recorded",
                   "lease_root": str(DATA_ROOT / "leases")}
    out["official_library_binding"] = {
        "root": str(OFFICIAL_ROOT),
        "files": [{"role": name, "path": str(OFFICIAL_ROOT / name),
                   "sha256": sha256_file(OFFICIAL_ROOT / name)}
                  for name in ("libdsphchrono.so", "libChronoEngine.so")],
        "purpose": "official libraries prepended at child launch",
    }
    out["launch_environment_contract"] = {
        "LD_LIBRARY_PATH": "official_library_binding.root + inherited_parent_value",
        "official_root_precedes_inherited": True,
        "original_path_fallback": "FORBIDDEN",
        "actual_environment_recorded_in_receipt": True,
    }
    out["execution"] = {
        "manufactured_only": False, "preflight_cfd_invoked": False,
        "cfd_invoked": False, "model_invoked": False,
        "native_bi4_open": True, "native_raw_hdf5_open": False,
        "reference_hdf5_open_forbidden": True,
        "reference_xmf_open_forbidden": True,
        "native_shared_library_binding": "official_library_binding",
        "runner_schema": EXTERNAL_SCHEMA, "runner_script": str(EXTERNAL_V5),
        "runtime_cfd_flag_from_process_launch": True,
        "scientific_status": "DEVELOPMENT_SOURCE_BOUND",
    }
    out["timing_contract"] = {
        "entry_to_terminal_deadline": True, "entry_time_includes_request_parse": True,
        "pre_and_post_input_hash_stat_included": True,
        "posthash_output_and_materialization_included": True,
        "gpu_cutoff": "single frozen post-product measurement reused by receipt and ledger",
        "receipt_finalization_scope": "bounded serialization and lease release after cutoff",
        "cancel_cleanup_bounded": True,
    }
    out["provenance_reference_files"] = []
    out["physical_qualification"] = "UNKNOWN"
    out["split_role"] = "DEVELOPMENT_PROSPECTIVE_ONLY"
    out["launch_allowed"] = True
    out["execution_allowed"] = True
    out["launch_disabled"] = False
    out["model_invoked"] = False
    out["cfd_invoked"] = False
    out["hdf5_opened"] = False
    out["raw_opened"] = False
    out["hdf5_read"] = False
    out["native_raw_hdf5_open"] = False
    out["gpu_started"] = False
    out["solver_started"] = False
    out["launch_commit"] = launch_commit
    out["source_provenance"] = {
        **dict(out.get("source_provenance", {})),
        "bi4_copy_required_before_external_v5": True,
        "original_bi4_excluded_from_post_copy_solver_inputs": True,
        "copy_receipt_required_before_v5": True,
        "copy_source_sha256": source_sha,
        "copy_source_bytes": int(out["materialization"].get("source_bi4_bytes", 0) or 0),
        "home_floor_preserved_by_external_product": True,
        "external_product_serial_policy": True,
        "external_runner_reserves_before_content_hash": True,
    }
    out["forward_of"] = {
        "schema": "ds02.stage2.f1-s1.owner-matched-binding.v1",
        "consumed_v2_schema": SCHEMA,
        "reason": "external-v5 reservation-before-content-hash and new-copy source integrity",
    }
    out["qualification"] = dict(UNKNOWN)
    out["sha256"] = canonical_sha(out)
    return out


def build(output_dir: Path, *, launch_commit: str | None = None) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    launch_commit = launch_commit or git_commit()
    cases = proof_cases()
    parent_binding()  # fail before producing a partial request set
    outputs: dict[str, Any] = {"schema": "ds02.stage2.f1.owner-gpu-forward-manifest.v1",
                               "status": "READY_FOR_PARENT_REVIEW", "launch_commit": launch_commit,
                               "source_qa_proof": str(QA_PROOF), "files": []}
    for rung in ("DP005", "DP0025"):
        v2_files = sorted(V2_DIR.glob(f"f1_s1_owner_{rung.lower()}_*_savedt_dense_v1.json"))
        if len(v2_files) != 2:
            raise BuildError(f"expected two consumed v2 requests for {rung}")
        sample = load_json(v2_files[0])
        source_path = Path(str(sample["materialization"]["source_bi4"])).expanduser().resolve()
        proof = cases.get(str(source_path))
        if proof is None:
            raise BuildError(f"no actual QA source proof for {source_path}")
        plan_path = output_dir / "materialization" / f"{rung.lower()}_copy_plan_v2.json"
        plan = _materialization_plan(sample, rung, proof, plan_path)
        cpu = _cpu_copy_request(rung, plan_path, plan, launch_commit)
        cpu_path = output_dir / "materialization" / f"f1_s1_owner_{rung.lower()}_bi4_copy_v2.json"
        cpu_path.write_text(json.dumps(cpu, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs["files"].extend([str(plan_path), str(cpu_path)])
        for v2_path in v2_files:
            v2 = load_json(v2_path)
            mode = "same_cfl" if "same_cfl" in v2_path.name else "half_cfl"
            request = _prepare_base_v6(v2, proof, rung, mode, plan, plan_path, launch_commit)
            request = _externalize(request, rung, mode, launch_commit)
            out_name = f"f1_s1_owner_{rung.lower()}_{mode}_savedt_external_v5.json"
            out_path = output_dir / out_name
            if out_path.exists():
                raise BuildError(f"refusing existing request: {out_path}")
            out_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            outputs["files"].append(str(out_path))
    manifest_path = output_dir / "f1_s1_owner_gpu_forward_manifest_v5.json"
    outputs["files"] = [str(Path(p).resolve()) for p in outputs["files"]]
    outputs["request_count"] = 4
    outputs["materialization_count"] = 2
    outputs["source_integrity"] = "QA digest bound; parent copy pre/post source stat and v6 pre/post digest required"
    outputs["external_solver_policy"] = "external v5 for both rungs; DP005 20GiB and DP0025 132GiB NVMe products; Home retains only bounded receipt reservation; run one at a time"
    outputs["sha256"] = canonical_sha(outputs)
    manifest_path.write_text(json.dumps(outputs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return outputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=REQUEST_DIR)
    ap.add_argument("--launch-commit")
    args = ap.parse_args(argv)
    try:
        result = build(args.output_dir, launch_commit=args.launch_commit)
    except (BuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "request_count": result["request_count"],
                      "materialization_count": result["materialization_count"],
                      "manifest": str((args.output_dir / "f1_s1_owner_gpu_forward_manifest_v5.json").resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
