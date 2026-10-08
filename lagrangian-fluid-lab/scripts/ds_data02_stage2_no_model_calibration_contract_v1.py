#!/usr/bin/env python3
"""Bind the model-free observer trial to a frozen development profile.

The existing F2 evaluator report contains an operator self-test and deliberate
wrong-status/wrong-time counterexamples.  This contract makes that evidence
usable by a caller without treating it as a solver calibration or a quality
qualification: the profile/current/evaluator hashes are frozen, the label
states and error budgets are explicit, and all QI/QN/QE remain UNKNOWN.
Only small JSON/Markdown/code sources are read here.  The typed result and
trajectory HDF5 are provenance/stat-only inputs; this command never opens
them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.no-model-calibration-contract.v1"
MAX_JSON_BYTES = 32 * 1024 * 1024


class CalibrationBindingError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({k: v for k, v in value.items() if k != "sha256"}).encode()).hexdigest()


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.stat().st_size > MAX_JSON_BYTES:
        raise CalibrationBindingError(f"JSON source is missing or too large: {target}")
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationBindingError(f"JSON object required: {target}")
    return value


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise CalibrationBindingError(f"refusing to overwrite contract: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _small_binding(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise CalibrationBindingError(f"{role} is missing: {path}")
    return {"role": role, "path": str(path), "bytes": path.stat().st_size,
            "sha256": file_sha256(path), "content_read": True}


def _profile(path: Path, current_sha: str) -> dict[str, Any]:
    profile = read_json(path)
    if profile.get("sha256") != canonical_sha(profile):
        raise CalibrationBindingError("observer profile canonical SHA differs")
    if profile.get("schema") not in {"ds02.stage2.f2-s1-observer-profile.v14",
                                     "ds02.stage2.reference-observer-profile.v9"}:
        raise CalibrationBindingError("unsupported observer profile schema")
    bound_current = profile.get("current_binding_sha256")
    if bound_current is None and isinstance(profile.get("source_binding"), Mapping):
        bound_current = profile["source_binding"].get("current_catalog_sha256")
    if bound_current != current_sha:
        raise CalibrationBindingError("observer profile CURRENT SHA differs")
    if profile.get("frozen_before_reference") is False:
        raise CalibrationBindingError("observer profile was not frozen before reference result")
    status = str(profile.get("scientific_status", ""))
    if status and "UNKNOWN" not in status and status != "DEVELOPMENT_ONLY":
        raise CalibrationBindingError("observer profile scientific status is over-promoted")
    budget = profile.get("scientific_error_budget", {})
    if not isinstance(budget, Mapping) or any(float(value) > 0.25 for value in budget.values()):
        raise CalibrationBindingError("observer profile error budget exceeds one-quarter")
    names = profile.get("observable_names") or profile.get("observation_contract", {}).get("fixed_observation_names")
    if not isinstance(names, list) or not names:
        raise CalibrationBindingError("observer profile has no fixed observation names")
    return {"path": str(path), "sha256": file_sha256(path), "embedded_sha256": profile["sha256"],
            "profile_id": profile.get("profile_id"), "schema": profile.get("schema"),
            "current_sha256": current_sha, "frozen_before_reference": True,
            "query_times_s": profile.get("query_times_s") or profile.get("observation_contract", {}).get("query_times_s"),
            "observable_names": list(names), "scientific_error_budget": dict(budget),
            "thresholds": profile.get("thresholds", {}), "qualification": dict(UNKNOWN)}


def bind_contract(current_path: Path | str, profile_path: Path | str,
                  evaluator_request_path: Path | str, evaluator_report_path: Path | str,
                  quality_label_source: Path | str, output_path: Path | str) -> dict[str, Any]:
    current_path = Path(current_path).expanduser().resolve()
    profile_path = Path(profile_path).expanduser().resolve()
    evaluator_request_path = Path(evaluator_request_path).expanduser().resolve()
    evaluator_report_path = Path(evaluator_report_path).expanduser().resolve()
    quality_label_source = Path(quality_label_source).expanduser().resolve()
    current = read_json(current_path)
    if current.get("schema") != "ds02.stage2.current336.v1" or len(current.get("cases", [])) != 336:
        raise CalibrationBindingError("CURRENT336 schema/count is not exact")
    current_sha = file_sha256(current_path)
    profile = _profile(profile_path, current_sha)
    request = read_json(evaluator_request_path)
    if request.get("schema") != "ds02.stage2.f2-no-model-evaluator-request.v1":
        raise CalibrationBindingError("evaluator request schema differs")
    if request.get("sha256") != canonical_sha(request):
        raise CalibrationBindingError("evaluator request canonical SHA differs")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise CalibrationBindingError("evaluator request is not model-free")
    if request.get("qualification") != UNKNOWN:
        raise CalibrationBindingError("evaluator request qualification is not UNKNOWN")
    frozen_path = Path(str(request.get("frozen_request", {}).get("path", ""))).expanduser().resolve()
    frozen = read_json(frozen_path)
    frozen_profile = frozen.get("observer_profile", {})
    if not isinstance(frozen_profile, Mapping) or frozen_profile.get("sha256") != profile["embedded_sha256"]:
        raise CalibrationBindingError("evaluator frozen request/profile SHA differs")
    report = read_json(evaluator_report_path)
    if report.get("schema") != "ds02.stage2.f2-no-model-evaluator-report.v1":
        raise CalibrationBindingError("evaluator report schema differs")
    if report.get("status") != "PASS_OPERATOR_TRIAL_WITH_EXPECTED_COUNTEREXAMPLES":
        raise CalibrationBindingError("evaluator report lacks the expected operator trial")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise CalibrationBindingError("evaluator report is not model-free")
    if report.get("hdf5_or_bi4_content_read") is not False or report.get("qualification") != UNKNOWN:
        raise CalibrationBindingError("evaluator report has unsafe content/qualification scope")
    cases = report.get("cases", {})
    if cases.get("pass", {}).get("status") != "PASS":
        raise CalibrationBindingError("operator pass counterexample is missing")
    if cases.get("status_mismatch", {}).get("status") != "FAIL" or cases.get("time_mismatch", {}).get("status") != "FAIL":
        raise CalibrationBindingError("operator wrong-status/time counterexamples are missing")
    label_source = _small_binding(quality_label_source, "QUALITY_LABEL_SPLIT_ZH")
    contract: dict[str, Any] = {
        "schema": SCHEMA, "status": "MANUFACTURED_OPERATOR_CALIBRATION_BOUND",
        "role": "DEVELOPMENT", "profile": profile,
        "current_binding": {"path": str(current_path), "sha256": current_sha, "case_count": 336},
        "evaluator_request": {"path": str(evaluator_request_path), "sha256": file_sha256(evaluator_request_path),
                               "embedded_sha256": request["sha256"], "request_id": request.get("request_id")},
        "evaluator_report": {"path": str(evaluator_report_path), "sha256": file_sha256(evaluator_report_path),
                              "status": report["status"], "counterexamples": ["status_mismatch", "time_mismatch"]},
        "label_interface": {
            "source": label_source, "first_passage_states": ["observed", "right_censored",
                "failed_before_observation", "initially_inside", "ambiguous_multiple_crossing"],
            "unknown_recross_policy": "retain_unknown; no imputation or qualification credit",
            "saved_bracket_policy": "first candidate bracket only; later bracket is not first-arrival credit",
        },
        "calibration_scope": "independent manufactured/operator expectation only; no reference result used",
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "limitations": [
            "The evaluator pass is an operator self-test, not solver/reference calibration.",
            "Trajectory HDF5, BI4, and raw arrays are not opened by this contract builder.",
            "QI/QN/QE remain UNKNOWN until separately approved source-bound calibration and reference evidence.",
        ],
    }
    contract["sha256"] = canonical_sha(contract)
    write_new(Path(output_path).expanduser().resolve(), contract)
    return {"path": str(Path(output_path).expanduser().resolve()), "sha256": contract["sha256"],
            "status": contract["status"], "qualification": dict(UNKNOWN), "hdf5_opened": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--evaluator-request", type=Path, required=True)
    parser.add_argument("--evaluator-report", type=Path, required=True)
    parser.add_argument("--quality-label-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = bind_contract(args.current, args.profile, args.evaluator_request,
                               args.evaluator_report, args.quality_label_source, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
