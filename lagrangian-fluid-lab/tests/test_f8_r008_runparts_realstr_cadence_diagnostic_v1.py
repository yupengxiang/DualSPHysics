from __future__ import annotations

from pathlib import Path
import re

import pytest

from scripts import f8_r008_runparts_realstr_cadence_diagnostic_v1 as diagnostic


def _row(part: int, time_token: str, *, steps: int = 10, dt_min: str = "0.001",
         dt_max: str = "0.002") -> str:
    cells = ["0"] * len(diagnostic.RUNPARTS_HEADER)
    cells[0] = str(part)
    cells[1] = time_token
    cells[2] = "0" if part == 0 else str(steps)
    cells[19] = "0" if part == 0 else dt_min
    cells[20] = "0" if part == 0 else dt_max
    return ";".join(cells)


def _payload(time_tokens: tuple[str, ...]) -> bytes:
    lines = [";".join(diagnostic.RUNPARTS_HEADER)]
    lines.extend(_row(index, token) for index, token in enumerate(time_tokens))
    lines.append("")
    lines.extend(diagnostic.RUNPARTS_FOOTER)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _simple_payload() -> bytes:
    return _payload(("0", "0.3500000000000000", "0.8100000000000000", "1.200000000000000"))


def _simple_config() -> dict[str, str]:
    return {"mode": "simple", "time_part_token": "0.1"}


def _assert_untrusted(receipt: dict[str, object]) -> None:
    assert receipt["source_authenticated"] is False
    assert receipt["runtime_authenticated"] is False
    assert receipt["native_integrity_evaluated"] is False
    assert receipt["T1_numerical"] is False
    assert receipt["gate_decision_eligible"] is False
    assert receipt["qualification_credit"] == 0
    assert receipt["execution_authority"] == {
        "native_solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
    }


def test_valid_simple_cadence_keeps_raw_realstr_tokens_and_binary64_crossings() -> None:
    payload = _simple_payload()
    receipt = diagnostic.build_diagnostic_receipt(
        payload,
        case_id="synthetic-simple",
        t_end_token="1.0",
        output_time=_simple_config(),
    )

    assert receipt["status"] == "synthetic_structural_untrusted"
    assert receipt["checks"] == {
        "synthetic_only": True,
        "production_hdf5_read": False,
        "native_solver_or_worker_run": False,
        "raw_csv_shape": True,
        "raw_realstr_tokens_preserved": True,
        "realstr_emission_proven": False,
        "binary64_stateful_outputtime_evaluated": True,
        "cadence_consistent": True,
        "t_end_reached": True,
        "final_savedata_observed": True,
        "no_final_savedata_detected": False,
        "single_attempt_label_consistent": False,
    }
    assert receipt["runparts"]["raw_rows"][1]["time_step_token"] == "0.3500000000000000"
    assert receipt["runparts"]["raw_rows"][1]["realstr_time_step_token"] == "0.3500000000000000"
    assert receipt["runparts"]["raw_rows"][1]["tokens"][1] == "0.3500000000000000"
    assert receipt["runparts"]["raw_rows"][1]["time_step_binary64"]["hex"] == float(
        "0.3500000000000000"
    ).hex()
    summary = receipt["cadence_summary"]
    assert summary["output_time_mode"] == "simple"
    assert summary["multi_target_crossing_observed"] is True
    assert summary["overshot_t_end"] is True
    assert _simple_config()["time_part_token"] == "0.1"
    _assert_untrusted(receipt)


def test_special_outputtime_crosses_multiple_cadence_bases_and_preserves_schedule_tokens() -> None:
    payload = _payload(("0", "0.3500000000000000", "0.9000000000000000", "1.200000000000000"))
    config = {
        "mode": "special",
        "segments": [
            {"time_token": "0", "timeout_token": "0.1"},
            {"time_token": "0.5", "timeout_token": "0.2"},
            {"time_token": "1.0", "timeout_token": "0.25"},
        ],
    }
    receipt = diagnostic.build_diagnostic_receipt(
        payload, case_id="synthetic-special", t_end_token="1.0", output_time=config
    )

    assert receipt["status"] == "synthetic_structural_untrusted"
    assert receipt["output_time_config"]["segments"][1] == {
        "time_token": "0.5",
        "timeout_token": "0.2",
        "time_binary64": {"value": 0.5, "hex": 0.5.hex()},
        "timeout_binary64": {"value": 0.2, "hex": 0.2.hex()},
    }
    trace = receipt["cadence_trace"]
    assert trace[2]["outputtime_transition"]["time_base_after"] == 1
    assert trace[2]["crossed_target_count_lower_bound"] > 1
    assert trace[2]["outputtime_transition"]["returned_next_time"]["value"] == 1.0
    assert receipt["cadence_summary"]["multi_target_crossing_observed"] is True
    _assert_untrusted(receipt)


def test_stateful_outputtime_reuses_exact_same_binary64_input() -> None:
    state = diagnostic._OutputTimeState(
        diagnostic._parse_output_time_config(_simple_config())
    )
    first = state.get_next(0.0, "0")
    cached = state.get_next(float("0.0"), "0.0000000000000000")

    assert first["returned_next_time"]["value"] == 0.1
    assert cached["last_input_reused"] is True
    assert cached["returned_next_time"] == first["returned_next_time"]
    assert cached["input_time_token"] == "0.0000000000000000"


def test_binary64_equality_uses_parsed_tokens_without_normalizing_them() -> None:
    payload = _payload(("0", "0.10000000000000001", "0.20000000000000001", "0.30000000000000004"))
    receipt = diagnostic.build_diagnostic_receipt(
        payload, case_id="binary64", t_end_token="0.3", output_time=_simple_config()
    )

    assert receipt["status"] == "synthetic_structural_untrusted"
    assert receipt["runparts"]["raw_rows"][1]["time_step_token"] == "0.10000000000000001"
    assert receipt["runparts"]["raw_rows"][1]["time_step_binary64"]["value"] == 0.1
    assert receipt["cadence_trace"][1]["save_due_to_outputtime"] is True
    assert receipt["cadence_trace"][1]["outputtime_transition"]["returned_next_time"]["value"] == 0.2
    _assert_untrusted(receipt)


def test_footer_does_not_fake_a_final_savedata() -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _payload(("0", "0.35", "0.8")),
        case_id="missing-final",
        t_end_token="1.0",
        output_time=_simple_config(),
    )

    assert receipt["status"] == "synthetic_structural_untrusted_rejected"
    assert receipt["runparts"]["footer_present"] is True
    assert receipt["checks"]["t_end_reached"] is False
    assert receipt["checks"]["final_savedata_observed"] is False
    assert receipt["checks"]["no_final_savedata_detected"] is True
    assert receipt["diagnostic_findings"][-1]["code"] == "FINAL_SAVEDATA_MISSING"
    _assert_untrusted(receipt)


def test_savedata_before_cadence_crossing_is_rejected_without_trust_credit() -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _payload(("0", "0.05", "1.0")),
        case_id="early-save",
        t_end_token="0.9",
        output_time=_simple_config(),
    )

    assert receipt["status"] == "synthetic_structural_untrusted_rejected"
    assert receipt["diagnostic_findings"][0]["code"] == "OUTPUTTIME_CADENCE_MISMATCH"
    assert receipt["checks"]["cadence_consistent"] is False
    _assert_untrusted(receipt)


@pytest.mark.parametrize(
    "tokens,code",
    [
        (("0", "0.1", "0.1"), "TIME_SEQUENCE_REJECTED"),
        (("0", "0.2", "0.1"), "TIME_SEQUENCE_REJECTED"),
        (("0", "nan", "0.2"), "NONFINITE_TIME_TOKEN"),
        (("0", "0.1", "inf"), "NONFINITE_TIME_TOKEN"),
        (("0",), "RUNPARTS_ROW_REJECTED"),
    ],
)
def test_duplicate_nonincreasing_nan_and_short_raw_inputs_fail_closed(
    tokens: tuple[str, ...], code: str
) -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _payload(tokens),
        case_id="invalid-raw",
        t_end_token="1.0",
        output_time=_simple_config(),
    )

    assert receipt["status"] == "synthetic_structural_untrusted_rejected"
    assert receipt["diagnostic_findings"][0]["code"] == code
    _assert_untrusted(receipt)


@pytest.mark.parametrize(
    "config,code",
    [
        ({"mode": "simple", "time_part_token": "nan"}, "NONFINITE_TIME_TOKEN"),
        ({"mode": "simple", "time_part_token": "0"}, "NONPOSITIVE_TIMEOUT"),
        ({
            "mode": "special",
            "segments": [
                {"time_token": "0", "timeout_token": "0.1"},
                {"time_token": "0", "timeout_token": "0.2"},
            ],
        }, "OUTPUTTIME_NONINCREASING_REJECTED"),
        ({
            "mode": "special",
            "segments": [{"time_token": "0", "timeout_token": "nan"}],
        }, "NONFINITE_TIME_TOKEN"),
    ],
)
def test_repeated_nonincreasing_and_nan_outputtime_configurations_fail_closed(
    config: dict[str, object], code: str
) -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _simple_payload(), case_id="invalid-outputtime", t_end_token="1.0", output_time=config
    )

    assert receipt["status"] == "synthetic_structural_untrusted_rejected"
    assert receipt["diagnostic_findings"][0]["code"] == code
    _assert_untrusted(receipt)


def test_cross_attempt_labels_are_explicitly_rejected_and_never_authenticated() -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _simple_payload(),
        case_id="cross-attempt",
        t_end_token="1.0",
        output_time=_simple_config(),
        attempt_labels=("attempt-a", "attempt-a", "attempt-b", "attempt-b"),
    )

    assert receipt["status"] == "synthetic_structural_untrusted_rejected"
    assert receipt["diagnostic_findings"][0]["code"] == "CROSS_ATTEMPT_REJECTED"
    assert "attempt_input" not in receipt
    _assert_untrusted(receipt)


def test_consistent_attempt_labels_remain_untrusted_caller_supplied_metadata() -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _simple_payload(),
        case_id="single-attempt-label",
        t_end_token="1.0",
        output_time=_simple_config(),
        attempt_labels=("attempt-a",) * 4,
    )

    assert receipt["status"] == "synthetic_structural_untrusted"
    assert receipt["attempt_input"] == {
        "labels_supplied": True,
        "labels_consistent": True,
        "cross_attempt_detected": False,
        "labels_untrusted": True,
    }
    assert receipt["checks"]["single_attempt_label_consistent"] is True
    assert receipt["source_authenticated"] is False
    _assert_untrusted(receipt)


def test_t_end_nan_is_rejected_and_does_not_leak_partial_trust() -> None:
    receipt = diagnostic.build_diagnostic_receipt(
        _simple_payload(), case_id="nan-end", t_end_token="NaN", output_time=_simple_config()
    )

    assert receipt["status"] == "synthetic_structural_untrusted_rejected"
    assert receipt["diagnostic_findings"][0]["code"] == "NONFINITE_TIME_TOKEN"
    _assert_untrusted(receipt)


def test_parser_contract_matches_jsph_source_header_and_footer() -> None:
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "src/source/JSph.cpp").read_text(encoding="utf-8")
    header_start = source.index("void JSph::SaveRunPartsCsv(")
    header_end = source.index("//-Saves data.", header_start)
    fragments = re.findall(r'scsv << "([^"]*)";', source[header_start:header_end])
    source_header = tuple(";".join(fragments).split(";"))
    footer_start = source.index("void JSph::SaveRunPartsCsvFinal()")
    footer_end = source.index("/// Stores files of particle data.", footer_start)
    source_footer = tuple(re.findall(
        r'scsv << "(#.*)" << jcsv::Endl\(\);', source[footer_start:footer_end]
    ))

    assert source_header == diagnostic.RUNPARTS_HEADER
    assert source_footer == diagnostic.RUNPARTS_FOOTER


def test_raw_payload_size_bound_is_applied_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostic, "MAX_RUNPARTS_BYTES", 8)
    receipt = diagnostic.build_diagnostic_receipt(
        b"x" * 9, case_id="bounded", t_end_token="1.0", output_time=_simple_config()
    )

    assert receipt["diagnostic_findings"][0]["code"] == "RUNPARTS_BOUNDS_REJECTED"
    _assert_untrusted(receipt)


def test_special_segment_count_bound_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostic, "MAX_OUTPUTTIME_SEGMENTS", 1)
    config = {
        "mode": "special",
        "segments": [
            {"time_token": "0", "timeout_token": "0.1"},
            {"time_token": "1", "timeout_token": "0.1"},
        ],
    }
    receipt = diagnostic.build_diagnostic_receipt(
        _simple_payload(), case_id="bounded-schedule", t_end_token="1.0", output_time=config
    )

    assert receipt["diagnostic_findings"][0]["code"] == "OUTPUTTIME_BOUNDS_REJECTED"
    _assert_untrusted(receipt)
