from scripts import l1_f1_qualification as l1


def test_l1_scope_is_f1_only_and_preserves_hard_limits():
    assert l1.BASELINE_COMMIT == "dc9533eecf7ee608a1db04ea4e26bb80cd2b456a"
    assert l1.GPU_IDS == (4, 5, 6, 7)
    assert l1.PROTECTED_GPU_IDS == (0, 1, 2, 3)
    assert l1.TIME_MAX_S == 1.5
    assert l1.TIME_OUT_S == 0.001
    assert l1.TIME_GATE == {
        "distribution_tv": 0.01,
        "com_l2_m": 0.012,
        "front_q90_abs_delta_m": 0.012,
    }
    assert l1.SPACE_GATE == {
        "distribution_tv": 0.05,
        "com_l2_m": 0.06,
        "front_q90_abs_delta_m": 0.06,
    }


def test_case_design_has_unique_ids_and_no_protected_gpu():
    records = l1.time_records(0.05) + l1.space_records(0.05)
    ids = [record["case_id"] for record in records]
    assert len(ids) == len(set(ids))
    assert len(records) == 11
    assert {record["family"] for record in records} == {"F1"}
    assert {record["background_id"] for record in records} == {"plain_dam_break"}
    assert {record["gpu"] for record in records}.issubset(set(l1.GPU_IDS))
    assert all(record["formal_release"] is False for record in records)
    assert all(record["development_authorized"] is False for record in records)


def test_time_gate_comparison_uses_registered_grid_and_initial_mass_distribution():
    def audit(value):
        return {
            "fixed_time_grid": [
                {
                    "requested_time_s": 0.0,
                    "actual_time_s": 0.0,
                    "distribution": {"a": 0.7, "b": 0.3},
                    "com_m": [value, 0.0, 0.0],
                    "front_quantiles_m": {"q90": value},
                    "kinetic_energy_proxy_j": 1.0,
                },
                {
                    "requested_time_s": 1.5,
                    "actual_time_s": 1.5,
                    "distribution": {"a": 0.7, "b": 0.3},
                    "com_m": [value, 0.0, 0.0],
                    "front_quantiles_m": {"q90": value},
                    "kinetic_energy_proxy_j": 1.0,
                },
            ]
        }

    result = l1.compare_time(audit(0.0), audit(0.005))
    assert result["time_grid_count"] == 2
    assert result["status"] == "pass"
    assert result["maxima"]["com_l2_m"] == 0.005


def test_w0_inventory_records_no_new_solver_attempts():
    import json

    report = json.loads((l1.CAMPAIGN / "L1-W00-INVENTORY.json").read_text())
    assert report["status"] == "completed_read_only"
    assert report["new_activity_before_capture"]["solver_attempts"] == 0
    assert report["historical_n4"]["fifth_attempt_allowed"] is False
    assert report["attachment_provenance"]["expected_sha256"] == (
        "2140048e019b2074668799aef145314af90eae242498450c069bbdb910aab5e3"
    )


def test_allowlist_reads_w0_gpu_policy():
    assert set(l1.allowed_uuids()) == {
        "GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9",
        "GPU-b5e3f067-fe26-4c00-5805-00a4f5acde32",
        "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
        "GPU-88bfe7db-87fb-d458-719b-eb9a098f8f51",
    }
