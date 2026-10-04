#!/usr/bin/env python3
"""Explicit Stage 1 visual dispatch adapter.

The consumed ``ds_data02_strict_dispatch_v1`` and ``ds_data02_runtime_v2``
remain untouched.  This adapter performs a small, auditable module alias only
while an explicit visual production request is running:

* ``kind`` must be ``production``;
* ``visual_stage_profile`` must be exactly ``stage1_visual``; and
* the original strict dispatcher is called with the original request and
  keyword arguments.

The alias makes the unchanged runtime dynamically import the Stage 1
authorizer under its legacy ``ds_data02_production`` name.  It is restored in
all cases before this function returns.  The runtime therefore keeps its
existing immutable input hash pass, resource ledger, UUID lease, process
monitoring, and execution receipt behavior.  A separate semantic sidecar
explains the legacy receipt's top-level status without changing its bytes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping

import ds_data02_stage1_production as authorizer


VISUAL_STAGE_PROFILE = authorizer.VISUAL_STAGE_PROFILE
SEMANTIC_SIDECAR_SCHEMA = "ds02.stage1.visual-receipt-semantics.v1"
LEGACY_TOP_LEVEL_STATUS = "approved_scope_at_launch"
_MISSING = object()


def _load_request(request_path: os.PathLike[str] | str) -> dict[str, Any]:
    path = Path(request_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read request JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("request must be a JSON object")
    return value


def validate_visual_request(request: Mapping[str, Any]) -> None:
    """Reject requests that are not explicitly in this adapter's scope."""

    if request.get("kind") != "production":
        raise ValueError("Stage 1 visual adapter accepts kind=production only")
    if request.get("visual_stage_profile") != VISUAL_STAGE_PROFILE:
        raise ValueError("Stage 1 visual adapter requires visual_stage_profile=stage1_visual")


def _strict_module() -> Any:
    try:
        return importlib.import_module("ds_data02_strict_dispatch_v1")
    except ImportError as error:
        raise RuntimeError("consumed strict dispatcher is not importable") from error


@contextmanager
def install_stage1_authorizer_alias(request: Mapping[str, Any]) -> Iterator[None]:
    """Install the legacy import alias for one explicit request only."""

    validate_visual_request(request)
    previous = sys.modules.get("ds_data02_production", _MISSING)
    sys.modules["ds_data02_production"] = authorizer
    try:
        yield
    finally:
        if previous is _MISSING:
            sys.modules.pop("ds_data02_production", None)
        else:
            sys.modules["ds_data02_production"] = previous


def semantic_sidecar(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    approval_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the explicit visual-only meaning of a legacy runtime receipt."""

    runtime_status = receipt.get("numerical_reference_status")
    receipt_hash = None
    output_value = receipt.get("output_root")
    if isinstance(output_value, str):
        receipt_path = Path(output_value) / "execution-receipt.json"
        if receipt_path.is_file():
            hasher = hashlib.sha256()
            with receipt_path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            receipt_hash = hasher.hexdigest()
    return {
        "schema": SEMANTIC_SIDECAR_SCHEMA,
        "stage1_profile": VISUAL_STAGE_PROFILE,
        "visual_only": True,
        "request_kind": request.get("kind"),
        "case_id": request.get("case_id"),
        "scope_id": request.get("scope_id"),
        "legacy_top_level_numerical_reference_status": runtime_status,
        "legacy_status_interpretation": (
            "approved_scope_at_launch records a visual-stage launch binding for "
            "this stage1_visual profile; it does not accept numerical precision."
        ),
        "numerical_precision_status": "not_accepted",
        "precision_context": "pending",
        "final_acceptance": "separate_root_visual_and_numerical_acceptance",
        "q_n": "not_granted",
        "q_e": "not_assessed",
        "runtime_receipt_bytes_preserved": True,
        "runtime_receipt_sha256_after_dispatch": receipt_hash,
        "approval_context": dict(approval_context or receipt.get("scientific_approval_at_launch", {})),
    }


def write_semantic_sidecar(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    approval_context: Mapping[str, Any] | None = None,
    output_root: os.PathLike[str] | str | None = None,
) -> Path | None:
    """Write a separate semantic sidecar after a completed strict dispatch."""

    root_value = output_root if output_root is not None else receipt.get("output_root")
    if not isinstance(root_value, str) or not root_value:
        return None
    root = Path(root_value)
    if not root.is_dir():
        return None
    destination = root / "execution-receipt.visual-stage1-semantics.json"
    payload = semantic_sidecar(receipt, request, approval_context=approval_context)
    temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def run_request(request_path: os.PathLike[str] | str, **kwargs: Any) -> Any:
    """Run one explicit visual request through the original strict dispatcher."""

    request = _load_request(request_path)
    validate_visual_request(request)
    strict = _strict_module()
    with install_stage1_authorizer_alias(request):
        # This is intentionally the original dispatcher entry point.  It
        # retains the original runtime/resource/lease/registered-digest path.
        receipt = strict.run_request(request_path, **kwargs)
    if isinstance(receipt, Mapping):
        sidecar = write_semantic_sidecar(receipt, request)
        if sidecar is not None:
            result = dict(receipt)
            result["visual_stage1_semantic_sidecar"] = str(sidecar)
            return result
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run",))
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = run_request(args.request)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return int(isinstance(receipt, Mapping) and receipt.get("status") != "completed")


__all__ = [
    "LEGACY_TOP_LEVEL_STATUS",
    "SEMANTIC_SIDECAR_SCHEMA",
    "VISUAL_STAGE_PROFILE",
    "install_stage1_authorizer_alias",
    "main",
    "run_request",
    "semantic_sidecar",
    "validate_visual_request",
    "write_semantic_sidecar",
]


if __name__ == "__main__":
    raise SystemExit(main())
