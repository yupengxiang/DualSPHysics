#!/usr/bin/env python3
"""Build a read-only root review for the Core A8 cross-host evidence.

The review joins two kinds of evidence that are easy to confuse:

* a bounded 20-step float64 arithmetic canary, and
* the existing 835-transition A8 MLP reproduction.

Both terminals must identify different physical hostnames and disjoint GPU
UUIDs.  A copied receipt, a same-host relocation, or a single terminal with a
``cross_host_reproduction`` marker is rejected.  The output is an admission
observation only: it never submits work, writes a registry/ledger, or changes
the formal-training gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "core.a8.cross_host_root_review.v1"
CANARY_SCHEMA = "core.cross_host_canary.float64.v1"
COMPARISON_SCHEMA = "core.cross_host_canary.float64_comparison.v1"
A8_COMPARISON_SCHEMA = "core.a8_paired_reproduction.receipt.v1"
A8_TERMINAL_SCHEMA = "core.model_reproduction.v1"
ROOT_REVIEW_SCHEMA = "core.reproduction.root_review.v1"
EXPECTED_CASE = "F3_DEV_08_a0p953125"
EXPECTED_STEPS = 20
EXPECTED_FRAMES = 21
EXPECTED_PARTICLES = 34560
EXPECTED_MODEL = "graph_residual"
EXPECTED_REGISTERED_CASES = (EXPECTED_CASE,)
EXPECTED_REGISTERED_FRAMES = {EXPECTED_CASE: 835}
EXPECTED_REGISTERED_TRANSITIONS = EXPECTED_REGISTERED_FRAMES[EXPECTED_CASE]
EXPECTED_REGISTERED_TRAJECTORY_FRAMES = EXPECTED_REGISTERED_TRANSITIONS + 1
EXPECTED_MANIFEST = "8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680"
EXPECTED_CHECKPOINT = "9af1dc3cb68991c38fd31b59d92895326e3abe89d5d29d33dd086d7fa462b8a8"
EXPECTED_MODELS = "73a98b262500c30e46f14aafd2a89f2bea34116c77b6e34ce5e33e7412c38c77"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# The trajectory comparator is deliberately cached only by already-verified
# content hashes.  This keeps repeated read-only reviews cheap without making
# a path/mtime cache part of the admission boundary.
_PAIR_COMPARISON_CACHE: dict[tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}


class ReviewError(ValueError):
    """An evidence contract error with a stable blocker code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).expanduser().resolve()
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReviewError("INVALID_JSON_OBJECT", f"JSON object required: {resolved}")
    return value, resolved


def _ref(path: Path, root: Path) -> dict[str, Any]:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise ReviewError("NON_PORTABLE_PATH", f"evidence is outside review root: {path}")
    return {"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ReviewError(code, message)


def _sha(value: Any, *, role: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
             "INVALID_HASH", f"{role} is not a SHA-256 string")
    return value.lower()


def _portable_relative(value: Any, *, role: str) -> Path:
    """Return a slash-separated, non-escaping relative artifact path."""
    _require(isinstance(value, str) and value, "ARTIFACT_PATH_INVALID",
             f"{role} path is missing")
    _require("\\" not in value and not value.startswith("/"
             ) and re.fullmatch(r"[A-Za-z]:[\\/].*", value) is None,
             "NON_PORTABLE_PATH", f"{role} path is not portable: {value!r}")
    candidate = Path(value)
    _require(not candidate.is_absolute() and ".." not in candidate.parts
             and candidate.parts not in ((), (".",)),
             "NON_PORTABLE_PATH", f"{role} path escapes its portable root: {value!r}")
    return candidate


def _resolve_relative(base: Path, value: Any, *, role: str) -> Path:
    relative = _portable_relative(value, role=role)
    base_resolved = base.resolve()
    resolved = (base_resolved / relative).resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise ReviewError("NON_PORTABLE_PATH", f"{role} path escapes its root: {value!r}")
    _require(resolved.is_file(), "ARTIFACT_MISSING", f"{role} artifact is missing: {value!r}")
    return resolved


def _file_identity(path: Path, cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved not in cache:
        cache[resolved] = {"sha256": sha256_file(resolved), "bytes": resolved.stat().st_size}
    return cache[resolved]


def _verify_file_reference(ref: Mapping[str, Any], path: Path, *, role: str,
                           cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    _require(isinstance(ref, Mapping), "ARTIFACT_REFERENCE_MISSING",
             f"{role} artifact reference is missing")
    actual = _file_identity(path, cache)
    declared_bytes = ref.get("bytes")
    _require(type(declared_bytes) is int and declared_bytes >= 0,
             "ARTIFACT_BYTES_INVALID", f"{role} artifact bytes are invalid")
    _require(declared_bytes == actual["bytes"], "ARTIFACT_BYTES_MISMATCH",
             f"{role} artifact byte count differs from the file")
    declared_sha = _sha(ref.get("sha256"), role=f"{role} artifact")
    _require(declared_sha == actual["sha256"], "ARTIFACT_HASH_MISMATCH",
             f"{role} artifact hash differs from the file")
    return {"path": path.resolve(), **actual}


def _same_identity(left: Mapping[str, Any], right: Mapping[str, Any], *, role: str) -> None:
    _require(left.get("sha256") == right.get("sha256")
             and left.get("bytes") == right.get("bytes"),
             "ARTIFACT_IDENTITY_MISMATCH", f"{role} references different artifact bytes")


def _gpu_uuids(record: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    query = record.get("driver_query")
    stdout = query.get("stdout", "") if isinstance(query, Mapping) else ""
    if isinstance(stdout, str):
        for line in stdout.splitlines():
            fields = [part.strip() for part in line.split(",")]
            if len(fields) >= 3 and fields[-1].startswith("GPU-"):
                values.add(fields[-1])
    return values


def _package_map(record: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    result: dict[str, tuple[Any, Any]] = {}
    for row in record.get("packages", []):
        if isinstance(row, Mapping) and isinstance(row.get("name"), str):
            result[row["name"]] = (row.get("version"), row.get("sha256"))
    return result


def _module_map(record: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in record.get("bundle_modules", []):
        if isinstance(row, Mapping) and isinstance(row.get("module"), str):
            result[row["module"]] = str(row.get("sha256", ""))
    return result


def validate_host_pair(ada: Mapping[str, Any], h200: Mapping[str, Any]) -> dict[str, Any]:
    """Validate physical host identity and matched software closure."""
    for label, record in (("ada", ada), ("h200", h200)):
        _require(record.get("schema") == "core.cross_host_environment_probe.v1",
                 "ENVIRONMENT_SCHEMA", f"{label} environment probe schema is unsupported")
        _require(isinstance(record.get("hostname"), str) and record["hostname"],
                 "HOSTNAME_MISSING", f"{label} environment has no physical hostname")
        _require(isinstance(record.get("host_label"), str) and record["host_label"],
                 "HOST_LABEL_MISSING", f"{label} environment has no host label")
        _require(record.get("probe_without_cuda_model") is True,
                 "ENVIRONMENT_PROBE_INVALID", f"{label} probe did not capture pre-model environment")
        _require(_gpu_uuids(record), "GPU_IDENTITY_MISSING", f"{label} probe has no GPU UUIDs")

    left_host = str(ada["hostname"])
    right_host = str(h200["hostname"])
    _require(left_host != right_host, "SAME_HOST_RELOCATION_REJECTED",
             "Ada and H200 evidence resolve to the same physical hostname")
    left_gpu = _gpu_uuids(ada)
    right_gpu = _gpu_uuids(h200)
    _require(left_gpu.isdisjoint(right_gpu), "GPU_IDENTITY_COLLISION",
             "Ada and H200 GPU UUID sets overlap; relocation cannot be excluded")

    left_packages = _package_map(ada)
    right_packages = _package_map(h200)
    required_packages = ("torch", "numpy", "scipy", "h5py")
    _require(all(name in left_packages and name in right_packages for name in required_packages),
             "PACKAGE_CLOSURE_INCOMPLETE", "matched runtime package set is incomplete")
    package_mismatches = {
        name: {"ada": left_packages[name], "h200": right_packages[name]}
        for name in required_packages if left_packages[name] != right_packages[name]
    }
    _require(not package_mismatches, "PACKAGE_CLOSURE_MISMATCH",
             f"matched runtime package closure differs: {package_mismatches}")

    left_modules = _module_map(ada)
    right_modules = _module_map(h200)
    _require(left_modules == right_modules, "MODULE_CLOSURE_MISMATCH",
             "bundle module hashes differ across terminals")
    left_python = ada.get("python", {})
    right_python = h200.get("python", {})
    _require(left_python.get("version") == right_python.get("version"),
             "PYTHON_CLOSURE_MISMATCH", "Python runtime versions differ")
    left_torch = ada.get("torch_runtime", {})
    right_torch = h200.get("torch_runtime", {})
    _require(left_torch.get("version") == right_torch.get("version")
             and left_torch.get("cuda_version") == right_torch.get("cuda_version"),
             "TORCH_CUDA_CLOSURE_MISMATCH", "Torch/CUDA runtime versions differ")
    return {
        "distinct_physical_hosts": True,
        "ada": {
            "host_label": ada["host_label"], "hostname": left_host,
            "gpu_uuids": sorted(left_gpu),
        },
        "h200": {
            "host_label": h200["host_label"], "hostname": right_host,
            "gpu_uuids": sorted(right_gpu),
        },
        "matched_packages": {name: left_packages[name][0] for name in required_packages},
        "matched_module_hashes": left_modules,
        "python_version": left_python["version"],
        "torch_version": left_torch["version"],
        "cuda_version": left_torch["cuda_version"],
    }


def _argv_value(spec: Mapping[str, Any], flag: str) -> str | None:
    argv = spec.get("argv")
    if not isinstance(argv, list):
        return None
    try:
        index = argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    value = argv[index + 1]
    return value if isinstance(value, str) else None


def validate_canary_spec(spec: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Check that a scheduled spec is a bounded diagnostic canary."""
    _require(spec.get("maximum_steps") == EXPECTED_STEPS, "CANARY_SPEC_STEPS",
             f"{label} canary spec is not exactly 20 steps")
    _require(spec.get("model_kind") == EXPECTED_MODEL, "CANARY_SPEC_MODEL",
             f"{label} canary model kind changed")
    _require(spec.get("deterministic_runtime") is True, "CANARY_SPEC_DETERMINISM",
             f"{label} canary does not require deterministic runtime")
    _require(spec.get("formal_core_case_run") is False and spec.get("full_core_release") is False,
             "CANARY_SPEC_FORMAL", f"{label} canary spec is marked formal")
    _require(spec.get("scientific_claim", "").startswith("none;"), "CANARY_SPEC_CLAIM",
             f"{label} canary spec carries a scientific claim")
    expected = {
        "manifest": EXPECTED_MANIFEST,
        "checkpoint": EXPECTED_CHECKPOINT,
        "models": EXPECTED_MODELS,
    }
    observed: dict[str, str] = {}
    for key, flag in (("manifest", "--expected-manifest-sha256"),
                      ("checkpoint", "--expected-checkpoint-sha256"),
                      ("models", "--expected-models-sha256")):
        value = _argv_value(spec, flag)
        _require(value is not None, "CANARY_SPEC_IDENTITY", f"{label} spec omits {flag}")
        observed[key] = _sha(value, role=f"{label} {flag}")
        _require(observed[key] == expected[key], "CANARY_SPEC_IDENTITY",
                 f"{label} spec binds an unexpected {key} hash")
    return {"maximum_steps": EXPECTED_STEPS, "model_kind": EXPECTED_MODEL,
            "deterministic_runtime": True, "identity": observed,
            "variant": spec.get("variant", "float64_inference")}


def _canary_identity(report: Mapping[str, Any], label: str) -> dict[str, str]:
    bundle = report.get("bundle", {})
    identity = bundle.get("identity", {}) if isinstance(bundle, Mapping) else {}
    expected = identity.get("expected", {}) if isinstance(identity, Mapping) else {}
    observed = identity.get("observed", {}) if isinstance(identity, Mapping) else {}
    result: dict[str, str] = {}
    for key, expected_hash in (("manifest", EXPECTED_MANIFEST),
                               ("checkpoint", EXPECTED_CHECKPOINT),
                               ("core_models", EXPECTED_MODELS)):
        _require(expected.get(key) == expected_hash, "CANARY_IDENTITY",
                 f"{label} canary expected {key} hash differs")
        actual = observed.get(key, {}) if isinstance(observed, Mapping) else {}
        _require(isinstance(actual, Mapping) and actual.get("sha256") == expected_hash,
                 "CANARY_IDENTITY", f"{label} canary observed {key} hash differs")
        result[key] = expected_hash
    return result


def validate_canary(report: Mapping[str, Any], *, label: str,
                    expected_hostname: str, expected_gpu_uuid: str) -> dict[str, Any]:
    _require(report.get("schema") == CANARY_SCHEMA, "CANARY_SCHEMA",
             f"{label} canary schema is unsupported")
    _require(report.get("status") == "complete" and report.get("completed_steps") == EXPECTED_STEPS,
             "CANARY_INCOMPLETE", f"{label} canary did not complete 20 steps")
    _require(report.get("maximum_steps") == EXPECTED_STEPS
             and report.get("expected_frames") == EXPECTED_FRAMES,
             "CANARY_FRAME_CONTRACT", f"{label} canary frame contract differs")
    _require(report.get("case_id") == EXPECTED_CASE and report.get("model_kind") == EXPECTED_MODEL,
             "CANARY_CASE_CONTRACT", f"{label} canary case/model differs")
    _require(report.get("variant") == "float64_inference"
             and report.get("inference_dtype") == "float64", "CANARY_VARIANT",
             f"{label} canary is not the fixed float64 diagnostic variant")
    _require(report.get("future_state_inputs") is False and report.get("autonomous") is True,
             "CANARY_AUTONOMY", f"{label} canary used future state or was not autonomous")
    scope = report.get("diagnostic_scope", {})
    _require(isinstance(scope, Mapping) and scope.get("formal_training") is False
             and scope.get("formal_evaluation") is False, "CANARY_FORMAL_MARKER",
             f"{label} canary has a formal marker")
    environment = report.get("environment", {})
    _require(isinstance(environment, Mapping), "CANARY_ENVIRONMENT", f"{label} canary has no environment")
    _require(environment.get("hostname") == expected_hostname, "CANARY_HOST_MISMATCH",
             f"{label} canary hostname does not match the environment probe")
    _require(environment.get("cuda_visible_devices") == expected_gpu_uuid,
             "CANARY_GPU_MISMATCH", f"{label} canary selected GPU differs from its receipt")
    _require(environment.get("deterministic_algorithms_enabled") is True
             and environment.get("cudnn_deterministic") is True,
             "CANARY_DETERMINISM", f"{label} canary did not enable deterministic algorithms")
    return {"hostname": expected_hostname, "gpu_uuid": expected_gpu_uuid,
            "identity": _canary_identity(report, label)}


def validate_canary_comparison(comparison: Mapping[str, Any]) -> dict[str, Any]:
    _require(comparison.get("schema") == COMPARISON_SCHEMA, "CANARY_COMPARISON_SCHEMA",
             "20-step canary comparison schema is unsupported")
    _require(comparison.get("status") == "pass", "CANARY_COMPARISON_FAILED",
             "20-step canary comparison did not pass")
    scope = comparison.get("scope", {})
    _require(scope.get("expected_steps") == EXPECTED_STEPS
             and scope.get("expected_frames") == EXPECTED_FRAMES
             and scope.get("expected_particle_count") == EXPECTED_PARTICLES,
             "CANARY_COMPARISON_SCOPE", "20-step comparison scope differs")
    _require(comparison.get("identity", {}).get("passed") is True
             and comparison.get("arrays", {}).get("passed") is True,
             "CANARY_COMPARISON_CONTRACT", "20-step comparison identity/arrays did not pass")
    return {
        "status": "pass", "steps": EXPECTED_STEPS, "frames": EXPECTED_FRAMES,
        "particles": EXPECTED_PARTICLES,
        "position_max_abs_error": comparison["arrays"]["numeric"]["position"].get("max_abs_error"),
        "velocity_max_abs_error": comparison["arrays"]["numeric"]["velocity"].get("max_abs_error"),
    }


def _validate_execution_artifacts(execution: Mapping[str, Any], *, report_path: Path,
                                  root: Path, label: str,
                                  cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    """Bind a terminal receipt to the supplied report and all four outputs."""
    _require(isinstance(execution, Mapping), "A8_EXECUTION_REFERENCE",
             f"{label} execution reference is missing")
    _require(execution.get("execution_status") == "succeeded", "A8_EXECUTION_STATUS",
             f"{label} execution receipt is not successful")
    report_reference = execution.get("report")
    _require(isinstance(report_reference, Mapping), "A8_REPORT_REFERENCE",
             f"{label} execution has no report reference")
    _portable_relative(report_reference.get("relative_path"), role=f"{label} report")
    bound_report = _resolve_relative(root, report_reference.get("relative_path"),
                                     role=f"{label} report")
    _require(bound_report == report_path.resolve(), "A8_REPORT_BINDING",
             f"{label} comparison receipt points at a different report")
    report_identity = _verify_file_reference(report_reference, bound_report,
                                             role=f"{label} report", cache=cache)

    attempt_root = report_path.resolve().parent.parent
    required_outputs = execution.get("required_outputs")
    _require(isinstance(required_outputs, list), "A8_REQUIRED_OUTPUTS_MISSING",
             f"{label} required-output list is missing")
    expected_paths = {
        "reproduction/reproduction.json",
        "reproduction/scores.json",
        f"reproduction/cases/000-{EXPECTED_CASE}/trajectory.h5",
        f"reproduction/cases/000-{EXPECTED_CASE}/progress.json",
    }
    observed_paths: set[str] = set()
    artifacts: dict[Path, dict[str, Any]] = {}
    for index, reference in enumerate(required_outputs):
        _require(isinstance(reference, Mapping), "A8_REQUIRED_OUTPUT_REFERENCE",
                 f"{label} required output {index} is malformed")
        relative = _portable_relative(reference.get("path"),
                                      role=f"{label} required output {index}")
        relative_text = relative.as_posix()
        _require(relative_text not in observed_paths, "A8_REQUIRED_OUTPUT_DUPLICATE",
                 f"{label} required outputs contain a duplicate path")
        observed_paths.add(relative_text)
        actual = _resolve_relative(attempt_root, reference.get("path"),
                                   role=f"{label} required output {index}")
        _require(reference.get("verified") is True, "A8_REQUIRED_OUTPUT_UNVERIFIED",
                 f"{label} required output {relative_text} is not verified")
        artifacts[actual] = _verify_file_reference(
            reference, actual, role=f"{label} required output {relative_text}", cache=cache)
    _require(observed_paths == expected_paths, "A8_REQUIRED_OUTPUT_DENOMINATOR",
             f"{label} required outputs do not close the registered artifact denominator")
    _require(report_path.resolve() in artifacts, "A8_REPORT_NOT_IN_OUTPUTS",
             f"{label} report is not one of the verified required outputs")
    _same_identity(report_identity, artifacts[report_path.resolve()], role=f"{label} report")

    receipt = execution.get("receipt")
    _require(isinstance(receipt, Mapping), "A8_EXECUTION_RECEIPT_MISSING",
             f"{label} execution receipt is missing")
    receipt_path = _resolve_relative(root, receipt.get("relative_path"),
                                     role=f"{label} execution receipt")
    receipt_identity = _verify_file_reference(receipt, receipt_path,
                                              role=f"{label} execution receipt", cache=cache)

    root_collection = execution.get("root_collection")
    root_collection_identity = None
    if root_collection is not None:
        _require(isinstance(root_collection, Mapping), "A8_ROOT_COLLECTION_REFERENCE",
                 f"{label} root collection reference is malformed")
        collection_path = _resolve_relative(root, root_collection.get("relative_path"),
                                            role=f"{label} root collection")
        root_collection_identity = _verify_file_reference(
            root_collection, collection_path, role=f"{label} root collection", cache=cache)
    return {
        "report": report_identity,
        "artifacts": artifacts,
        "receipt": receipt_identity,
        "root_collection": root_collection_identity,
    }


def _validate_report_artifact(report: Mapping[str, Any], reference: Mapping[str, Any], *,
                              report_path: Path, label: str,
                              execution_artifacts: Mapping[Path, Mapping[str, Any]],
                              cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    relative = _portable_relative(reference.get("path"), role=f"{label} report artifact")
    actual = _resolve_relative(report_path.parent, reference.get("path"),
                               role=f"{label} report artifact")
    identity = _verify_file_reference(reference, actual, role=f"{label} report artifact",
                                      cache=cache)
    _require(actual in execution_artifacts, "A8_ARTIFACT_NOT_REGISTERED",
             f"{label} report artifact is absent from the required-output registry")
    _same_identity(identity, execution_artifacts[actual], role=f"{label} report artifact")
    return {"path": actual, **identity}


def _host_aliases(record: Mapping[str, Any]) -> set[str]:
    return {str(record[key]) for key in ("hostname", "host_label") if record.get(key)}


def _validate_a8_terminal(report: Mapping[str, Any], *, report_path: Path,
                          execution_artifacts: Mapping[Path, Mapping[str, Any]],
                          label: str, own_host: Mapping[str, Any],
                          other_host: Mapping[str, Any], cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    """Validate terminal facts from the report and its materialized artifacts."""
    _require(report.get("schema") == A8_TERMINAL_SCHEMA, "A8_TERMINAL_SCHEMA",
             f"{label} A8 terminal report schema is unsupported")
    own_hostname = str(own_host["hostname"])
    _require(report.get("reproduction_host") == own_hostname,
             "A8_TERMINAL_HOST_MISMATCH", f"{label} reproduction host is not bound to its probe")
    source_host = report.get("source_host")
    _require(isinstance(source_host, str) and source_host in _host_aliases(other_host),
             "A8_SOURCE_HOST_MISMATCH", f"{label} source host is not the other physical host")
    _require(report.get("cross_host_reproduction") is False,
             "A8_TERMINAL_SINGLE_HOST_MARKER", f"{label} terminal report must remain single-host")
    _require(report.get("full_product_reproduction") is False,
             "A8_TERMINAL_PRODUCT_MARKER", f"{label} terminal report is marked product-complete")
    _require(report.get("predictor_future_state_inputs") is False,
             "A8_TERMINAL_FUTURE_STATE", f"{label} terminal report used future states")
    verification = report.get("verification")
    _require(isinstance(verification, Mapping) and verification.get("host") == own_hostname,
             "A8_TERMINAL_VERIFICATION_HOST", f"{label} verification host is not bound")

    _require(report.get("case_ids") == list(EXPECTED_REGISTERED_CASES),
             "A8_REGISTERED_DENOMINATOR", f"{label} case registry is incomplete or reordered")
    cases = report.get("cases")
    _require(isinstance(cases, Mapping) and set(cases) == set(EXPECTED_REGISTERED_CASES),
             "A8_REGISTERED_DENOMINATOR", f"{label} case rows do not close the registered denominator")
    full_horizon = report.get("full_horizon")
    _require(isinstance(full_horizon, Mapping)
             and full_horizon.get("trajectory_frames") == {
                 EXPECTED_CASE: EXPECTED_REGISTERED_TRAJECTORY_FRAMES
             },
             "A8_FRAME_DENOMINATOR", f"{label} full-horizon denominator is incomplete")
    _require(report.get("manifest_sha256") == EXPECTED_MANIFEST,
             "A8_IDENTITY_MISMATCH", f"{label} manifest identity is unexpected")
    for key in ("checkpoint_sha256", "bundle_sha256"):
        _sha(report.get(key), role=f"{label} {key}")
    _require(report.get("model_kind") == "mlp" and report.get("seed") == 17
             and report.get("hidden") == 64, "A8_IDENTITY_MISMATCH",
             f"{label} model identity is unexpected")

    row = cases[EXPECTED_CASE]
    _require(isinstance(row, Mapping) and row.get("case_id") == EXPECTED_CASE,
             "A8_CASE_ROW", f"{label} case row is malformed")
    rollout = row.get("rollout")
    _require(isinstance(rollout, Mapping), "A8_CASE_ROLLOUT", f"{label} rollout is missing")
    for key in ("expected_frames", "frames_expected", "frames_executed", "frames_predicted"):
        _require(rollout.get(key) == EXPECTED_REGISTERED_TRANSITIONS, "A8_FRAME_DENOMINATOR",
                 f"{label} rollout {key} does not retain the registered horizon")
    for key in ("executed", "execution_complete", "finite_rollout_complete", "autonomous"):
        _require(rollout.get(key) is True, "A8_CASE_ROLLOUT", f"{label} rollout {key} is not true")
    _require(rollout.get("future_state_inputs") is False
             and rollout.get("failure_category") is None
             and rollout.get("first_failure_frame") is None
             and rollout.get("particles") == EXPECTED_PARTICLES,
             "A8_CASE_ROLLOUT", f"{label} rollout carries an invalid completion contract")

    score = row.get("score")
    _require(isinstance(score, Mapping)
             and score.get("expected_frames") == EXPECTED_REGISTERED_TRANSITIONS
             and score.get("finite_prefix_frames") == EXPECTED_REGISTERED_TRANSITIONS
             and score.get("executed") is True and score.get("complete") is True
             and score.get("failure_category") is None
             and score.get("first_failure_frame") is None
             and score.get("raw_error_coverage") == 1.0,
             "A8_SCORE_DENOMINATOR", f"{label} score row does not close the registered horizon")
    _require(isinstance(score.get("selection_score"), (int, float))
             and not isinstance(score.get("selection_score"), bool)
             and 0 <= float(score["selection_score"]) <= 1,
             "A8_SCORE_INVALID", f"{label} score row is not finite")

    artifacts = execution_artifacts
    score_artifact = _validate_report_artifact(
        report, report.get("score_artifact", {}), report_path=report_path,
        label=f"{label} score", execution_artifacts=artifacts, cache=cache)
    trajectory_artifact = _validate_report_artifact(
        report, row.get("trajectory", {}), report_path=report_path,
        label=f"{label} trajectory", execution_artifacts=artifacts, cache=cache)
    progress_artifact = _validate_report_artifact(
        report, row.get("progress", {}), report_path=report_path,
        label=f"{label} progress", execution_artifacts=artifacts, cache=cache)
    verification_cases = verification.get("cases")
    _require(isinstance(verification_cases, list) and len(verification_cases) == 1,
             "A8_VERIFICATION_DENOMINATOR", f"{label} verification case denominator is incomplete")
    verification_case = verification_cases[0]
    _require(isinstance(verification_case, Mapping)
             and verification_case.get("case_id") == EXPECTED_CASE
             and verification_case.get("full_particle_axis") is True,
             "A8_VERIFICATION_DENOMINATOR", f"{label} verification case is not registered")
    _require(report.get("full_horizon_reproduction") is True and report.get("passed") is True,
             "A8_TERMINAL_SELF_REPORT", f"{label} terminal status disagrees with its verified facts")
    return {
        "case_ids": list(EXPECTED_REGISTERED_CASES),
        "expected_frames": dict(EXPECTED_REGISTERED_FRAMES),
        "score_path": score_artifact["path"],
        "trajectory_path": trajectory_artifact["path"],
        "progress_path": progress_artifact["path"],
        "report_identity": {key: report.get(key) for key in (
            "dataset_id", "manifest_sha256", "checkpoint_sha256", "bundle_sha256",
            "model_kind", "seed", "hidden")},
        "code_closure_sha256": report.get("code", {}).get("closure_sha256")
        if isinstance(report.get("code"), Mapping) else None,
        "score": score,
    }


def validate_a8_pair(*, ada_report: Mapping[str, Any], h200_report: Mapping[str, Any],
                     comparison: Mapping[str, Any], root_review: Mapping[str, Any],
                     ada_report_path: Path, h200_report_path: Path,
                     comparison_path: Path, root_review_path: Path,
                     host_pair: Mapping[str, Any], root: Path,
                     cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    """Require paired terminal evidence from independently verified artifacts."""
    ada_execution = comparison.get("executions", {}).get("ada")
    h200_execution = comparison.get("executions", {}).get("h200")
    ada_execution_info = _validate_execution_artifacts(
        ada_execution, report_path=ada_report_path, root=root, label="ada", cache=cache)
    h200_execution_info = _validate_execution_artifacts(
        h200_execution, report_path=h200_report_path, root=root, label="h200", cache=cache)
    ada_info = _validate_a8_terminal(
        ada_report, report_path=ada_report_path,
        execution_artifacts=ada_execution_info["artifacts"], label="ada",
        own_host=host_pair["ada"], other_host=host_pair["h200"], cache=cache)
    h200_info = _validate_a8_terminal(
        h200_report, report_path=h200_report_path,
        execution_artifacts=h200_execution_info["artifacts"], label="h200",
        own_host=host_pair["h200"], other_host=host_pair["ada"], cache=cache)

    _require(ada_info["report_identity"] == h200_info["report_identity"],
             "A8_IDENTITY_MISMATCH", "Ada/H200 terminal reports bind different model identities")
    _require(ada_info["code_closure_sha256"] == h200_info["code_closure_sha256"]
             and isinstance(ada_info["code_closure_sha256"], str),
             "A8_IDENTITY_MISMATCH", "Ada/H200 code closures differ")

    _require(comparison.get("schema") == A8_COMPARISON_SCHEMA,
             "A8_COMPARISON_SCHEMA", "A8 paired comparison schema is unsupported")
    _require(comparison.get("status") == "passed", "A8_COMPARISON_STATUS",
             "A8 paired comparison is not a completed comparison")
    hosts = comparison.get("hosts")
    expected_hosts = {
        "ada_report_host": ada_report.get("reproduction_host"),
        "ada_source_host": ada_report.get("source_host"),
        "h200_report_host": h200_report.get("reproduction_host"),
        "h200_source_host": h200_report.get("source_host"),
        "observed_hosts": sorted([ada_report["reproduction_host"],
                                   h200_report["reproduction_host"]]),
    }
    _require(
        hosts == {**expected_hosts, "distinct_host_evidence": True},
        "A8_HOST_BINDING",
        "comparison host fields are self-reported or stale",
    )
    block = comparison.get("comparison")
    _require(isinstance(block, Mapping), "A8_COMPARISON_PAYLOAD", "A8 comparison payload is missing")
    _require(block.get("schema") == "core.model_reproduction.comparison.v1",
             "A8_COMPARISON_SCHEMA", "A8 comparison payload schema is unsupported")
    _require(block.get("status") == "compared", "A8_COMPARISON_STATUS",
             "A8 paired comparison payload is not a completed comparison")
    _require(block.get("observed_hosts") == expected_hosts["observed_hosts"],
             "A8_HOST_BINDING", "A8 comparison observed hosts are not bound")
    paired_report = block.get("paired_report")
    _require(isinstance(paired_report, str) and paired_report
             and Path(paired_report).resolve() == h200_report_path.resolve(), "A8_REPORT_BINDING",
             "A8 comparison paired report is not the supplied H200 report")

    scope = comparison.get("scope")
    expected_scope = {
        "all_particle_axis": True, "case_id": EXPECTED_CASE, "diagnostic_only": True,
        "family": "F3", "formal_training_count": 0, "full_horizon": True,
        "particle_count": EXPECTED_PARTICLES, "scientific_qualification": False,
        "split": "validation", "trajectory_frames": EXPECTED_REGISTERED_TRAJECTORY_FRAMES,
        "transitions": EXPECTED_REGISTERED_TRANSITIONS,
    }
    _require(scope == expected_scope, "A8_REGISTERED_DENOMINATOR",
             "A8 comparison scope does not close the registered denominator")
    _require(comparison.get("identity", {}).get("identity_equal") is True,
             "A8_IDENTITY_MISMATCH", "A8 comparison identity is not equal")
    for key in ("manifest_sha256", "checkpoint_sha256", "bundle_sha256", "model_kind", "seed", "hidden"):
        _require(comparison.get("identity", {}).get(key) == ada_info["report_identity"].get(key),
                 "A8_IDENTITY_MISMATCH", f"A8 comparison identity differs for {key}")
    _sha(comparison.get("identity", {}).get("code_closure_sha256"), role="A8 comparison code closure")
    _require(comparison["identity"]["code_closure_sha256"] == ada_info["code_closure_sha256"],
             "A8_IDENTITY_MISMATCH", "A8 comparison code closure is stale")

    score_path_key = (str(ada_info["score_path"]), str(h200_info["score_path"]))
    trajectory_path_key = (str(ada_info["trajectory_path"]), str(h200_info["trajectory_path"]))
    score_ids = (_file_identity(ada_info["score_path"], cache)["sha256"],
                 _file_identity(h200_info["score_path"], cache)["sha256"])
    trajectory_ids = (_file_identity(ada_info["trajectory_path"], cache)["sha256"],
                      _file_identity(h200_info["trajectory_path"], cache)["sha256"])
    cache_key = (score_ids[0], score_ids[1], trajectory_ids[0], trajectory_ids[1])
    if cache_key not in _PAIR_COMPARISON_CACHE:
        from scripts import core_reproduction_check
        score_result = core_reproduction_check.compare_scores(
            ada_info["score_path"], h200_info["score_path"],
            expected_frames=EXPECTED_REGISTERED_TRANSITIONS)
        trajectory_result = core_reproduction_check.compare(
            ada_info["trajectory_path"], h200_info["trajectory_path"],
            expected_frames=EXPECTED_REGISTERED_TRAJECTORY_FRAMES)
        _PAIR_COMPARISON_CACHE[cache_key] = (score_result, trajectory_result)
    score_result, trajectory_result = _PAIR_COMPARISON_CACHE[cache_key]
    _require(score_result.get("passed") is True and trajectory_result.get("passed") is True,
             "A8_PAIRED_COMPARISON_FAILED", "independent artifact comparison did not pass")
    reported_score = block.get("score")
    reported_trajectory = block.get("trajectory")
    _require(reported_score == score_result and reported_trajectory == {EXPECTED_CASE: trajectory_result},
             "A8_COMPARISON_SELF_REPORT", "comparison summary does not match independently computed artifacts")
    _require(block.get("passed") is True and block.get("distinct_host_evidence") is True,
             "A8_PAIRED_COMPARISON_FAILED", "A8 paired comparison lacks an explicit pass")
    headline = comparison.get("headline")
    _require(isinstance(headline, Mapping), "A8_COMPARISON_SELF_REPORT", "comparison headline is missing")
    score_case = score_result["cases"][EXPECTED_CASE]
    _require(headline.get("absolute_score_difference") == score_case["absolute_score_difference"]
             and headline.get("score_left_ada") == score_case["left"]["selection_score"]
             and headline.get("score_right_h200") == score_case["right"]["selection_score"]
             and headline.get("maximum_position_absolute_difference_m")
             == trajectory_result["maximum_absolute_difference"]["position"]
             and headline.get("maximum_velocity_absolute_difference_mps")
             == trajectory_result["maximum_absolute_difference"]["velocity"]
             and headline.get("physics_and_failure_categories_passed") is True
             and headline.get("passed") is True,
             "A8_COMPARISON_SELF_REPORT", "comparison headline is not independently bound")

    _require(root_review.get("schema") == ROOT_REVIEW_SCHEMA,
             "A8_ROOT_REVIEW_SCHEMA", "A8 root review schema is unsupported")
    _require(_sha(root_review.get("receipt_sha256"), role="A8 root review receipt")
             == sha256_file(comparison_path), "A8_ROOT_REVIEW_RECEIPT",
             "A8 root review is not bound to the supplied comparison receipt")
    _require(root_review.get("registered_comparison_pass") is True
             and root_review.get("two_terminal_reports_verified") is True
             and root_review.get("all_eight_required_outputs_verified") is True,
             "A8_ROOT_REVIEW_UNVERIFIED", "A8 root review did not verify the complete pair")
    _require(root_review.get("diagnostic_only") is True
             and root_review.get("formal_training_count") == 0
             and root_review.get("full_core_reproduction_proven") is False,
             "A8_ROOT_REVIEW_SCOPE", "A8 root review carries a formal/product claim")
    root_scope = root_review.get("scope")
    _require(root_scope == {"all_particle_axis": True, "case_id": EXPECTED_CASE,
                            "diagnostic_only": True, "family": "F3",
                            "formal_training_count": 0, "full_horizon": True,
                            "particle_count": EXPECTED_PARTICLES,
                            "scientific_qualification": False, "split": "validation",
                            "trajectory_frames": EXPECTED_REGISTERED_TRAJECTORY_FRAMES,
                            "transitions": EXPECTED_REGISTERED_TRANSITIONS},
             "A8_REGISTERED_DENOMINATOR", "A8 root review scope is incomplete")
    _require(root_review.get("headline") == headline, "A8_ROOT_REVIEW_SELF_REPORT",
             "A8 root review headline is not bound to the comparison")
    return {
        "paired_comparison_pass": True, "distinct_host_evidence": True,
        "observed_hosts": expected_hosts["observed_hosts"],
        "transitions": EXPECTED_REGISTERED_TRANSITIONS,
        "diagnostic_only": True, "formal_training_count": 0,
    }


def _validate_metadata(metadata_root: Path) -> dict[str, Any]:
    """Validate the lightweight fallback bundle by content, never by path."""
    dataset = metadata_root / "dataset.json"
    checkpoint = metadata_root / "models" / "checkpoint-001.pt"
    models = metadata_root / "code" / "scripts" / "core_models.py"
    for path in (dataset, checkpoint, models):
        _require(path.is_file(), "BUNDLE_METADATA_MISSING", f"metadata fallback missing: {path}")
    hashes = {"manifest": sha256_file(dataset), "checkpoint": sha256_file(checkpoint),
              "core_models": sha256_file(models)}
    expected = {"manifest": EXPECTED_MANIFEST, "checkpoint": EXPECTED_CHECKPOINT,
                "core_models": EXPECTED_MODELS}
    _require(hashes == expected, "BUNDLE_METADATA_HASH_MISMATCH",
             f"metadata fallback identity differs: {hashes}")
    return {"root": str(metadata_root.resolve()), "identity": hashes,
            "execution_role": "identity_fallback_only"}


def build_review(*, root: str | Path, ada_record: str | Path, h200_record: str | Path,
                 ada_spec: str | Path, h200_spec: str | Path,
                 ada_canary: str | Path, h200_canary: str | Path,
                 canary_comparison: str | Path,
                 a8_ada_report: str | Path, a8_h200_report: str | Path,
                 a8_comparison: str | Path, a8_root_review: str | Path,
                 metadata_root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    inputs: dict[str, tuple[dict[str, Any], Path]] = {}
    for label, path in (
        ("ada_record", ada_record), ("h200_record", h200_record),
        ("ada_spec", ada_spec), ("h200_spec", h200_spec),
        ("ada_canary", ada_canary), ("h200_canary", h200_canary),
        ("canary_comparison", canary_comparison),
        ("a8_ada_report", a8_ada_report), ("a8_h200_report", a8_h200_report),
        ("a8_comparison", a8_comparison), ("a8_root_review", a8_root_review),
    ):
        inputs[label] = _load_json(path)

    host_pair = validate_host_pair(inputs["ada_record"][0], inputs["h200_record"][0])
    specs = {
        "ada": validate_canary_spec(inputs["ada_spec"][0], label="ada"),
        "h200": validate_canary_spec(inputs["h200_spec"][0], label="h200"),
    }
    _require(specs["ada"]["identity"] == specs["h200"]["identity"],
             "CANARY_SPEC_IDENTITY_MISMATCH", "Ada/H200 canary specs bind different identities")
    ada_gpu = inputs["ada_canary"][0]["environment"]["cuda_visible_devices"]
    h200_gpu = inputs["h200_canary"][0]["environment"]["cuda_visible_devices"]
    canary_terminals = {
        "ada": validate_canary(inputs["ada_canary"][0], label="ada",
                                expected_hostname=host_pair["ada"]["hostname"],
                                expected_gpu_uuid=ada_gpu),
        "h200": validate_canary(inputs["h200_canary"][0], label="h200",
                                 expected_hostname=host_pair["h200"]["hostname"],
                                 expected_gpu_uuid=h200_gpu),
    }
    _require(ada_gpu != h200_gpu, "GPU_IDENTITY_COLLISION",
             "two canary receipts selected the same physical GPU UUID")
    _require(ada_gpu in host_pair["ada"]["gpu_uuids"], "CANARY_GPU_UNBOUND",
             "Ada canary GPU UUID is absent from its environment probe")
    _require(h200_gpu in host_pair["h200"]["gpu_uuids"], "CANARY_GPU_UNBOUND",
             "H200 canary GPU UUID is absent from its environment probe")
    canary_pair = validate_canary_comparison(inputs["canary_comparison"][0])
    artifact_cache: dict[Path, dict[str, Any]] = {}
    a8_pair = validate_a8_pair(
        ada_report=inputs["a8_ada_report"][0], h200_report=inputs["a8_h200_report"][0],
        comparison=inputs["a8_comparison"][0], root_review=inputs["a8_root_review"][0],
        ada_report_path=inputs["a8_ada_report"][1], h200_report_path=inputs["a8_h200_report"][1],
        comparison_path=inputs["a8_comparison"][1], root_review_path=inputs["a8_root_review"][1],
        host_pair=host_pair, root=root_path, cache=artifact_cache)
    metadata = _validate_metadata(Path(metadata_root).expanduser().resolve())
    evidence = {label: _ref(path, root_path) for label, (_, path) in inputs.items()}
    evidence["metadata_bundle"] = _ref(Path(metadata_root).expanduser().resolve() / "bundle.json", root_path)
    return {
        "schema": SCHEMA,
        "status": "pass",
        "review_id": "a8-cross-host-frontier-20260920-v1",
        "decision": {
            "true_cross_host_canary": True,
            "full_horizon_paired_diagnostic": True,
            "full_product_reproduction": False,
            "scientific_qualification": False,
            "formal_training_admission": False,
            "formal_training_count": 0,
        },
        "host_pair": host_pair,
        "canary": {
            "protocol": "core.cross_host_canary.float64.v1",
            "case_id": EXPECTED_CASE,
            "steps": EXPECTED_STEPS,
            "frames": EXPECTED_FRAMES,
            "particle_count": EXPECTED_PARTICLES,
            "specs": specs,
            "terminals": canary_terminals,
            "paired_comparison": canary_pair,
        },
        "a8_full_horizon": a8_pair,
        "identity": {
            "manifest_sha256": EXPECTED_MANIFEST,
            "checkpoint_sha256": EXPECTED_CHECKPOINT,
            "core_models_sha256": EXPECTED_MODELS,
            "metadata_fallback": metadata,
        },
        "execution_constraints": {
            "read_only": True,
            "formal_runs_started": 0,
            "formal_specs_written": False,
            "submitted": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
        },
        "evidence": evidence,
        "interpretation": (
            "A real Ada/H200 pair is verified by physical hostnames, disjoint GPU UUIDs, "
            "matched package/module hashes, and paired outputs. The 20-step float64 canary "
            "is a diagnostic arithmetic check. The 835-transition A8 pair is a diagnostic "
            "full-horizon reproduction; neither evidence admits formal training or a product release."
        ),
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    _require(not target.exists(), "IMMUTABLE_OUTPUT_EXISTS", f"review output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ada-record", type=Path, required=True)
    parser.add_argument("--h200-record", type=Path, required=True)
    parser.add_argument("--ada-spec", type=Path, required=True)
    parser.add_argument("--h200-spec", type=Path, required=True)
    parser.add_argument("--ada-canary", type=Path, required=True)
    parser.add_argument("--h200-canary", type=Path, required=True)
    parser.add_argument("--canary-comparison", type=Path, required=True)
    parser.add_argument("--a8-ada-report", type=Path, required=True)
    parser.add_argument("--a8-h200-report", type=Path, required=True)
    parser.add_argument("--a8-comparison", type=Path, required=True)
    parser.add_argument("--a8-root-review", type=Path, required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_review(
            root=args.root, ada_record=args.ada_record, h200_record=args.h200_record,
            ada_spec=args.ada_spec, h200_spec=args.h200_spec,
            ada_canary=args.ada_canary, h200_canary=args.h200_canary,
            canary_comparison=args.canary_comparison,
            a8_ada_report=args.a8_ada_report, a8_h200_report=args.a8_h200_report,
            a8_comparison=args.a8_comparison, a8_root_review=args.a8_root_review,
            metadata_root=args.metadata_root,
        )
    except (OSError, json.JSONDecodeError, ReviewError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "blocked",
                          "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 2
    write_json(args.output, report)
    print(json.dumps({"schema": report["schema"], "status": report["status"],
                      "true_cross_host_canary": report["decision"]["true_cross_host_canary"],
                      "formal_training_count": report["decision"]["formal_training_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
