#!/usr/bin/env python3
"""Resource-gated, exactly-once F8 R008 CPU GenCase/native decode preflight."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable
import xml.etree.ElementTree as ET

from scripts import f8_r008_cpu_native_preflight_authorization_v1 as authorization_builder


LAB = Path(__file__).resolve().parents[1]
AUTHORIZATION = authorization_builder.LAB / authorization_builder.OUTPUT
REQUEST = authorization_builder.LAB / authorization_builder.REQUEST
OUTPUT = authorization_builder.LAB / authorization_builder.ROOT / "cpu-native-preflight-v3"
SCHEMA = "core.cfd.f8.r008_cpu_native_preflight.v1"
LOCK_SCHEMA = "core.cfd.f8.r008_cpu_native_preflight_lock.v1"
F3_MARKER = "f3-material-30-canonical-s4-r003"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_binding(item: dict[str, Any]) -> Path:
    raw = item.get("path")
    if not isinstance(raw, str) or not raw:
        raise ValueError("authorization binding lacks a path")
    path = Path(raw)
    resolved = path.resolve(strict=True) if path.is_absolute() else (LAB / path).resolve(strict=True)
    if not path.is_absolute():
        resolved.relative_to(LAB.resolve())
    if (not resolved.is_file() or resolved.stat().st_size != item.get("bytes")
            or sha256(resolved) != item.get("sha256")):
        raise ValueError(f"authorization hash binding changed: {raw}")
    return resolved


def load_authorization(path: Path = AUTHORIZATION) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("R008 authorization must be a JSON object")
    validate_authorization(value)
    return value


def validate_authorization(value: dict[str, Any]) -> None:
    if not (
        value.get("schema") == authorization_builder.SCHEMA
        and value.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
        and value.get("status") == "authorized_for_exactly_one_r008_cpu_native_preflight"
        and value.get("qualification_credit") == 0
        and value.get("output_namespace", {}).get("path") == str(authorization_builder.ROOT / "cpu-native-preflight-v3")
        and value.get("output_namespace", {}).get("must_be_absent_before_start") is True
        and value.get("output_namespace", {}).get("reuse_or_retry_allowed") is False
    ):
        raise PermissionError("R008 authorization does not match the registered one-shot zero-credit scope")
    permissions = value.get("permissions", {})
    if not (
        permissions.get("cpu_gencase") is True
        and permissions.get("native_decode") is True
        and all(permissions.get(key) is False for key in (
            "solver", "gpu", "queue", "scheduler", "worker", "registry", "ledger", "training", "qualification"
        ))
        and all(permissions.get(key) == 0 for key in (
            "queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"
        ))
    ):
        raise PermissionError("R008 authorization opens an out-of-scope execution or mutation surface")
    policy = value.get("execution_policy", {})
    if not all(policy.get(key) is True for key in (
        "exactly_one_gencase_before_any_native_decode", "at_most_one_native_decode",
        "decode_only_after_gencase_geometry_and_control_copy_gates_pass",
        "fail_closed_on_any_error_timeout_cap_pressure_or_oom", "same_input_retry_forbidden",
        "output_reuse_forbidden", "resource_block_defers_without_output_namespace_or_lock",
        "resource_gate_rechecked_immediately_before_lock",
        "no_solver_gpu_queue_worker_registry_ledger_training_or_qualification",
    )):
        raise PermissionError("R008 authorization is missing a mandatory fail-closed or one-shot rule")
    resource = value.get("resource_scope", {})
    prelaunch = resource.get("prelaunch_gates", {})
    if not (
        resource.get("memory_max_bytes") == authorization_builder.MEMORY_MAX_BYTES
        and resource.get("memory_accounting") is True
        and resource.get("cpu_only") is True
        and resource.get("native_child_cpu_affinity") == "one CPU from current affinity mask; descendants inherit"
        and resource.get("gpu") is False
        and resource.get("max_concurrent_native_processes") == 1
        and resource.get("cap_pressure_or_oom_fails_preflight") is True
        and prelaunch.get("available_memory_bytes_minimum") == authorization_builder.MIN_AVAILABLE_MEMORY_BYTES
        and prelaunch.get("free_disk_bytes_minimum") == authorization_builder.MIN_FREE_DISK_BYTES
        and prelaunch.get("f3_material_row30_worker_must_be_absent") is True
        and prelaunch.get("systemd_user_manager_must_be_responsive") is True
        and prelaunch.get("transient_scope_names_must_be_unused") is True
        and prelaunch.get("cgroup_v2_and_systemd_run_must_be_available") is True
    ):
        raise PermissionError("R008 authorization lacks its exact cgroup and CPU-only resource envelope")

    request_ref = value.get("request_reference", {})
    if _resolve_binding(request_ref) != REQUEST.resolve():
        raise PermissionError("R008 authorization is not bound to the current v3 request")
    review_ref = value.get("independent_review_reference", {})
    if _resolve_binding(review_ref) != (LAB / authorization_builder.INDEPENDENT_REVIEW).resolve():
        raise PermissionError("R008 authorization is not bound to the registered independent static review")
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    binding_index = {
        (str(item.get("path")), item.get("sha256"), item.get("bytes"))
        for item in value.get("bindings", [])
    }
    required_closure = [
        *request.get("all_r008_inputs", {}).get("bindings", []),
        *request.get("source_bindings", []),
        request.get("resource_admission_reference", {}),
        request.get("capability_probe_reference", {}),
        value.get("independent_review_reference", {}),
    ]
    if (len(request.get("all_r008_inputs", {}).get("bindings", [])) != 94
            or len(request.get("source_bindings", [])) != 24
            or request.get("source_binding_count") != 24
            or any((str(item.get("path")), item.get("sha256"), item.get("bytes")) not in binding_index
                   for item in required_closure)):
        raise PermissionError("R008 authorization omits part of the v3 input, source, resource, cap, or review closure")
    critical_paths = (
        authorization_builder.REQUEST, authorization_builder.RESOURCE, authorization_builder.CAPABILITY,
        authorization_builder.INDEPENDENT_REVIEW, authorization_builder.R007_AUTH,
        authorization_builder.R007_PREFLIGHT, authorization_builder.SCOPED_COMMAND,
        authorization_builder.EXECUTOR, authorization_builder.BUILDER, authorization_builder.TESTS,
        authorization_builder.AUDIT_HELPERS, authorization_builder.NATIVE_HELPERS,
        authorization_builder.NATIVE_RUNNER, authorization_builder.GEOMETRY_REVIEW,
        Path("tests/test_f8_r006_cpu_native_preflight_v1.py"),
        Path("tests/test_f8_r007_cpu_native_preflight_v1.py"),
        Path("tests/test_f8_r003_cpu_native_preflight_v1.py"),
        Path("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"),
        Path("campaigns/l1-resume/artifacts/bi4_dump"),
    )
    for relative in critical_paths:
        critical_path = LAB / relative
        expected_identity = (str(relative), sha256(critical_path), critical_path.stat().st_size)
        if expected_identity not in binding_index:
            raise PermissionError(f"R008 authorization omits critical executable/audit source: {relative}")
    templates = request.get("proposed_preflight_only", {}).get("argv_templates_not_executed", {})
    native_tools = value.get("native_tools", {})
    requested_tools = request.get("proposed_preflight_only", {}).get("cpu_native_tools_inherited_as_metadata_only", {})
    if not (
        value.get("target_case") == request.get("target_case")
        and native_tools.get("gencase_argv_template") == templates.get("gencase")
        and native_tools.get("native_decode_argv_template") == templates.get("native_decode")
        and native_tools.get("working_directory") == templates.get("working_directory")
        and native_tools.get("gencase", {}).get("sha256") == requested_tools.get("gencase_binary", {}).get("sha256")
        and native_tools.get("gencase", {}).get("bytes") == requested_tools.get("gencase_binary", {}).get("bytes")
        and native_tools.get("native_decoder", {}).get("sha256") == requested_tools.get("native_decoder", {}).get("sha256")
        and native_tools.get("native_decoder", {}).get("bytes") == requested_tools.get("native_decoder", {}).get("bytes")
    ):
        raise PermissionError("R008 authorization does not exactly preserve the v3 input and native argv scope")
    for item in value.get("bindings", []):
        _resolve_binding(item)
    runtime = value.get("runtime_bindings", {})
    for key in ("systemd_run", "systemctl", "python_interpreter"):
        if key not in runtime:
            raise PermissionError(f"R008 authorization lacks runtime binding: {key}")
        _resolve_binding(runtime[key])
    if Path(runtime["python_interpreter"]["path"]).resolve() != Path(sys.executable).resolve():
        raise PermissionError("the Python interpreter differs from the hash-bound telemetry runtime")


def parse_memavailable_bytes(meminfo: str) -> int:
    for line in meminfo.splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) != 3 or fields[2] != "kB" or not fields[1].isdecimal():
                raise ValueError("MemAvailable entry is malformed")
            return int(fields[1]) * 1024
    raise ValueError("MemAvailable is missing from /proc/meminfo")


def f3_material_worker_pids(proc_root: Path = Path("/proc")) -> list[int]:
    own_pid = os.getpid()
    matches: list[int] = []
    for entry in Path(proc_root).iterdir():
        if not entry.name.isdecimal() or int(entry.name) == own_pid:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except (FileNotFoundError, ProcessLookupError, PermissionError, IsADirectoryError):
            continue
        if F3_MARKER in command:
            matches.append(int(entry.name))
    return sorted(set(matches))


def _systemd_user_manager_responsive(systemctl: Path) -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            [str(systemctl), "--user", "show-environment"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, repr(error)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace")[-500:]
        return False, f"systemctl --user show-environment returned {result.returncode}: {detail}"
    return True, None


def _systemd_scope_names_available(systemctl: Path, names: list[str]) -> tuple[bool, list[str], str | None]:
    occupied: list[str] = []
    for name in names:
        unit = name if name.endswith(".scope") else name + ".scope"
        try:
            result = subprocess.run(
                [str(systemctl), "--user", "show", unit, "--property=LoadState", "--value"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, occupied, repr(error)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace")[-500:]
            return False, occupied, f"systemd unit lookup failed for {unit}: {detail}"
        if result.stdout.decode("utf-8", "replace").strip() != "not-found":
            occupied.append(unit)
    return not occupied, occupied, None


def collect_resource_snapshot(
    output_parent: Path,
    *,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    load_getter: Callable[[], tuple[float, float, float]] = os.getloadavg,
    affinity_getter: Callable[[], set[int]] = os.sched_getaffinity,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    manager_probe: Callable[[Path], tuple[bool, str | None]] = _systemd_user_manager_responsive,
    systemctl_path: Path | None = None,
) -> dict[str, Any]:
    affinity = affinity_getter(0)
    loads = load_getter()
    meminfo = (Path(proc_root) / "meminfo").read_text(encoding="ascii")
    disk = disk_usage(Path(output_parent))
    controllers_path = Path(cgroup_root) / "cgroup.controllers"
    controllers = controllers_path.read_text(encoding="ascii").split() if controllers_path.is_file() else []
    unified_cgroup = any(line.startswith("0::") for line in (Path(proc_root) / "self/cgroup").read_text(encoding="ascii").splitlines())
    authorized = load_authorization() if systemctl_path is None else None
    runtime = authorized.get("runtime_bindings", {}) if authorized else {}
    bound_systemctl = systemctl_path or Path(runtime["systemctl"]["path"])
    manager_ok, manager_error = manager_probe(bound_systemctl)
    unit_names: list[str] = []
    if authorized:
        for key in ("gencase_argv_template", "native_decode_argv_template"):
            template = authorized["native_tools"][key]
            unit_names.append(next(item.split("=", 1)[1] for item in template if item.startswith("--unit=")))
    scope_names_ok, occupied_units, unit_query_error = _systemd_scope_names_available(bound_systemctl, unit_names) if manager_ok else (False, [], manager_error)
    return {
        "observed_at_utc": stamp(),
        "cpu_affinity_count": len(affinity),
        "load_average_1_5_15_min": [float(item) for item in loads],
        "mem_available_bytes": parse_memavailable_bytes(meminfo),
        "filesystem_free_bytes": int(disk.free),
        "f3_material_row30_pids": f3_material_worker_pids(proc_root),
        "cgroup_v2_unified": unified_cgroup,
        "cgroup_v2_memory_controller": "memory" in controllers,
        "systemd_user_manager_responsive": manager_ok,
        "systemd_user_manager_error": manager_error,
        "systemd_scope_names_available": scope_names_ok,
        "occupied_transient_scope_units": occupied_units,
        "systemd_scope_name_query_error": unit_query_error,
    }


def gate_blockers(snapshot: dict[str, Any], authorization: dict[str, Any]) -> list[str]:
    gates = authorization["resource_scope"]["prelaunch_gates"]
    blockers: list[str] = []
    cpus = int(snapshot.get("cpu_affinity_count", 0))
    loads = snapshot.get("load_average_1_5_15_min", [])
    if cpus < int(gates["cpu_affinity_count_minimum"]):
        blockers.append("CPU affinity reports no available execution core")
    if len(loads) != 3 or not math.isfinite(float(loads[0])) or float(loads[0]) > cpus:
        blockers.append(f"1-minute load {loads[0] if loads else 'missing'} exceeds affinity CPU count {cpus}")
    if int(snapshot.get("mem_available_bytes", 0)) < int(gates["available_memory_bytes_minimum"]):
        blockers.append("available memory is below the 8 GiB reserve")
    if int(snapshot.get("filesystem_free_bytes", 0)) < int(gates["free_disk_bytes_minimum"]):
        blockers.append("free disk is below the 8 GiB reserve")
    if snapshot.get("f3_material_row30_pids"):
        blockers.append("F3 material row30 worker/coordinator is still live")
    if snapshot.get("cgroup_v2_unified") is not True or snapshot.get("cgroup_v2_memory_controller") is not True:
        blockers.append("the current host does not expose the required unified cgroup-v2 memory controller")
    if snapshot.get("systemd_user_manager_responsive") is not True:
        blockers.append("the rootless systemd user manager is not responsive")
    if snapshot.get("systemd_scope_names_available") is not True:
        blockers.append("one or both exact R008 transient scope names are already loaded or unavailable")
    return blockers


def _load_request() -> dict[str, Any]:
    value = json.loads(REQUEST.read_text(encoding="utf-8"))
    if value.get("schema") != "core.cfd.f8.r008_cpu_native_preflight_request.v3":
        raise ValueError("R008 request schema changed")
    return value


def build_execution_plan(authorization: dict[str, Any]) -> dict[str, Any]:
    validate_authorization(authorization)
    request = _load_request()
    proposed = request["proposed_preflight_only"]
    templates = proposed["argv_templates_not_executed"]
    definition = (LAB / request["target_case"]["definition"]["path"]).resolve(strict=True)
    control = (LAB / request["target_case"]["control"]["path"]).resolve(strict=True)
    if definition.parent != control.parent:
        raise ValueError("R008 Definition and acceleration control must remain colocated")
    definition_root = ET.parse(definition).getroot()
    hswl = definition_root.find(".//constantsdef/hswl")
    control_reference = definition_root.find(".//acctimesfile")
    input_contract = {
        "definition_xml_parses": True,
        "hswl_explicit_zero": hswl is not None and hswl.get("value") == "0" and hswl.get("auto") == "true",
        "control_reference_exact": control_reference is not None and control_reference.get("value") == control.name,
        "control_is_colocated": definition.parent == control.parent,
    }
    if not all(input_contract.values()):
        raise ValueError("R008 representative Definition/control input contract failed before launch")
    output = OUTPUT.resolve()
    authorized_output = (LAB / authorization["output_namespace"]["path"]).resolve()
    if output != authorized_output:
        raise ValueError("R008 output path differs from the separately authorized namespace")

    def split_template(name: str) -> tuple[list[str], list[str]]:
        template = templates[name]
        if not isinstance(template, list) or template.count("--") != 1:
            raise ValueError(f"R008 {name} argv template is malformed")
        marker = template.index("--")
        return template[:marker + 1], template[marker + 1:]

    gencase_scope, gencase_payload = split_template("gencase")
    decode_scope, decode_payload = split_template("native_decode")
    expected_memory_arg = f"--property=MemoryMax={authorization['resource_scope']['memory_max_bytes']}"
    for scope_head in (gencase_scope, decode_scope):
        if not (
            scope_head[:3] == ["systemd-run", "--user", "--scope"]
            and expected_memory_arg in scope_head
            and "--property=MemoryAccounting=yes" in scope_head
        ):
            raise ValueError("R008 native tool template lacks its exact rootless 4 GiB accounting scope")
    if (Path(gencase_payload[0]).resolve() != (LAB / authorization["native_tools"]["gencase"]["path"]).resolve()
            or Path(decode_payload[0]).resolve() != (LAB / authorization["native_tools"]["native_decoder"]["path"]).resolve()
            or Path(gencase_payload[1]).resolve() != definition.with_suffix("")
            or Path(gencase_payload[2]).resolve() != output / "generated" / request["target_case"]["case_id"]
            or Path(decode_payload[1]).resolve() != Path(gencase_payload[2]).with_suffix(".bi4")
            or Path(decode_payload[2]).resolve() != output / "native-initial"):
        raise ValueError("R008 native argv does not exactly match the authorized case/input/output paths")

    return {
        "authorization": str(AUTHORIZATION),
        "request": str(REQUEST),
        "output_namespace": output,
        "input": {"definition": definition, "control": control},
        "input_contract": input_contract,
        "generated": {
            "prefix": Path(gencase_payload[2]),
            "definition": Path(gencase_payload[2]).with_suffix(".xml"),
            "bi4": Path(gencase_payload[2]).with_suffix(".bi4"),
            "bound_vtk": Path(str(gencase_payload[2]) + "_Bound.vtk"),
            "fluid_vtk": Path(str(gencase_payload[2]) + "_Fluid.vtk"),
            "hdp_actual_vtk": Path(str(gencase_payload[2]) + "_hdp_Actual.vtk"),
            "control_copy": Path(gencase_payload[2]).parent / control.name,
        },
        "gencase": {
            "scope_head": gencase_scope,
            "payload": gencase_payload,
            "unit": next(item.split("=", 1)[1] for item in gencase_scope if item.startswith("--unit=")),
            "timeout_seconds": int(authorization["resource_scope"]["gencase_timeout_seconds"]),
        },
        "native_decode": {
            "scope_head": decode_scope,
            "payload": decode_payload,
            "unit": next(item.split("=", 1)[1] for item in decode_scope if item.startswith("--unit=")),
            "output_base": Path(decode_payload[2]),
            "timeout_seconds": int(authorization["resource_scope"]["native_decode_timeout_seconds"]),
        },
        "working_directory": Path(templates["working_directory"]),
    }


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 evidence: {path}")
    partial = path.with_name(path.name + ".partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _cpu_environment(authorization: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    binary_dir = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
    env.update({
        "LD_LIBRARY_PATH": str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", ""),
        "CUDA_VISIBLE_DEVICES": "",
        "NVIDIA_VISIBLE_DEVICES": "void",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    })
    return env


def _scope_command(plan: dict[str, Any], stage: str, metrics_path: Path, authorization: dict[str, Any]) -> list[str]:
    data = plan[stage]
    runtime = authorization["runtime_bindings"]
    systemd_run = _resolve_binding(runtime["systemd_run"])
    python = _resolve_binding(runtime["python_interpreter"])
    wrapper = (LAB / authorization_builder.SCOPED_COMMAND).resolve(strict=True)
    return [
        str(systemd_run), *data["scope_head"][1:], str(python), str(wrapper),
        "--metrics-json", str(metrics_path),
        "--working-directory", str(plan["working_directory"] if stage == "gencase" else plan["output_namespace"]),
        "--timeout-seconds", str(data["timeout_seconds"]),
        "--memory-max-bytes", str(authorization["resource_scope"]["memory_max_bytes"]),
        "--", *data["payload"],
    ]


def _invoke_stage(
    plan: dict[str, Any], stage: str, authorization: dict[str, Any], output: Path,
) -> dict[str, Any]:
    label = "gencase" if stage == "gencase" else "native-decode"
    log_path = output / f"{label}.stdout.log"
    metrics_path = output / f"{label}.scope-metrics.json"
    if log_path.exists() or metrics_path.exists():
        raise FileExistsError(f"refusing to overwrite R008 {label} evidence")
    command = _scope_command(plan, stage, metrics_path, authorization)
    record: dict[str, Any] = {
        "command": command,
        "unit": plan[stage]["unit"],
        "native_payload": plan[stage]["payload"],
        "scope_invocation_attempted": True,
        "native_payload_invoked": False,
    }
    start = time.monotonic()
    outer_timeout = plan[stage]["timeout_seconds"] + 45
    try:
        with log_path.open("x", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                cwd=plan["working_directory"] if stage == "gencase" else output,
                env=_cpu_environment(authorization), stdout=log, stderr=subprocess.STDOUT,
                check=False, timeout=outer_timeout,
            )
        record["systemd_run_return_code"] = int(result.returncode)
    except subprocess.TimeoutExpired as error:
        record.update({"outer_timed_out": True, "error": f"systemd-run client timeout: {error!r}"})
    except Exception as error:
        record["error"] = f"scope invocation failed: {error!r}"
    record["wall_seconds"] = time.monotonic() - start
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        record["metrics_receipt"] = {"path": str(metrics_path.relative_to(LAB)), "sha256": sha256(metrics_path), "bytes": metrics_path.stat().st_size}
        record["native_payload_invoked"] = True
        record["native_return_code"] = metrics.get("child_return_code")
        record["timed_out"] = metrics.get("timed_out") is True
        record["scope_process_tree_clean"] = metrics.get("scope_process_tree_clean") is True
        record["memory"] = metrics.get("metrics")
        record["wrapper_receipt"] = metrics
    else:
        record["metrics_missing"] = True
    memory = record.get("memory", {})
    events = memory.get("memory_events", {})
    record["resource_gate_pass"] = bool(
        record.get("systemd_run_return_code") == 0
        and record.get("native_return_code") == 0
        and record.get("timed_out") is False
        and record.get("scope_process_tree_clean") is True
        and record.get("wrapper_receipt", {}).get("native_child_single_cpu_affinity_requested") is True
        and memory.get("memory_max_bytes") == authorization["resource_scope"]["memory_max_bytes"]
        and memory.get("memory_peak_bytes", authorization["resource_scope"]["memory_max_bytes"] + 1)
            <= authorization["resource_scope"]["memory_max_bytes"]
        and memory.get("cap_pressure_observed") is False
        and memory.get("oom_observed") is False
        and events.get("high", -1) == 0
        and events.get("max", -1) == 0
        and events.get("oom", -1) == 0
        and events.get("oom_kill", -1) == 0
        and events.get("oom_group_kill", 0) == 0
        and not record.get("metrics_missing")
    )
    record["log"] = {"path": str(log_path.relative_to(LAB)), "sha256": sha256(log_path), "bytes": log_path.stat().st_size} if log_path.is_file() else None
    return record


def _reference(path: Path, role: str) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    resolved = path.resolve()
    display = str(resolved.relative_to(LAB)) if resolved.is_relative_to(LAB) else str(resolved)
    return {"path": display, "sha256": sha256(resolved), "bytes": resolved.stat().st_size, "role": role}


def _audit_generated(plan: dict[str, Any], authorization: dict[str, Any]) -> dict[str, Any]:
    generated = plan["generated"]
    control_copy = generated["control_copy"]
    control_matches = control_copy.is_file() and sha256(control_copy) == authorization["target_case"]["control"]["sha256"]
    artifacts = {
        "generated_xml": generated["definition"],
        "native_bi4": generated["bi4"],
        "bound_vtk": generated["bound_vtk"],
        "fluid_vtk": generated["fluid_vtk"],
        "hdp_actual_vtk": generated["hdp_actual_vtk"],
    }
    missing = [name for name, path in artifacts.items() if not path.is_file()]
    result: dict[str, Any] = {
        "control_copy": _reference(control_copy, "GenCase colocated R008 acceleration control"),
        "control_copy_hash_matches": control_matches,
        "required_artifacts": {name: _reference(path, name.replace("_", " ")) for name, path in artifacts.items()},
        "missing_artifacts": missing,
    }
    if missing or not control_matches:
        result["pass"] = False
        return result
    from scripts import f8_r006_cpu_native_preflight_execute_v1 as audit_helpers
    geometry = audit_helpers.generated_checks(
        generated["definition"], generated["bound_vtk"], generated["fluid_vtk"],
        generated["hdp_actual_vtk"], authorization,
    )
    result["geometry_audit"] = geometry
    result["pass"] = bool(geometry.get("pass")) and control_matches
    return result


def _base_receipt(plan: dict[str, Any], authorization: dict[str, Any], lock: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "scope_id": authorization["scope_id"],
        "created_at_utc": stamp(),
        "status": "cpu_native_preflight_pending",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "authorization": _reference(Path(plan["authorization"]), "immutable one-shot CPU/native authorization"),
        "request": _reference(Path(plan["request"]), "hash-closed R008 v3 request"),
        "input": {
            "definition": _reference(plan["input"]["definition"], "R008 representative Definition"),
            "control": _reference(plan["input"]["control"], "R008 colocated acceleration control"),
        },
        "one_shot_lock": _reference(lock, "pre-execution no-retry lock"),
        "execution_controls": {
            "cpu_gencase_invocation_attempted": False,
            "cpu_gencase_invoked": False,
            "native_decode_invocation_attempted": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "worker_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
            "qualification_credit": 0,
        },
        "resource_scope": authorization["resource_scope"],
        "failure_policy": "Any error, timeout, mismatch, cap pressure, or OOM closes this one-shot scope with zero credit; no retry or output reuse.",
    }


def run_once(
    *,
    execute: bool = False,
    resource_provider: Callable[[Path], dict[str, Any]] | None = None,
    authorization_path: Path = AUTHORIZATION,
) -> dict[str, Any]:
    authorization = load_authorization(authorization_path)
    plan = build_execution_plan(authorization)
    output = Path(plan["output_namespace"])
    if output.exists() or output.is_symlink():
        return {"status": "output_namespace_occupied_no_retry", "qualification_credit": 0, "output_namespace_created": False}
    provider = resource_provider or (lambda parent: collect_resource_snapshot(parent))

    first_snapshot = provider(output.parent)
    blockers = gate_blockers(first_snapshot, authorization)
    if blockers:
        return {
            "status": "deferred_resource_gate_blocked",
            "qualification_credit": 0,
            "output_namespace_created": False,
            "one_shot_lock_created": False,
            "resource_snapshot": first_snapshot,
            "blockers": blockers,
        }
    if not execute:
        return {
            "status": "preflight_ready_not_started",
            "qualification_credit": 0,
            "output_namespace_created": False,
            "one_shot_lock_created": False,
            "resource_snapshot": first_snapshot,
            "blockers": [],
        }

    # Freshness and resource admission are checked again immediately before consuming the one-shot.
    if output.exists() or output.is_symlink():
        return {"status": "output_namespace_occupied_no_retry", "qualification_credit": 0, "output_namespace_created": False}
    second_snapshot = provider(output.parent)
    blockers = gate_blockers(second_snapshot, authorization)
    if blockers:
        return {
            "status": "deferred_resource_gate_blocked",
            "qualification_credit": 0,
            "output_namespace_created": False,
            "one_shot_lock_created": False,
            "resource_snapshot": second_snapshot,
            "blockers": blockers,
            "resource_gate_rechecked": True,
        }

    output.mkdir(parents=False, exist_ok=False)
    lock = output / "one-shot-lock.json"
    _write_exclusive(lock, {
        "schema": LOCK_SCHEMA,
        "created_at_utc": stamp(),
        "authorization": _reference(Path(plan["authorization"]), "one-shot authority"),
        "request": _reference(Path(plan["request"]), "exact R008 v3 request"),
        "same_input_retry": False,
        "gencase_invocation_budget": 1,
        "native_decode_invocation_budget": 1,
        "solver_invocation_budget": 0,
        "resource_gate_rechecked": True,
        "resource_snapshot": second_snapshot,
    })
    receipt = _base_receipt(plan, authorization, lock)
    receipt["resource_admission"] = {"status": "passed_at_launch", "snapshot": second_snapshot}
    receipt["input_contract"] = plan["input_contract"]
    receipt["commands"] = {
        "gencase_payload": plan["gencase"]["payload"],
        "native_decode_payload": plan["native_decode"]["payload"],
        "solver_invocations": 0,
    }
    receipt_path = output / "receipt.json"
    try:
        (output / "generated").mkdir()
        receipt["execution_controls"]["cpu_gencase_invocation_attempted"] = True
        gencase = _invoke_stage(plan, "gencase", authorization, output)
        receipt["gencase"] = gencase
        receipt["execution_controls"]["cpu_gencase_invoked"] = gencase.get("native_payload_invoked") is True
        if not gencase.get("resource_gate_pass"):
            receipt.update({"status": "cpu_gencase_resource_or_execution_failed", "failure": "GenCase did not complete under the clean 4 GiB cgroup gate"})
        else:
            generated_audit = _audit_generated(plan, authorization)
            receipt["generated_audit"] = generated_audit
            if not generated_audit.get("pass"):
                receipt.update({"status": "generated_geometry_or_control_copy_failed", "failure": "generated R008 artifacts did not pass the frozen hard gates"})
            else:
                receipt["execution_controls"]["native_decode_invocation_attempted"] = True
                decode = _invoke_stage(plan, "native_decode", authorization, output)
                receipt["native_decode"] = decode
                receipt["execution_controls"]["native_decode_invoked"] = decode.get("native_payload_invoked") is True
                if not decode.get("resource_gate_pass"):
                    receipt.update({"status": "native_decode_resource_or_execution_failed", "failure": "native decoder did not complete under the clean 4 GiB cgroup gate"})
                else:
                    from scripts import f8_r006_cpu_native_preflight_execute_v1 as audit_helpers
                    native_audit = audit_helpers.native_checks(
                        plan["generated"]["definition"], plan["native_decode"]["output_base"], authorization,
                    )
                    receipt["native_audit"] = native_audit
                    receipt["status"] = "cpu_native_preflight_passed_zero_credit" if native_audit.get("pass") else "native_arrays_failed_hard_audit"
                    if not native_audit.get("pass"):
                        receipt["failure"] = "decoded R008 arrays, identities, mass, or wall normals failed hard gates"
    except Exception as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"executor exception: {error!r}"})
    receipt["finished_at_utc"] = stamp()
    _write_exclusive(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="consume the authorized one-shot only if both resource gates pass")
    mode.add_argument("--preflight-only", action="store_true", help="check hashes and current resource gates without creating runtime state (default)")
    args = parser.parse_args(argv)
    try:
        result = run_once(execute=args.execute)
    except Exception as error:
        print(json.dumps({"status": "authorization_or_static_preflight_failed", "error": repr(error), "qualification_credit": 0}, sort_keys=True))
        return 2
    summary = {key: result.get(key) for key in (
        "status", "qualification_credit", "output_namespace_created", "one_shot_lock_created", "blockers",
    ) if key in result}
    print(json.dumps(summary, sort_keys=True))
    return 0 if result.get("status") in ("preflight_ready_not_started", "cpu_native_preflight_passed_zero_credit") else 3


if __name__ == "__main__":
    raise SystemExit(main())
