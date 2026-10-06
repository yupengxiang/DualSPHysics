#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import validate_fresh066_corner_contract as validator  # noqa: E402


def request():
    return validator.load(HERE / "requests/F3_STAGE1_DP006_P0800_AY0250.json")


def main() -> None:
    validator.validate_package(check_files=True)

    missing_worktree = request()
    missing_worktree.pop("worktree_root")
    try:
        validator.validate_request(missing_worktree, missing_worktree["case_id"], check_files=False)
    except AssertionError:
        pass
    else:
        raise AssertionError("missing worktree_root was accepted")

    direct_converter = request()
    delimiter = direct_converter["command"].index("--")
    direct_converter["command"].insert(delimiter + 1, "/tmp/ds_data02_direct_convert.py")
    try:
        validator.validate_request(direct_converter, direct_converter["case_id"], check_files=False)
    except AssertionError:
        pass
    else:
        raise AssertionError("direct converter after wrapper delimiter was accepted")

    enabled = request()
    enabled["execution_allowed"] = True
    try:
        validator.validate_request(enabled, enabled["case_id"], check_files=False)
    except AssertionError:
        pass
    else:
        raise AssertionError("enabled future request was accepted")

    future_hash = request()
    future_hash["future_typed_outputs"]["trajectory_h5"]["sha256"] = "0" * 64
    try:
        validator.validate_request(future_hash, future_hash["case_id"], check_files=False)
    except AssertionError:
        pass
    else:
        raise AssertionError("future science hash was accepted")

    print("PASS: fresh066-corner706 contract and negative tests")


if __name__ == "__main__":
    main()
