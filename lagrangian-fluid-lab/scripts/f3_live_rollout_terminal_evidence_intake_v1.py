#!/usr/bin/env python3
"""Intake bounded terminal evidence for the F3 graph_raw hidden16 rollout.

This module is a read-only evidence boundary.  It reads only bounded JSON
terminal summaries and small-file metadata.  Progress files, trajectories,
checkpoints, manifests, HDF5 files, PIDs, and runtime state are never opened
or used to infer completion.  A valid intake is still diagnostic-only and
cannot mint T1/T2/qualification credit or mutate campaign state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.live_rollout_terminal_evidence_intake_report.v1"
REPORT_ID = "f3-graph-raw-hidden16-live-rollout-terminal-evidence-intake-v1"
SEEDS = (17, 29, 43)
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
JSON_SUFFIXES = {".json", ".jsonl"}
DISALLOWED_SUFFIXES = {".h5", ".hdf5", ".pt", ".pth", ".ckpt", ".bin"}
OUTPUT_PREFIX_RE = re.compile(
    r"^/[^\x00]*f3-graph-raw500-hidden16-seed(?P<seed>[0-9]+)-full835-[^/]+$"
)
DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
DEFAULT_TERMINAL_PATHS = {
    seed: Path(
        f"/tmp/f3-graph-raw500-hidden16-seed{seed}-full835-"
        "live-terminal-evidence-v1.json"
    )
    for seed in SEEDS
}
DEFAULT_REPORT = Path(
    "reports/F3-GRAPH-RAW-HIDDEN16-LIVE-ROLLOUT-TERMINAL-EVIDENCE-"
    "INTAKE-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F3-GRAPH-RAW-HIDDEN16-LIVE-ROLLOUT-TERMINAL-EVIDENCE-"
    "INTAKE-V1-2026-09-28.zh-CN.md"
)


class IntakeError(ValueError):
    """Malformed, unsafe, incomplete, or non-terminal input."""


def _fail(message: str) -> None:
    raise IntakeError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _check_finite(value: Any, name: str = "value") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _check_finite(item, f"{name}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _check_finite(item, f"{name}[{index}]")
        return
    _fail(f"{name} contains unsupported value {type(value).__name__}")


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _source_ref(root: Path, path: Path, *, opened: bool, raw: bytes | None = None) -> dict[str, Any]:
    exists = path.is_file()
    result: dict[str, Any] = {
        "path": _display_path(root, path),
        "exists": exists,
        "opened": opened,
        "bytes": len(raw) if raw is not None else (path.stat().st_size if exists else None),
        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
    }
    return result


def _read_bounded_json(root: Path, value: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    if path.is_symlink():
        _fail(f"symlink JSON input is not allowed: {path}")
    path = path.resolve()
    if path.suffix.lower() in DISALLOWED_SUFFIXES:
        _fail(f"disallowed non-JSON input: {path}")
    if path.suffix.lower() not in JSON_SUFFIXES:
        _fail(f"input must use a JSON suffix: {path}")
    if not path.is_file():
        _fail(f"missing terminal JSON: {path}")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        _fail(f"terminal JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        raw = path.read_bytes()
        value_obj = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except IntakeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read strict terminal JSON {path}: {error}")
    payload = dict(_mapping(value_obj, str(path)))
    _check_finite(payload, str(path))
    source = _source_ref(root, path, opened=True, raw=raw)
    source["schema"] = payload.get("schema")
    return payload, source


def _missing_source(root: Path, value: Path | str) -> dict[str, Any]:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return _source_ref(root, path, opened=False)


def _declared_path(value: Any, name: str, suffix: str | None = None) -> str:
    path = _string(value, name)
    path_obj = Path(path)
    if not path_obj.is_absolute() or ".." in path_obj.parts:
        _fail(f"{name} must be absolute and must not contain parent traversal")
    if suffix is not None and not path.endswith(suffix):
        _fail(f"{name} must end with {suffix}")
    return path


def _require_false_or_zero(value: Mapping[str, Any], key: str, name: str) -> None:
    if key not in value:
        return
    item = value[key]
    if type(item) is bool and item is False:
        return
    if type(item) is int and item == 0:
        return
    _fail(f"{name}.{key} must be false or zero")


def validate_terminal_receipt(receipt: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Validate one bounded, terminal hidden16 diagnostic summary."""

    value = _mapping(receipt, f"terminal[{seed}]")
    accepted_schemas = {
        "core.f3.graph_raw.hidden16.full835.rollout_diagnostic.summary.v1",
        f"core.f3.graph_raw.hidden16.seed{seed}.full835.rollout_diagnostic.summary.v1",
    }
    if value.get("schema") not in accepted_schemas:
        _fail(f"terminal[{seed}].schema is not an accepted hidden16 summary")
    if value.get("status") not in {"completed", "completed_diagnostic"}:
        _fail(f"terminal[{seed}] is not completed")
    if value.get("model_kind") != MODEL_KIND:
        _fail(f"terminal[{seed}].model_kind drifts")
    if value.get("seed") != seed or value.get("hidden") != HIDDEN:
        _fail(f"terminal[{seed}] seed/hidden drifts")
    if value.get("updates") != UPDATES:
        _fail(f"terminal[{seed}].updates drifts")
    if value.get("transitions") != TRANSITIONS or value.get("frames") != FRAMES:
        _fail(f"terminal[{seed}] must bind 835 transitions and 836 frames")

    markers = _mapping(value.get("terminal_markers"), f"terminal[{seed}].terminal_markers")
    if markers.get("terminal") is not True:
        _fail(f"terminal[{seed}].terminal_markers.terminal must be true")
    if markers.get("execution_complete") is not True:
        _fail(f"terminal[{seed}].terminal_markers.execution_complete must be true")
    if markers.get("finite_rollout_complete") is not True:
        _fail(f"terminal[{seed}].terminal_markers.finite_rollout_complete must be true")
    if markers.get("terminal_status") != "completed":
        _fail(f"terminal[{seed}].terminal_markers.terminal_status must be completed")

    checkpoint = _mapping(value.get("checkpoint"), f"terminal[{seed}].checkpoint")
    checkpoint_path = _declared_path(checkpoint.get("path"), f"terminal[{seed}].checkpoint.path")
    checkpoint_sha = _sha256(checkpoint.get("sha256"), f"terminal[{seed}].checkpoint.sha256")
    if checkpoint.get("update") != UPDATES:
        _fail(f"terminal[{seed}].checkpoint.update drifts")

    output = _mapping(value.get("output"), f"terminal[{seed}].output")
    prefix = _declared_path(output.get("fresh_output_namespace"), f"terminal[{seed}].output.fresh_output_namespace")
    match = OUTPUT_PREFIX_RE.fullmatch(prefix)
    if match is None or int(match.group("seed")) != seed:
        _fail(f"terminal[{seed}].output namespace is not a fresh hidden16 seed namespace")
    evaluation_path = _declared_path(output.get("evaluation_path"), f"terminal[{seed}].output.evaluation_path", "-evaluation.json")
    trajectory_path = _declared_path(output.get("trajectory_path"), f"terminal[{seed}].output.trajectory_path", "-trajectory.h5")
    progress_path = _declared_path(output.get("progress_path"), f"terminal[{seed}].output.progress_path", "-evaluation-progress.json")
    if evaluation_path != prefix + "-evaluation.json":
        _fail(f"terminal[{seed}].evaluation path is not derived from fresh namespace")
    if trajectory_path != prefix + "-trajectory.h5":
        _fail(f"terminal[{seed}].trajectory path is not derived from fresh namespace")
    if progress_path != prefix + "-evaluation-progress.json":
        _fail(f"terminal[{seed}].progress path is not derived from fresh namespace")

    if value.get("diagnostic_only") is not True:
        _fail(f"terminal[{seed}].diagnostic_only must be true")
    for key in ("formal_eligible", "qualification", "T1_numerical", "T2_macro", "T2_path"):
        if value.get(key) is not False:
            _fail(f"terminal[{seed}].{key} must be false")
    if value.get("future_state_inputs") is not False:
        _fail(f"terminal[{seed}].future_state_inputs must be false")
    if value.get("qualification_credit") != 0 or value.get("credit") != 0:
        _fail(f"terminal[{seed}] credit markers must be zero")
    qualification = _mapping(value.get("qualification_markers", {}), f"terminal[{seed}].qualification_markers")
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        _require_false_or_zero(qualification, key, f"terminal[{seed}].qualification_markers")
    if "credit" in qualification and qualification["credit"] != 0:
        _fail(f"terminal[{seed}].qualification_markers.credit must be zero")
    side_effects = _mapping(value.get("side_effects", {}), f"terminal[{seed}].side_effects")
    for key, item in side_effects.items():
        if key in {"rollout_inputs_read_only"}:
            if item is not True:
                _fail(f"terminal[{seed}].side_effects.{key} must be true")
        else:
            _require_false_or_zero(side_effects, key, f"terminal[{seed}].side_effects")

    return {
        "seed": seed,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "checkpoint": {"path": checkpoint_path, "sha256": checkpoint_sha, "update": UPDATES},
        "output": {
            "fresh_output_namespace": prefix,
            "evaluation_path": evaluation_path,
            "trajectory_path": trajectory_path,
            "progress_path": progress_path,
        },
        "terminal_status": "completed",
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification_credit": 0,
        "credit": 0,
    }


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"check": name, "passed": bool(passed), "reason": reason}
    if observed is not None:
        result["observed"] = observed
    if expected is not None:
        result["expected"] = expected
    return result


def _empty_side_effects() -> dict[str, Any]:
    return {
        "manifest_opened": False,
        "case_hdf5_opened": False,
        "checkpoint_opened": False,
        "trajectory_hdf5_opened": False,
        "progress_opened": False,
        "runtime_started": False,
        "gpu_started": False,
        "worker_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def evaluate_payloads(
    receipts: Mapping[int, Mapping[str, Any]],
    sources: Mapping[int, Mapping[str, Any]] | None = None,
    *,
    source_errors: Sequence[str] = (),
) -> dict[str, Any]:
    """Evaluate a complete seed set without touching any non-JSON artifact."""

    sources = dict(sources or {})
    errors = list(source_errors)
    rows: list[dict[str, Any]] = []
    projections: dict[int, dict[str, Any]] = {}
    prefixes: list[str] = []
    for seed in SEEDS:
        row: dict[str, Any] = {
            "seed": seed,
            "status": "missing",
            "source": sources.get(seed),
            "blocked_reasons": [],
        }
        if seed not in receipts:
            reason = f"missing terminal evidence for seed {seed}"
            row["blocked_reasons"].append(reason)
            errors.append(reason)
        else:
            try:
                projection = validate_terminal_receipt(receipts[seed], seed)
                projections[seed] = projection
                prefixes.append(projection["output"]["fresh_output_namespace"])
                row.update({"status": "bound_terminal", "projection": projection})
            except Exception as error:
                reason = str(error)
                row.update({"status": "rejected", "error": reason})
                row["blocked_reasons"].append(reason)
                errors.append(f"seed{seed}: {reason}")
        rows.append(row)

    exact_set = set(projections) == set(SEEDS)
    unique_prefixes = len(prefixes) == len(set(prefixes)) == len(SEEDS)
    checks = [
        _check("terminal_seed_set_exact", exact_set, "all three target seeds have valid terminal evidence", sorted(projections), list(SEEDS)),
        _check("fresh_output_identity_unique", unique_prefixes, "terminal output namespaces are distinct and fresh"),
    ]
    if not exact_set:
        errors.append(f"terminal seed set incomplete: observed {sorted(projections)} expected {list(SEEDS)}")
    if not unique_prefixes:
        errors.append("terminal output namespace is missing or reused across seeds")
    errors = list(dict.fromkeys(errors))
    any_rejected = any(row["status"] == "rejected" for row in rows)
    all_bound = exact_set and unique_prefixes and not errors
    if all_bound:
        status = "bound_terminal_diagnostic"
    elif any_rejected or source_errors:
        status = "blocked_fail_closed"
    else:
        status = "blocked_missing_terminal_evidence"
    for row in rows:
        if row["status"] == "bound_terminal":
            row["status"] = "bound_terminal_diagnostic" if all_bound else "bound_terminal"

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": status,
        "fail_closed": not all_bound,
        "source_bound": all_bound,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "expected_contract": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "terminal_status": "completed",
            "progress_or_pid_is_not_completion": True,
        },
        "seed_matrix": rows,
        "checks": checks,
        "blocked_reasons": errors,
        "terminal_sources": {str(seed): sources.get(seed) for seed in SEEDS},
        "side_effects": _empty_side_effects(),
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "terminal_json_opened": len(receipts),
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
            "runtime_started": False,
            "gpu_started": False,
            "worker_started": False,
        },
        "interpretation": (
            "This adapter binds bounded terminal JSON summaries only. It never opens progress, "
            "trajectory, checkpoint, manifest, or HDF5 content; it cannot authorize execution "
            "or produce T1/T2/formal qualification credit."
        ),
    }


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    terminal_paths: Mapping[int, Path | str] = DEFAULT_TERMINAL_PATHS,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    receipts: dict[int, Mapping[str, Any]] = {}
    sources: dict[int, Mapping[str, Any]] = {}
    source_errors: list[str] = []
    for seed in SEEDS:
        path = terminal_paths.get(seed)
        if path is None:
            source_errors.append(f"missing configured terminal path for seed {seed}")
            continue
        try:
            payload, source = _read_bounded_json(root, path)
            receipts[seed] = payload
            sources[seed] = source
        except Exception as error:
            sources[seed] = _missing_source(root, path)
            # A configured path that simply does not exist is the normal
            # missing-terminal state.  Unsafe suffixes, malformed JSON,
            # symlinks, and other reader failures remain fail-closed errors.
            if "missing terminal JSON" not in str(error):
                source_errors.append(f"seed{seed} terminal input: {error}")
    report = evaluate_payloads(receipts, sources, source_errors=source_errors)
    report["observed_at_utc"] = observed_at_utc
    return report


def render_zh_report(report: Mapping[str, Any]) -> str:
    rows = report.get("seed_matrix", [])
    lines = [
        "# F3 `graph_raw` hidden16 live rollout terminal-evidence intake V1",
        "",
        "机器报告：`F3-GRAPH-RAW-HIDDEN16-LIVE-ROLLOUT-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json`",
        "",
        f"- 状态：`{report.get('status')}`；这不是资格结论。",
        f"- 目标：model=`{MODEL_KIND}`、hidden=`{HIDDEN}`、updates=`{UPDATES}`、seed=`17/29/43`。",
        f"- 固定分母：`{TRANSITIONS}` transitions / `{FRAMES}` frames；progress/PID 不被视为完成。",
        "- 边界：只读取有界 terminal JSON；不打开 manifest、HDF5、checkpoint、trajectory 或 progress。",
        "- 结果：diagnostic-only，formal/T1/T2/qualification=false，credit=0，所有 mutation=0。",
        "",
        "## Seed 状态",
        "",
    ]
    for row in rows:
        lines.append(f"- seed `{row.get('seed')}`：`{row.get('status')}`；阻塞：{', '.join(row.get('blocked_reasons', [])) or '无'}")
    lines.extend([
        "",
        "## 后续",
        "",
        "只有严格终态、hidden16、同配置、835/836 且零信用的 fresh terminal summary 才能重新 intake；当前缺失或非终态输入不会被提升为 T1/T2/qualification。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], output: Path | str, zh_output: Path | str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    zh_path = Path(zh_output)
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.write_text(render_zh_report(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--terminal", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, default=LAB_ROOT / DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=LAB_ROOT / DEFAULT_ZH_REPORT)
    parser.add_argument("--observed-at-utc", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args(argv)
    paths = dict(DEFAULT_TERMINAL_PATHS)
    for raw in args.terminal:
        if "=" not in raw:
            raise SystemExit(f"--terminal must use SEED=PATH: {raw}")
        seed_text, path_text = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise SystemExit(f"invalid seed: {raw}") from error
        if seed not in SEEDS:
            raise SystemExit(f"seed must be one of {SEEDS}: {raw}")
        paths[seed] = Path(path_text)
    report = build_report(args.root, terminal_paths=paths, observed_at_utc=args.observed_at_utc)
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({"status": report["status"], "source_bound": report["source_bound"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
