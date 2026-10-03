#!/usr/bin/env python3
"""Test suite for F5 prospective execution-only transformer and errata artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from prospective_execution_transformer import (
    RUNUP_FINE_XML_PATH,
    RUNUP_FINE_XML_SHA256,
    WEIR_FINE_XML_PATH,
    WEIR_FINE_XML_SHA256,
    audit_sources,
    transform_execution_xml_bytes,
)

SCOPE_DIR = Path(__file__).resolve().parent


def test_audit_sources():
    res = audit_sources()
    assert res["schema"] == "ds02.f5.temporal-control-source-audit.v1"
    assert res["all_sources_verified"] is True
    assert res["cases"]["runup"]["xml_verified"] is True
    assert res["cases"]["runup"]["bi4_verified"] is True
    assert res["cases"]["runup"]["gencase_verified"] is True
    assert res["cases"]["weir"]["xml_verified"] is True
    assert res["cases"]["weir"]["bi4_verified"] is True
    assert res["cases"]["weir"]["gencase_verified"] is True


def test_transform_runup_xml():
    runup_bytes = RUNUP_FINE_XML_PATH.read_bytes()
    mutated_bytes, meta = transform_execution_xml_bytes(runup_bytes)
    assert meta["original_sha256"] == RUNUP_FINE_XML_SHA256
    assert meta["mutated_sha256"] == "d3f6ebcafdeb3051c32891f18678a3fe0e4e85b918e8711b3c184c2f593e0aed"
    assert meta["reversibility_verified"] is True
    assert meta["casedef_cfl_preserved"] == "0.2"
    assert meta["execution_cfl_mutated"] == "0.1"
    assert meta["execution_coefdtmin_mutated"] == "0.025"
    assert meta["byte_delta"] == 1

    # Verify text directly
    mut_text = mutated_bytes.decode("utf-8")
    assert '<cflnumber value="0.2" />' in mut_text.split("<execution>")[0]
    assert '<parameter key="CoefDtMin" value="0.025" />' in mut_text.split("<execution>")[1]
    assert '<cflnumber value="0.1" />' in mut_text.split("<execution>")[1]


def test_transform_weir_xml():
    weir_bytes = WEIR_FINE_XML_PATH.read_bytes()
    mutated_bytes, meta = transform_execution_xml_bytes(weir_bytes)
    assert meta["original_sha256"] == WEIR_FINE_XML_SHA256
    assert meta["mutated_sha256"] == "c69f453f7f81c670ce6fcc91f91bed0fa39807af7dda8f104d7dfd371194ec2d"
    assert meta["reversibility_verified"] is True
    assert meta["casedef_cfl_preserved"] == "0.2"
    assert meta["execution_cfl_mutated"] == "0.1"
    assert meta["execution_coefdtmin_mutated"] == "0.025"
    assert meta["byte_delta"] == 1

    # Verify text directly
    mut_text = mutated_bytes.decode("utf-8")
    assert '<cflnumber value="0.2" />' in mut_text.split("<execution>")[0]
    assert '<parameter key="CoefDtMin" value="0.025" />' in mut_text.split("<execution>")[1]
    assert '<cflnumber value="0.1" />' in mut_text.split("<execution>")[1]


def test_binding_proposals():
    p = SCOPE_DIR / "binding_proposals.json"
    assert p.is_file()
    data = json.loads(p.read_text())
    assert data["schema"] == "ds02.f5.binding-proposals.v1"
    assert "runup" in data["cases"]
    assert "weir" in data["cases"]
    assert data["frozen_reader_sha256"] == "8f858144b52a03ef207251bd84458bb8cdd0ee5d73bf2a6799cf168a8fc8e35a"
    assert data["preregistered_evaluation"]["temporal_integration_error_budget"] == 0.01


def test_preregistered_diagnostic():
    p = SCOPE_DIR / "preregistered_integration_diagnostic.json"
    assert p.is_file()
    data = json.loads(p.read_text())
    assert data["schema"] == "ds02.f5.preregistered-integration-diagnostic.v1"
    assert data["error_budget_specification"]["temporal_integration_error_budget"] == 0.01
    assert data["error_budget_specification"]["temporal_integration_absolute_tolerance_m"] == 0.004
    assert data["strict_methodological_invariants"]["no_phase_alignment"] is True


def test_runner_requests():
    for req_file in [
        SCOPE_DIR / "requests" / "F5_RUNUP_FINE_TEMPORAL_HALFSTEP_REQUEST.json",
        SCOPE_DIR / "requests" / "F5_WEIR_FINE_TEMPORAL_HALFSTEP_REQUEST.json",
    ]:
        assert req_file.is_file()
        data = json.loads(req_file.read_text())
        assert data["schema"] == "ds02.runner-request.v2"
        assert data["launch_allowed"] is False
        assert data["launch_owner"] == "root"
        assert data["root_review_required"] is True
        assert data["max_wall_seconds"] == 28800
        assert data["cpu_threads"] == 4
        assert data["resource_and_budget_claims"]["conservative_gpu_hours_cap"] == 8.0
        assert data["resource_and_budget_claims"]["cpu_core_hours_cap"] == 32.0
