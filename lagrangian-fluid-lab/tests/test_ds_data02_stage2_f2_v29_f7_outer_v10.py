from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_f7_outer_v10_metadata_only_bi4_and_home_attempt_output(tmp_path: Path, monkeypatch):
    outer = _load("f7_outer_v10_test", ROOT / "scripts/ds_data02_stage2_f7_half_cfl_initial_qa_outer_v10.py")
    output = tmp_path / "outer-request.json"
    real_sha = outer.sha256_file
    seen: list[Path] = []

    def no_bi4_hash(path):
        path = Path(path)
        seen.append(path)
        assert path.suffix != ".bi4", "metadata build/preflight must not read raw BI4"
        return real_sha(path)

    monkeypatch.setattr(outer, "sha256_file", no_bi4_hash)
    result = outer.build_request(output=output)
    assert result["status"] == "READY_FOR_PARENT_CPU_GUARD"
    assert result["schema"].endswith(".v10")
    assert result["identity_gate"]["checks"][0].startswith("decoder header")
    assert result["xml_semantics"]["half"]["np"] == 70179
    assert result["xml_semantics"]["half"]["cflnumber"] == 0.1
    assert result["xml_semantics"]["baseline"]["cflnumber"] == 0.2
    assert result["execution"]["output_dir_template"] == "{attempt_root}/qa"
    assert result["execution"]["output_filesystem"] == "home"
    assert result["resource_request"]["max_rss_bytes"] == 512 * 1024**2
    assert all(path.suffix != ".bi4" for path in seen)
    assert any(item["role"] == "f7_initial_qa_outer_v10" for item in result["source_bindings"])
    for item in result["source_bindings"]:
        if item["role"] in {"half_generated_bi4", "baseline_generated_bi4"}:
            assert item["content_scope"] == "metadata_only_stat_known_sha"
            assert item["content_verified"] is False
    preflight = outer.preflight(output)
    assert preflight["status"] == "READY_FOR_PARENT_CPU_SLOT"
    assert preflight["hdf5_opened"] is False
    assert preflight["raw_opened"] is False
    assert preflight["output_dir_template"] == "{attempt_root}/qa"
    assert preflight["source_count"] == 13


def test_f7_outer_v10_rejects_external_or_existing_home_output(tmp_path: Path):
    outer = _load("f7_outer_v10_output_test", ROOT / "scripts/ds_data02_stage2_f7_half_cfl_initial_qa_outer_v10.py")
    output = tmp_path / "outer-request.json"
    request = outer.build_request(output=output)
    with pytest.raises(outer.OuterQAError, match="external temporary"):
        outer._validate_home_output(request, Path("/var/tmp/qa"))
    attempt = ROOT / (".v10-existing-output-" + uuid.uuid4().hex)
    qa = attempt / "qa"
    try:
        qa.mkdir(parents=True)
        with pytest.raises(outer.OuterQAError, match="existing"):
            outer._validate_home_output(request, qa)
    finally:
        shutil.rmtree(attempt)


def test_f7_outer_v10_decoder_header_gate_reports_present_fields_and_rejects_wrong_identity(tmp_path: Path):
    outer = _load("f7_outer_v10_header_test", ROOT / "scripts/ds_data02_stage2_f7_half_cfl_initial_qa_outer_v10.py")
    output_dir = tmp_path / "attempt" / "qa"
    decoder_xml = (
        "<root><item name='case'>"
        "<uint name='CaseNp' v='70179'/><uint name='Np' v='70179'/><uint name='Nb' v='29479'/><uint name='Nbf' v='27495'/>"
        "<real name='Dp' v='0.019999999552965164'/><real name='B' v='554965.6875'/>"
        "<real name='Rhop0' v='1000'/><real name='Gamma' v='7'/><real name='MassBound' v='0.008'/>"
        "<real name='MassFluid' v='0.008'/><item name='particle'><real name='TimeStep' v='0'/></item>"
        "</item></root>"
    )
    for tag in ("half", "baseline"):
        path = output_dir / "decoder-scratch" / tag
        path.mkdir(parents=True)
        path.joinpath("frame_0000.xml").write_text(decoder_xml)
    request = outer.build_request(output=tmp_path / "request.json")
    gate = outer._header_identity_gate(output_dir, request["xml_semantics"])
    assert gate["identity_fields"]["CaseNp"]["status"] == "verified"
    assert gate["decoder_constants"]["B"]["status"] == "verified"
    (output_dir / "decoder-scratch" / "half" / "frame_0000.xml").write_text(
        decoder_xml.replace("70179", "70178", 1)
    )
    with pytest.raises(outer.OuterQAError, match="CaseNp"):
        outer._header_identity_gate(output_dir, request["xml_semantics"])
