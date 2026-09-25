from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import time

import pytest

from scripts import f8_r008_timestep_source_semantics_v1 as audit


def _inputs():
    sources = {
        key: audit._read_regular(audit.REPO, path)[0]
        for key, path in audit.SOURCE_PATHS.items()
    }
    pack = audit._read_regular(audit.LAB, audit.PACK_PATH)[0]
    scope = audit._strict_json(pack)
    definitions = {
        case["definition"]["path"]: audit._read_regular(
            audit.LAB, case["definition"]["path"]
        )[0]
        for case in scope["cases"]
    }
    return sources, pack, definitions


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | audit.O_DIRECTORY | audit.O_NOFOLLOW)


def _runtime_evidence(**updates):
    evidence = {
        "backend": "standard_cpu_single",
        "frozen_time_max_s": 10.0,
        "effective_time_max_s": 10.0,
        "final_time_s": 10.02,
        "absolute_tolerance_s": 0.001,
        "relative_tolerance": 0.002,
        "tolerance_preregistration_claim": True,
        "tolerance_receipt_sha256": "a" * 64,
        "process_exit_code": 0,
        "nstepsbreak_observed": False,
        "minimum_fluid_stop_observed": False,
        "terminate_file_observed": False,
        "terminate_applied": False,
        "terminate_warning_observed": False,
        "unregistered_control_override_observed": False,
        "gpu_enabled": False,
        "openmp_enabled": False,
        "vres_enabled": False,
    }
    evidence.update(updates)
    return evidence


def test_source_audit_distinguishes_default_from_runtime_adjudication():
    receipt = audit.build_audit()

    assert receipt["frozen_definition_pack"]["definition_count"] == 47
    assert receipt["frozen_definition_pack"]["qualification_definition_count"] == 15
    assert receipt["frozen_definition_pack"]["production_definition_count"] == 32
    assert receipt["frozen_definition_pack"]["definition_bytes_and_hashes_verified"] is True
    assert receipt["frozen_definition_pack"]["explicit_step_algorithm_overrides"] == []
    assert receipt["static_findings"]["xml_step_algorithm_absent_from_all_frozen_definitions"] is True
    assert receipt["static_findings"]["solver_xml_default_step_algorithm"].startswith("Verlet (StepAlgorithm=1)")
    assert receipt["static_findings"]["effective_runtime_step_algorithm"] == "unverified"
    assert receipt["static_findings"]["cpu_verlet_dtmax_equals_applied_step_when_runtime_integrator_is_verified"] is True
    assert receipt["static_findings"]["cpu_symplectic_recorded_part_dtmax_is_actual_used_dt_max"] is False
    assert receipt["static_findings"]["runparts_footer_proves_normal_completion"] is False
    assert receipt["static_findings"]["terminate_file_can_rewrite_cpu_time_max"] is True
    assert receipt["static_findings"]["terminate_file_is_checked_during_save_data"] is True
    assert receipt["backend_scope"] == {
        "audited_backend": "standard_cpu_single_only",
        "runtime_backend_verified": False,
        "gpu_semantics_audited": False,
        "vres_semantics_audited": False,
        "other_backend_evidence_accepted": False,
    }
    assert receipt["receipt_publication_scope"] == {
        "publication": "anonymous_inode_atomic_no_replace",
        "concurrent_no_clobber": True,
        "hostile_same_uid_mutation_defended": False,
        "group_or_other_writable_output_ancestry_rejected": True,
    }
    missing = set(receipt["frozen_definition_pack"]["runtime_control_keys_without_frozen_definition_values"])
    assert {"StepAlgorithm", "VerletSteps", "DtIni", "DtMin", "DtFixed",
            "CFLnumber", "TimeOutExtra", "MinFluidStop", "NstepsBreak"} <= missing
    assert not {"TimeMax", "TimeOut"} & missing
    assert any("final_time >= frozen_TimeMax" in item and "tolerance" in item
               for item in receipt["future_runtime_adjudication_requirements"])
    contract = receipt["runtime_completion_evidence_contract"]
    assert contract["schema"] == audit.RUNTIME_EVIDENCE_SCHEMA
    assert contract["accepted_backend"] == "standard_cpu_single"
    assert "abs(final_time_s-frozen_time_max_s)<=tolerance_s" in contract["time_acceptance_rule"]
    assert contract["evidence_authentication_performed_here"] is False
    assert any("no TERMINATE file" in item for item in receipt["future_runtime_adjudication_requirements"])
    assert receipt["source_evidence"]["cpu_dispatch"]["functions"]["ComputeStep"]["anchors"]
    assert receipt["implementation"]["sha256"]
    assert receipt["test"]["sha256"]
    assert receipt["T1_numerical"] is False
    assert receipt["qualification_credit"] == 0
    assert receipt["execution_authority"]["solver"] is False
    assert receipt["execution_authority"]["worker"] is False
    assert receipt["execution_authority"]["denominator_mutation"] == 0


def test_runtime_completion_evidence_uses_preregistered_numeric_tolerance_as_untrusted_diagnostic():
    verdict = audit.diagnose_runtime_completion_evidence(_runtime_evidence())

    assert verdict["schema"] == audit.RUNTIME_EVIDENCE_SCHEMA
    assert verdict["state"] == "untrusted_runtime_evidence_diagnostic_only"
    assert verdict["conditions_satisfied_untrusted"] is True
    assert "accepted" not in verdict
    assert verdict["tolerance_s"] == pytest.approx(0.021)
    assert verdict["evidence_authenticated"] is False
    assert verdict["solver_timestep_adjudicated"] is False
    assert verdict["trusted_acceptance_verdict_issued"] is False


def test_runtime_completion_evidence_rejects_early_or_unaudited_execution():
    verdict = audit.diagnose_runtime_completion_evidence(_runtime_evidence(
        backend="gpu", final_time_s=9.9, process_exit_code=1,
        nstepsbreak_observed=True, terminate_file_observed=True,
        terminate_applied=True, unregistered_control_override_observed=True,
        gpu_enabled=True, openmp_enabled=True, vres_enabled=True,
    ))

    assert verdict["conditions_satisfied_untrusted"] is False
    assert "backend_not_standard_cpu_single" in verdict["violations"]
    assert "final_time_outside_preregistered_tolerance" in verdict["violations"]
    assert "solver_process_did_not_exit_successfully" in verdict["violations"]
    assert "nstepsbreak_observed" in verdict["violations"]
    assert "terminate_file_observed" in verdict["violations"]
    assert "terminate_time_max_was_changed_by_terminate" in verdict["violations"]
    assert "unregistered_runtime_override_observed" in verdict["violations"]
    assert "gpu_backend_enabled" in verdict["violations"]
    assert "openmp_backend_enabled" in verdict["violations"]
    assert "vres_backend_enabled" in verdict["violations"]


def test_runtime_completion_evidence_requires_tolerance_preregistration():
    verdict = audit.diagnose_runtime_completion_evidence(
        _runtime_evidence(tolerance_preregistration_claim=False)
    )
    assert verdict["conditions_satisfied_untrusted"] is False
    assert "tolerance_not_claimed_preregistered" in verdict["violations"]


def test_runtime_completion_evidence_rejects_unknown_fields():
    with pytest.raises(audit.TimestepSemanticsError, match="frozen schema"):
        audit.diagnose_runtime_completion_evidence(
            _runtime_evidence(extra="not registered")
        )


def test_untrusted_tolerance_claim_cannot_issue_an_early_stop_acceptance():
    verdict = audit.diagnose_runtime_completion_evidence(_runtime_evidence(
        final_time_s=0.0, absolute_tolerance_s=10.0, relative_tolerance=0.0,
    ))

    assert verdict["conditions_satisfied_untrusted"] is True
    assert verdict["trusted_acceptance_verdict_issued"] is False
    assert "accepted" not in verdict


def test_cli_integrator_override_drift_fails_closed():
    sources, pack, definitions = _inputs()
    sources["cli"] = sources["cli"].replace(
        b'else if(txword=="SYMPLECTIC")TStep=STEP_Symplectic;',
        b'else if(txword=="SYMPLECTIC_DISABLED")TStep=STEP_Symplectic;',
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="symplectic_cli_override"):
        audit._audit_blobs(sources, pack, definitions)


def test_cli_integrator_override_cannot_be_hidden_under_an_unreachable_if():
    sources, pack, definitions = _inputs()
    sources["config"] = sources["config"].replace(
        b"if(cfg->TStep)TStep=cfg->TStep;",
        b"if(false)if(cfg->TStep)TStep=cfg->TStep;",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="runtime_config_can_override_integrator"):
        audit._audit_blobs(sources, pack, definitions)


def test_symplectic_step_flow_drift_fails_closed():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"const double dt_p=DtVariable(false);",
        b"const double dt_p=DtVariable(true);",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="symplectic_predictor_candidate_not_final"):
        audit._audit_blobs(sources, pack, definitions)


def test_dtmax_update_cannot_be_hidden_under_an_unreachable_final_guard():
    sources, pack, definitions = _inputs()
    sources["cpu_dt"] = sources["cpu_dt"].replace(
        b"if(final){", b"if(false)if(final){", 1
    )

    with pytest.raises(audit.TimestepSemanticsError, match="recorded_part_max_inside_final_guard"):
        audit._audit_blobs(sources, pack, definitions)


def test_nsteps_early_exit_change_fails_closed():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"if(NstepsBreak && Nstep>=NstepsBreak)break;",
        b"if(NstepsBreak && Nstep>=NstepsBreak)continue;",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="nsteps_break_can_exit_early"):
        audit._audit_blobs(sources, pack, definitions)


def test_xml_then_cli_integrator_precedence_is_ordered_inside_load_case_config():
    sources, pack, definitions = _inputs()
    xml_call = b"LoadConfigParameters(cxml);"
    cli_call = b"LoadConfigCommands(cfg);"
    config = sources["config"]
    assert config.count(xml_call) == config.count(cli_call) == 1
    config = config.replace(xml_call, b"TEMP_CONFIG_CALL;", 1)
    config = config.replace(cli_call, xml_call, 1)
    sources["config"] = config.replace(b"TEMP_CONFIG_CALL;", cli_call, 1)

    with pytest.raises(audit.TimestepSemanticsError, match="control/data-flow order changed: config.LoadCaseConfig"):
        audit._audit_blobs(sources, pack, definitions)


def test_comment_or_string_decoy_cannot_satisfy_a_function_anchor():
    sources, pack, definitions = _inputs()
    real = b"if(cfg->TStep)TStep=cfg->TStep;"
    decoy = (b'// if(cfg->TStep)TStep=cfg->TStep;\n'
             b'  const char* note="if(cfg->TStep)TStep=cfg->TStep;";')
    assert sources["config"].count(real) == 1
    sources["config"] = sources["config"].replace(real, decoy, 1)

    with pytest.raises(audit.TimestepSemanticsError, match="runtime_config_can_override_integrator"):
        audit._audit_blobs(sources, pack, definitions)


def test_disabled_preprocessor_branch_cannot_satisfy_a_function_anchor():
    sources, pack, definitions = _inputs()
    real = b"if(cfg->TStep)TStep=cfg->TStep;"
    disabled = b"#if 0\n  if(cfg->TStep)TStep=cfg->TStep;\n#endif"
    sources["config"] = sources["config"].replace(real, disabled, 1)

    with pytest.raises(audit.TimestepSemanticsError, match="inside conditional compilation"):
        audit._audit_blobs(sources, pack, definitions)


def test_disabled_cpu_header_cannot_supply_dispatcher_evidence():
    sources, pack, definitions = _inputs()
    header = sources["cpu_dispatch"].replace(
        b'#include <string>\n', b'#include <string>\n#if 0\n', 1
    )
    prefix, final_endif = header.rsplit(b"#endif", 1)
    sources["cpu_dispatch"] = prefix + b"#endif\n#endif" + final_endif

    with pytest.raises(audit.TimestepSemanticsError, match="inside conditional compilation"):
        audit._audit_blobs(sources, pack, definitions)


def test_backslash_continued_line_comment_cannot_hide_an_anchor():
    sources, pack, definitions = _inputs()
    real = b"if(cfg->TStep)TStep=cfg->TStep;"
    continued_comment = b"// disabled by continuation \\\nif(cfg->TStep)TStep=cfg->TStep;"
    sources["config"] = sources["config"].replace(real, continued_comment, 1)

    with pytest.raises(audit.TimestepSemanticsError, match="line continuations are unsupported"):
        audit._audit_blobs(sources, pack, definitions)


def test_cpu_dispatcher_must_select_matching_integrator():
    sources, pack, definitions = _inputs()
    sources["cpu_dispatch"] = sources["cpu_dispatch"].replace(
        b"return(TStep==STEP_Verlet? ComputeStep_Ver(): ComputeStep_Sym());",
        b"return(TStep==STEP_Verlet? ComputeStep_Sym(): ComputeStep_Ver());",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="cpu_dispatches_verlet_or_symplectic"):
        audit._audit_blobs(sources, pack, definitions)


def test_terminate_file_semantics_drift_fails_closed():
    sources, pack, definitions = _inputs()
    sources["config"] = sources["config"].replace(
        b"if(!Mgpu)TimeMax=tmax;",
        b"// if(!Mgpu)TimeMax=tmax;\n      const char* note=\"if(!Mgpu)TimeMax=tmax;\";",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="termination_time_max_assignment"):
        audit._audit_blobs(sources, pack, definitions)


def test_terminate_time_max_write_must_remain_in_mtime_change_branch():
    sources, pack, definitions = _inputs()
    original = (
        b"    TerminateTimeMax=tmax;\n"
        b"    if(!Mgpu)TimeMax=tmax;\n"
        b"  }\n"
        b"  TerminateMt=tmodif;"
    )
    moved = (
        b"    TerminateTimeMax=tmax;\n"
        b"  }\n"
        b"  if(false){\n"
        b"    if(!Mgpu)TimeMax=tmax;\n"
        b"  }\n"
        b"  TerminateMt=tmodif;"
    )
    assert sources["config"].count(original) == 1
    sources["config"] = sources["config"].replace(original, moved, 1)

    with pytest.raises(audit.TimestepSemanticsError, match="escaped its file-mtime change branch"):
        audit._audit_blobs(sources, pack, definitions)


def test_cpu_save_chain_must_reach_base_termination_check():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"JSph::SaveData(npsave,arrays,1,&vdom,infoplus);",
        b"// JSph::SaveData(npsave,arrays,1,&vdom,infoplus);",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="derived_save_calls_base"):
        audit._audit_blobs(sources, pack, definitions)


def test_integrator_anchor_cannot_be_moved_into_dead_or_nested_code():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"ComputeVerlet(dt);",
        b"if(false){ComputeVerlet(dt);}",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="conditional, nested"):
        audit._audit_blobs(sources, pack, definitions)


def test_integrator_dt_shadowing_fails_closed():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"ComputeVerlet(dt);",
        b"{ const auto dt=0; } ComputeVerlet(dt);",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="binding is shadowed or mutable"):
        audit._audit_blobs(sources, pack, definitions)


def test_cpu_loop_cannot_shadow_member_time_step():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"TimeStep+=stepdt;",
        b"const double TimeStep=0; TimeStep+=stepdt;",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="member binding is shadowed"):
        audit._audit_blobs(sources, pack, definitions)


def test_integrator_early_return_fails_closed():
    sources, pack, definitions = _inputs()
    sources["cpu_loop"] = sources["cpu_loop"].replace(
        b"ComputeVerlet(dt);",
        b"if(false)return(0); ComputeVerlet(dt);",
        1,
    )

    with pytest.raises(audit.TimestepSemanticsError, match="early/alternate return path"):
        audit._audit_blobs(sources, pack, definitions)


def test_definition_bytes_must_match_the_frozen_pack():
    sources, pack, definitions = _inputs()
    path = next(iter(definitions))
    definitions[path] += b"\n"

    with pytest.raises(audit.TimestepSemanticsError, match="Definition bytes do not match"):
        audit._audit_blobs(sources, pack, definitions)


def test_strict_json_rejects_duplicate_keys():
    with pytest.raises(audit.TimestepSemanticsError, match="duplicate JSON keys"):
        audit._strict_json(b'{"cases":[],"cases":[]}')


def test_read_regular_rejects_parent_traversal(tmp_path: Path):
    with pytest.raises(audit.TimestepSemanticsError, match="bounded relative path"):
        audit._read_regular(tmp_path, "../outside")


def test_read_regular_rejects_final_symlink(tmp_path: Path):
    target = tmp_path / "target"
    target.write_bytes(b"evidence")
    (tmp_path / "link").symlink_to(target)

    with pytest.raises(OSError):
        audit._read_regular(tmp_path, "link")


def test_read_regular_rejects_nested_directory_symlink(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "evidence").write_bytes(b"evidence")
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)

    with pytest.raises(OSError):
        audit._read_regular(tmp_path, "alias/evidence")


def test_read_regular_rejects_hardlinks(tmp_path: Path):
    original = tmp_path / "original"
    original.write_bytes(b"evidence")
    os.link(original, tmp_path / "second-name")

    with pytest.raises(audit.TimestepSemanticsError, match="single-link regular file"):
        audit._read_regular(tmp_path, "original")


def test_read_regular_rejects_oversized_file(tmp_path: Path, monkeypatch):
    (tmp_path / "large").write_bytes(b"12345")
    monkeypatch.setattr(audit, "MAX_EVIDENCE_BYTES", 4)

    with pytest.raises(audit.TimestepSemanticsError, match="byte limit"):
        audit._read_regular(tmp_path, "large")


def test_read_regular_detects_mutation_while_reading(tmp_path: Path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.write_bytes(b"original bytes")
    real_read = os.read
    changed = False

    def mutate_then_read(fd, size):
        nonlocal changed
        block = real_read(fd, size)
        if not changed:
            changed = True
            write_fd = os.open(evidence, os.O_WRONLY)
            try:
                os.write(write_fd, b"mutated bytes!")
            finally:
                os.close(write_fd)
            future = time.time_ns() + 5_000_000_000
            os.utime(evidence, ns=(future, future))
        return block

    monkeypatch.setattr(audit.os, "read", mutate_then_read)
    with pytest.raises(audit.TimestepSemanticsError, match="changed while being read"):
        audit._read_regular(tmp_path, "evidence")


def test_read_regular_fails_closed_without_nofollow_support(tmp_path: Path, monkeypatch):
    (tmp_path / "evidence").write_bytes(b"evidence")
    monkeypatch.setattr(audit, "O_NOFOLLOW", 0)

    with pytest.raises(audit.TimestepSemanticsError, match="lacks required O_NOFOLLOW"):
        audit._read_regular(tmp_path, "evidence")


def test_receipt_writer_refuses_overwrite(tmp_path: Path):
    parent_fd = _open_dir(tmp_path)
    try:
        payload = json.dumps({"schema": audit.SCHEMA}, sort_keys=True).encode("utf-8")
        audit._write_receipt_at(parent_fd, "receipt.json", payload)
        with pytest.raises(FileExistsError):
            audit._write_receipt_at(parent_fd, "receipt.json", b'{"overwritten":true}')
        assert (tmp_path / "receipt.json").read_bytes() == payload
        assert sorted(path.name for path in tmp_path.iterdir()) == ["receipt.json"]
    finally:
        os.close(parent_fd)


def test_receipt_writer_refuses_preexisting_symlink(tmp_path: Path):
    target = tmp_path / "target"
    target.write_bytes(b"do not modify")
    (tmp_path / "receipt.json").symlink_to(target)
    parent_fd = _open_dir(tmp_path)
    try:
        with pytest.raises(FileExistsError):
            audit._write_receipt_at(parent_fd, "receipt.json", b"receipt")
        assert target.read_bytes() == b"do not modify"
        assert (tmp_path / "receipt.json").is_symlink()
        assert sorted(path.name for path in tmp_path.iterdir()) == ["receipt.json", "target"]
    finally:
        os.close(parent_fd)


def test_receipt_writer_failure_does_not_publish_partial_final(tmp_path: Path, monkeypatch):
    parent_fd = _open_dir(tmp_path)
    real_write = os.write
    calls = 0

    def fail_after_partial(fd, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, payload[:3])
        raise OSError(errno.EIO, "injected mid-write failure")

    monkeypatch.setattr(audit.os, "write", fail_after_partial)
    try:
        with pytest.raises(OSError, match="injected mid-write"):
            audit._write_receipt_at(parent_fd, "receipt.json", b"complete payload")
        assert not (tmp_path / "receipt.json").exists()
        assert list(tmp_path.iterdir()) == []
    finally:
        os.close(parent_fd)


def test_receipt_writer_publishes_from_anonymous_inode(tmp_path: Path, monkeypatch):
    parent_fd = _open_dir(tmp_path)
    real_link = os.link
    source_paths = []

    def observe_link(source, destination, **kwargs):
        source_paths.append(source)
        assert source.startswith("/proc/self/fd/")
        assert list(tmp_path.iterdir()) == []
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(audit.os, "link", observe_link)
    try:
        audit._write_receipt_at(parent_fd, "receipt.json", b"anonymous payload")
        assert len(source_paths) == 1
        assert (tmp_path / "receipt.json").read_bytes() == b"anonymous payload"
        assert sorted(path.name for path in tmp_path.iterdir()) == ["receipt.json"]
    finally:
        os.close(parent_fd)


def test_receipt_writer_link_failure_cleans_only_its_temp(tmp_path: Path, monkeypatch):
    parent_fd = _open_dir(tmp_path)

    def fail_link(*args, **kwargs):
        raise OSError(errno.EIO, "injected link failure")

    monkeypatch.setattr(audit.os, "link", fail_link)
    try:
        with pytest.raises(OSError, match="injected link failure"):
            audit._write_receipt_at(parent_fd, "receipt.json", b"complete payload")
        assert not (tmp_path / "receipt.json").exists()
        assert list(tmp_path.iterdir()) == []
    finally:
        os.close(parent_fd)


def test_receipt_writer_concurrent_publishers_are_no_overwrite(tmp_path: Path):
    parent_fd = _open_dir(tmp_path)
    payloads = [b"publisher one", b"publisher two"]

    def publish(payload):
        try:
            audit._write_receipt_at(parent_fd, "receipt.json", payload)
            return "published"
        except FileExistsError:
            return "exists"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, payloads))
        assert sorted(results) == ["exists", "published"]
        assert (tmp_path / "receipt.json").read_bytes() in payloads
        assert sorted(path.name for path in tmp_path.iterdir()) == ["receipt.json"]
    finally:
        os.close(parent_fd)
