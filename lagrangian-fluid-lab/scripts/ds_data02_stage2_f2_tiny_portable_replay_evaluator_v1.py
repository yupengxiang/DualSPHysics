#!/usr/bin/env python3
"""Run a bounded, manufactured portable replay through the real JSON evaluator.

This is a development-interface probe for the F2 portable chain.  It copies a
small producer input and the frozen observer evaluator into a fresh attempt
root, runs a real producer subprocess, and then invokes the existing
``no_model_observer_evaluator_v2.py`` ``build-profile``, ``observe`` and
``score`` commands in fresh interpreters.  It records source pre/post
signatures, target hashes, process cleanup and old-root poison checks.

The input is intentionally a tiny manufactured typed trajectory.  The report
is ``fixture_only`` and keeps QI/QN/QE UNKNOWN; it cannot establish a raw
anchor, a native reconstruction, or a portable scientific product.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
OBSERVER = SCRIPT_DIR / "ds_data02_stage2_no_model_observer_evaluator_v2.py"
REQUEST_SCHEMA = "ds02.stage2.f2-tiny-portable-replay-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-tiny-portable-replay-report.v1"
INPUT_SCHEMA = "ds02.stage2.f2-tiny-producer-input.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 10 * 1024 * 1024


class TinyReplayError(RuntimeError):
    """Raised for a source, relocation, subprocess, or evaluator mismatch."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise TinyReplayError(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise TinyReplayError(f"{role} exceeds the bounded metadata limit")
    return target


def _json(path: Path | str, role: str) -> dict[str, Any]:
    target = _regular(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TinyReplayError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise TinyReplayError(f"{role} must be a JSON object")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise TinyReplayError(f"{name} must be a lowercase SHA-256")
    return value


def _stat(path: Path | str) -> dict[str, int]:
    target = _regular(path, "stat target")
    value = target.stat()
    return {
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "st_size": int(value.st_size),
        "st_mtime_ns": int(value.st_mtime_ns),
        "st_ctime_ns": int(value.st_ctime_ns),
        "mode_bits": int(value.st_mode & 0o777),
    }


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise TinyReplayError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True,
                                 ensure_ascii=False, allow_nan=False) + "\n",
                      encoding="utf-8")
    return target


def _source_entry(role: str, path: Path, target_relative_path: str) -> dict[str, Any]:
    path = _regular(path, role)
    return {
        "role": role,
        "source_path_provenance": str(path),
        "source_sha256": sha256_file(path),
        "source_stat": _stat(path),
        "target_relative_path": target_relative_path,
        "actionable": True,
        "content_read_by_builder": True,
    }


def _validate_input_shape(value: Mapping[str, Any]) -> None:
    if value.get("schema") != INPUT_SCHEMA:
        raise TinyReplayError("producer input schema differs")
    for key in ("query_times_s", "identity", "initial_mass_kg", "positions_m", "velocities_m_s", "valid"):
        if key not in value:
            raise TinyReplayError(f"producer input lacks {key}")
    if not isinstance(value["query_times_s"], list) or not value["query_times_s"]:
        raise TinyReplayError("producer query_times_s must be nonempty")
    if not isinstance(value["identity"], list) or not value["identity"]:
        raise TinyReplayError("producer identity must be nonempty")


def build_request(*, producer_input: Path, observer_script: Path = OBSERVER,
                  output: Path, fresh_root: Path, old_root: Path) -> dict[str, Any]:
    source = _regular(producer_input, "producer input")
    input_value = _json(source, "producer input")
    _validate_input_shape(input_value)
    evaluator = _regular(observer_script, "observer evaluator")
    fresh = Path(fresh_root).expanduser().resolve()
    old = Path(old_root).expanduser().resolve()
    if fresh.exists():
        raise TinyReplayError(f"fresh attempt root already exists: {fresh}")
    if fresh == old or _inside(fresh, old) or _inside(old, fresh):
        raise TinyReplayError("fresh and old roots overlap")
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "fixture_only": True,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "case_id": "F2_TINY_PORTABLE_REPLAY_FIXTURE",
        "attempt_id": fresh.name,
        "fresh_namespace": {"root": str(fresh), "must_be_new": True},
        "original_roots": [str(old)],
        "source_fallback": "REJECT",
        "copy_roles": [
            _source_entry("producer_input", source, "inputs/producer-input.json"),
            _source_entry("observer_evaluator", evaluator, "runtime/observer-evaluator.py"),
            _source_entry("chain_runner", SCRIPT, "runtime/tiny-chain-runner.py"),
        ],
        "execution": {
            "python_executable": str(Path(sys.executable).expanduser().resolve()),
            "python_argv0_policy": "literal_pinned_interpreter",
            "max_wall_seconds": 30.0,
            "max_output_bytes": 65536,
            "threads": 1,
            "source_content_read_phase": "after_parent_reservation",
            "old_root_open": "FORBIDDEN",
        },
        "chain": {
            "producer": "real subprocess producer command",
            "profile": "real observer evaluator build-profile command",
            "replay": "real observer evaluator observe command",
            "evaluator": "real observer evaluator score command",
            "independent_verifier": "this script verify-report",
        },
        "limitations": [
            "Manufactured tiny trajectory only; no raw/native/HDF5/BI4 payload is read.",
            "Fixture-only operator score; QI/QN/QE and physical equivalence remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    _write_new(output, request)
    return request


def _check_request(request: Mapping[str, Any]) -> tuple[Path, Path, list[dict[str, Any]], Path]:
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise TinyReplayError("request schema/canonical SHA differs")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("fixture_only") is not True:
        raise TinyReplayError("request is not a fixture-only parent-ready request")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise TinyReplayError("request model/CFD boundary is unsafe")
    if request.get("qualification") != UNKNOWN or request.get("source_fallback") != "REJECT":
        raise TinyReplayError("request qualification or fallback boundary is unsafe")
    roots = request.get("fresh_namespace")
    if not isinstance(roots, Mapping) or not isinstance(roots.get("root"), str):
        raise TinyReplayError("fresh namespace is missing")
    fresh = Path(roots["root"]).expanduser().resolve()
    if fresh.exists():
        raise TinyReplayError(f"fresh namespace is not new: {fresh}")
    old_roots = request.get("original_roots")
    if not isinstance(old_roots, list) or not old_roots or any(not isinstance(item, str) for item in old_roots):
        raise TinyReplayError("original_roots are missing")
    entries = request.get("copy_roles")
    if not isinstance(entries, list) or len(entries) != 3:
        raise TinyReplayError("exactly three copy roles are required")
    for item in entries:
        if not isinstance(item, Mapping):
            raise TinyReplayError("copy role is malformed")
        source = _regular(item.get("source_path_provenance"), str(item.get("role")))
        if sha256_file(source) != _sha(item.get("source_sha256"), f"{item.get('role')}.source_sha256"):
            raise TinyReplayError(f"source changed before reservation: {item.get('role')}")
        if item.get("source_stat") != _stat(source):
            raise TinyReplayError(f"source stat changed before reservation: {item.get('role')}")
        target = item.get("target_relative_path")
        if not isinstance(target, str) or not target or Path(target).is_absolute() or ".." in Path(target).parts:
            raise TinyReplayError(f"unsafe target path for {item.get('role')}")
    evaluator = next((item for item in entries if item.get("role") == "observer_evaluator"), None)
    producer = next((item for item in entries if item.get("role") == "producer_input"), None)
    chain = next((item for item in entries if item.get("role") == "chain_runner"), None)
    if evaluator is None or producer is None or chain is None:
        raise TinyReplayError("required producer/evaluator/chain roles are missing")
    return fresh, Path(old_roots[0]).expanduser().resolve(), [dict(producer), dict(evaluator), dict(chain)], _regular(evaluator["source_path_provenance"], "observer evaluator")


def _run_child(argv: Sequence[str], *, cwd: Path, timeout: float, old_roots: Sequence[Path]) -> dict[str, Any]:
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    process = subprocess.Popen(list(argv), cwd=str(cwd), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, env=env)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2.0)
        raise
    text_blob = (stdout + "\n" + stderr)
    for root in old_roots:
        if str(root) in text_blob:
            raise TinyReplayError(f"child exposed forbidden original root: {root}")
    if len(stdout.encode()) + len(stderr.encode()) > 65536:
        raise TinyReplayError("child output exceeded bounded log contract")
    if process.returncode != 0:
        raise TinyReplayError(f"child failed rc={process.returncode}: {stderr[-2048:]}")
    return {"returncode": process.returncode, "stdout": stdout[-4096:],
            "stderr": stderr[-4096:], "stdout_bytes": len(stdout.encode()),
            "stderr_bytes": len(stderr.encode())}


def _copy_role(item: Mapping[str, Any], fresh: Path) -> dict[str, Any]:
    source = _regular(item["source_path_provenance"], str(item["role"]))
    pre_sha = sha256_file(source)
    pre_stat = _stat(source)
    target = (fresh / str(item["target_relative_path"])).resolve()
    if not _inside(target, fresh) or target.exists():
        raise TinyReplayError(f"unsafe or existing copied target: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target_sha = sha256_file(target)
    target_stat = _stat(target)
    post_sha = sha256_file(source)
    post_stat = _stat(source)
    if pre_sha != post_sha or pre_stat != post_stat:
        raise TinyReplayError(f"source changed while copying: {item['role']}")
    if target_sha != pre_sha or target_stat["st_size"] != pre_stat["st_size"]:
        raise TinyReplayError(f"copied target differs: {item['role']}")
    return {"role": item["role"], "source_sha256": pre_sha,
            "target_sha256": target_sha, "source_pre_stat": pre_stat,
            "source_post_stat": post_stat, "target_stat": target_stat,
            "target_path": str(target), "target_relative_path": item["target_relative_path"],
            "source_content_unchanged": True}


def _fixture_config(input_path: Path) -> dict[str, Any]:
    stat = _stat(input_path)
    entry = {"path": str(input_path), "bytes": stat["st_size"],
             "mtime_ns": stat["st_mtime_ns"], "sha256": sha256_file(input_path)}
    return {
        "profile_id": "f2-tiny-portable-replay-fixture-profile",
        "query_times_s": [0.0, 1.0],
        "observers": ["mass_weighted_com_m", "mean_velocity_m_s", "kinetic_energy_j",
                       "mass_quantile_front_m", "mass_distribution_fraction",
                       "observed_mass_fraction", "velocity_missing_mass_fraction"],
        "physical_scales": {"position_m": 1.0, "velocity_m_s": 1.0,
                             "kinetic_energy_j": 1.0, "feature_time_s": 1.0,
                             "mass_kg": 6.0},
        "tolerances": {"position_relative": 0.02, "velocity_relative": 0.02,
                       "kinetic_energy_relative": 0.02, "mass_fraction_absolute": 0.03},
        "budget_fraction_of_total_error": {"integration_time": 0.25, "output_sampling": 0.25},
        "mass_distribution_bins_m": [0.5, 1.0], "mass_quantile": 0.5,
        "source_binding": {"current_catalog": entry, "trajectory_h5": entry, "producer_input": entry},
    }


def _make_prediction(profile_path: Path, observed_path: Path, output: Path) -> None:
    profile = _json(profile_path, "profile")
    observed = _json(observed_path, "observed report")
    if observed.get("status") != "OBSERVED_DEVELOPMENT_JSON":
        raise TinyReplayError("observer report is not complete")
    body = observed.get("observers")
    if not isinstance(body, Mapping) or not isinstance(body.get("meta"), Mapping):
        raise TinyReplayError("observer report lacks observed meta")
    prediction = {
        "schema": "ds02.stage2.no-model-observer-prediction.v2",
        "profile_sha256": profile["sha256"],
        "query_times_s": profile["query_times_s"],
        "identity": body["meta"]["identity"],
        "observers": {name: body[name] for name in profile["observers"]},
        "budget_fraction_of_total_error": profile["budget_fraction_of_total_error"],
    }
    _write_new(output, prediction)


def run_request(request_path: Path, *, output: Path, parent_pid: int | None = None) -> dict[str, Any]:
    request = _json(request_path, "tiny replay request")
    fresh, old_root, roles, _ = _check_request(request)
    if parent_pid is None:
        parent_pid = os.getppid()
    if isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 1:
        raise TinyReplayError("parent_pid must be a live positive integer")
    if fresh.exists():
        raise TinyReplayError(f"fresh root already exists: {fresh}")
    output = Path(output).expanduser().resolve()
    if not _inside(output, fresh) or output.exists():
        raise TinyReplayError("report output must be a new path inside the fresh root")
    fresh.mkdir(parents=True)
    copied: list[dict[str, Any]] = []
    try:
        for role in roles:
            copied.append(_copy_role(role, fresh))
        target_input = fresh / "inputs/producer-input.json"
        target_evaluator = fresh / "runtime/observer-evaluator.py"
        target_chain = fresh / "runtime/tiny-chain-runner.py"
        products = fresh / "products"
        reports = fresh / "reports"
        products.mkdir()
        reports.mkdir()
        target_trajectory = products / "trajectory.json"
        producer_argv = [sys.executable, "-B", "-I", str(target_chain), "producer",
                         "--input", str(target_input), "--output", str(target_trajectory)]
        producer_run = _run_child(producer_argv, cwd=fresh, timeout=10.0, old_roots=[old_root])
        config_path = reports / "observer-config.json"
        _write_new(config_path, _fixture_config(target_input))
        profile_path = reports / "profile.json"
        profile_run = _run_child([sys.executable, "-B", "-I", str(target_evaluator),
                                  "build-profile", "--config", str(config_path),
                                  "--output", str(profile_path)], cwd=fresh, timeout=10.0,
                                 old_roots=[old_root])
        observed_path = reports / "observed.json"
        observe_run = _run_child([sys.executable, "-B", "-I", str(target_evaluator),
                                  "observe", "--profile", str(profile_path),
                                  "--trajectory", str(target_trajectory),
                                  "--output", str(observed_path), "--verify-sources"],
                                 cwd=fresh, timeout=10.0, old_roots=[old_root])
        prediction_path = reports / "prediction.json"
        _make_prediction(profile_path, observed_path, prediction_path)
        score_path = reports / "score.json"
        score_run = _run_child([sys.executable, "-B", "-I", str(target_evaluator),
                                "score", "--profile", str(profile_path),
                                "--trajectory", str(target_trajectory),
                                "--prediction", str(prediction_path),
                                "--output", str(score_path), "--verify-sources"],
                               cwd=fresh, timeout=10.0, old_roots=[old_root])
        score = _json(score_path, "score report")
        if score.get("status") != "PASS" or score.get("qualification") != UNKNOWN:
            raise TinyReplayError("real observer evaluator did not produce an UNKNOWN PASS")
        source_audit = {item["role"]: item for item in copied}
        report: dict[str, Any] = {
            "schema": REPORT_SCHEMA,
            "status": "PASS_DEVELOPMENT_TINY_PORTABLE_REPLAY_OPERATOR",
            "request_sha256": sha256_file(request_path),
            "request_canonical_sha256": request["sha256"],
            "case_id": request["case_id"], "attempt_id": request["attempt_id"],
            "parent_pid": parent_pid, "fixture_only": True,
            "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN", "original_roots_poisoned": [],
            "fresh_namespace": {"root": str(fresh), "new": True},
            "source_audit": source_audit,
            "commands": {
                "producer": producer_run, "profile": profile_run,
                "replay": observe_run, "evaluator": score_run,
            },
            "products": {
                "trajectory": {"path": str(target_trajectory), "sha256": sha256_file(target_trajectory),
                               "bytes": target_trajectory.stat().st_size},
                "profile": {"path": str(profile_path), "sha256": sha256_file(profile_path)},
                "observed": {"path": str(observed_path), "sha256": sha256_file(observed_path)},
                "prediction": {"path": str(prediction_path), "sha256": sha256_file(prediction_path)},
                "score": {"path": str(score_path), "sha256": sha256_file(score_path),
                          "status": score["status"]},
            },
            "execution": {
                "subprocesses_fresh_interpreter": True, "threads": 1,
                "max_wall_seconds_each": 10.0, "log_limit_bytes": 65536,
                "hdf5_or_bi4_content_read": False, "raw_native_content_read": False,
                "source_content_read_after_guard": True,
            },
            "limitations": [
                "Manufactured tiny trajectory and real generic JSON observer operator only.",
                "No raw/native/HDF5/BI4 content or production ledger was accessed.",
                "This does not grant raw-anchor, reconstruction, event, QI, QN, or QE credit.",
            ],
        }
        report["sha256"] = canonical_sha(report)
        _write_new(output, report)
        return report
    except BaseException:
        # Keep the failed attempt namespace for forensic inspection, but never
        # turn a partial run into a successful report or reuse its outputs.
        raise


def verify_report(report_path: Path) -> dict[str, Any]:
    report = _json(report_path, "tiny replay report")
    if report.get("schema") != REPORT_SCHEMA or report.get("sha256") != canonical_sha(report):
        raise TinyReplayError("report schema/canonical SHA differs")
    if report.get("status") != "PASS_DEVELOPMENT_TINY_PORTABLE_REPLAY_OPERATOR":
        raise TinyReplayError("report is not a completed tiny operator chain")
    if report.get("fixture_only") is not True or report.get("qualification") != UNKNOWN:
        raise TinyReplayError("report fixture/qualification boundary is unsafe")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise TinyReplayError("report model/CFD flags are unsafe")
    if report.get("original_path_fallback") != "FORBIDDEN" or report.get("original_roots_poisoned") != []:
        raise TinyReplayError("report permits original-path fallback")
    fresh = Path(report["fresh_namespace"]["root"]).expanduser().resolve()
    if not fresh.is_dir():
        raise TinyReplayError("fresh namespace is missing")
    for item in report.get("source_audit", {}).values():
        if item.get("source_pre_stat") != item.get("source_post_stat") or item.get("source_sha256") != item.get("target_sha256"):
            raise TinyReplayError("source pre/post or target hash is not closed")
        target = Path(item["target_path"]).expanduser().resolve()
        if not _inside(target, fresh):
            raise TinyReplayError("target escaped fresh namespace")
    score = report.get("products", {}).get("score", {})
    if score.get("status") != "PASS":
        raise TinyReplayError("score product is not PASS")
    return {"status": "VERIFIED_TINY_REPLAY_CHAIN", "fixture_only": True,
            "qualification": dict(UNKNOWN), "fresh_root": str(fresh),
            "report_sha256": report["sha256"]}


def producer(input_path: Path, output: Path) -> dict[str, Any]:
    source = _json(input_path, "producer input")
    _validate_input_shape(source)
    binding: dict[str, Any] = {}
    stat = _stat(input_path)
    digest = sha256_file(input_path)
    for role in ("current_catalog", "trajectory_h5", "producer_input"):
        binding[role] = {"path": str(input_path.resolve()), "bytes": stat["st_size"],
                         "mtime_ns": stat["st_mtime_ns"], "sha256": digest}
    trajectory = {key: source[key] for key in
                  ("query_times_s", "identity", "initial_mass_kg", "positions_m", "velocities_m_s", "valid")}
    trajectory.update({"schema": "ds02.stage2.no-model-observer-trajectory.v2",
                       "position_frame": "world", "velocity_frame": "world_inertial",
                       "source_binding": binding})
    _write_new(output, trajectory)
    return {"status": "PRODUCED_TINY_TYPED_TRAJECTORY", "sha256": sha256_file(output)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--producer-input", type=Path, required=True)
    build.add_argument("--observer-script", type=Path, default=OBSERVER)
    build.add_argument("--fresh-root", type=Path, required=True)
    build.add_argument("--old-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    produce = sub.add_parser("producer")
    produce.add_argument("--input", type=Path, required=True)
    produce.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=False)
    verify = sub.add_parser("verify-report")
    verify.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(producer_input=args.producer_input,
                                  observer_script=args.observer_script,
                                  fresh_root=args.fresh_root, old_root=args.old_root,
                                  output=args.output)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"]}, sort_keys=True))
        elif args.command == "producer":
            print(json.dumps(producer(args.input, args.output), sort_keys=True))
        elif args.command == "run":
            value = run_request(args.request, output=args.output, parent_pid=args.parent_pid)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                              "report": str(args.output.resolve())}, sort_keys=True))
        else:
            print(json.dumps(verify_report(args.report), sort_keys=True))
    except (TinyReplayError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
