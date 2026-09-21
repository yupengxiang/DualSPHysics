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
EXPECTED_MANIFEST = "8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680"
EXPECTED_CHECKPOINT = "9af1dc3cb68991c38fd31b59d92895326e3abe89d5d29d33dd086d7fa462b8a8"
EXPECTED_MODELS = "73a98b262500c30e46f14aafd2a89f2bea34116c77b6e34ce5e33e7412c38c77"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
        relative = str(path.resolve())
    return {"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ReviewError(code, message)


def _sha(value: Any, *, role: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
             "INVALID_HASH", f"{role} is not a SHA-256 string")
    return value.lower()


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


def validate_a8_pair(*, ada_report: Mapping[str, Any], h200_report: Mapping[str, Any],
                     comparison: Mapping[str, Any], root_review: Mapping[str, Any]) -> dict[str, Any]:
    """Require paired terminal A8 evidence; reject single-host semantics."""
    for label, report, expected_reproduction in (
        ("ada", ada_report, "user-SYS-421GE-TNRT"),
        ("h200", h200_report, "h200"),
    ):
        _require(report.get("schema") == A8_TERMINAL_SCHEMA, "A8_TERMINAL_SCHEMA",
                 f"{label} A8 terminal report schema is unsupported")
        _require(report.get("passed") is True and report.get("full_horizon_reproduction") is True,
                 "A8_TERMINAL_INCOMPLETE", f"{label} A8 terminal report is incomplete")
        _require(report.get("reproduction_host") == expected_reproduction,
                 "A8_TERMINAL_HOST_MISMATCH", f"{label} A8 reproduction host is unexpected")
        _require(report.get("cross_host_reproduction") is False,
                 "A8_TERMINAL_SINGLE_HOST_MARKER", f"{label} terminal report must remain single-host")
        _require(report.get("full_product_reproduction") is False,
                 "A8_TERMINAL_PRODUCT_MARKER", f"{label} terminal report is marked product-complete")
        _require(report.get("predictor_future_state_inputs") is False,
                 "A8_TERMINAL_FUTURE_STATE", f"{label} terminal report used future states")
    _require(comparison.get("schema") == A8_COMPARISON_SCHEMA,
             "A8_COMPARISON_SCHEMA", "A8 paired comparison schema is unsupported")
    block = comparison.get("comparison", {})
    _require(block.get("passed") is True and block.get("distinct_host_evidence") is True,
             "A8_PAIRED_COMPARISON_FAILED", "A8 paired comparison lacks distinct-host pass")
    hosts = block.get("observed_hosts", [])
    _require(isinstance(hosts, list) and len(set(hosts)) == 2,
             "A8_HOST_PAIR_INCOMPLETE", "A8 comparison does not contain two physical hosts")
    _require(root_review.get("schema") == ROOT_REVIEW_SCHEMA,
             "A8_ROOT_REVIEW_SCHEMA", "A8 root review schema is unsupported")
    _require(root_review.get("registered_comparison_pass") is True
             and root_review.get("two_terminal_reports_verified") is True,
             "A8_ROOT_REVIEW_UNVERIFIED", "A8 root review did not verify both terminal reports")
    _require(root_review.get("diagnostic_only") is True
             and root_review.get("formal_training_count") == 0
             and root_review.get("full_core_reproduction_proven") is False,
             "A8_ROOT_REVIEW_SCOPE", "A8 root review carries a formal/product claim")
    scope = root_review.get("scope", {})
    _require(scope.get("full_horizon") is True and scope.get("transitions") == 835,
             "A8_ROOT_REVIEW_HORIZON", "A8 root review does not bind the 835-transition horizon")
    return {
        "paired_comparison_pass": True, "distinct_host_evidence": True,
        "observed_hosts": list(hosts), "transitions": 835,
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
    a8_pair = validate_a8_pair(
        ada_report=inputs["a8_ada_report"][0], h200_report=inputs["a8_h200_report"][0],
        comparison=inputs["a8_comparison"][0], root_review=inputs["a8_root_review"][0])
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
