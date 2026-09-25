"""Synthetic-only tests for the non-authorizing V5 journal shape parser."""
import hashlib
import json
import math
import shlex
import subprocess
import struct

import pytest
import scripts.f8_r008_c_execution_journal_v5 as journal_v5

from scripts.f8_r008_c_execution_journal_v5 import (
    JOURNAL_SCHEMA,
    JournalV5Error,
    SOURCE_CALLGRAPH_OBJECT_ID,
    SOURCE_CALLGRAPH_SCHEMA,
    inspect_untrusted_v5_journal,
    inspect_untrusted_v5_journal_with_source_callgraph,
    inspect_untrusted_v5_source_callgraph,
    inspect_untrusted_v5_source_callgraph_against_git_head,
)


NONCE = "a" * 32
MONO = "00000000000003e8"


def _process(birth_seq=0, *, pid=42):
    return {
        "pid_namespace_inode_hex": "0000000000000001",
        "pid": pid,
        "start_monotonic_ns_hex": "0000000000000002",
        "kernel_starttime_ticks_hex": "0000000000000003",
        "birth_seq_hex": f"{birth_seq:016x}",
    }


def _thread(birth_seq=0, *, tid=43):
    return {
        "tid": tid,
        "start_monotonic_ns_hex": "0000000000000002",
        "kernel_starttime_ticks_hex": "0000000000000003",
        "birth_seq_hex": f"{birth_seq:016x}",
    }


def _event(kind, seq, **fields):
    return {
        "seq": seq,
        "mono_ns_hex": MONO,
        "kind": kind,
        "attempt_nonce_hex": NONCE,
        **fields,
    }


def _main_events(*, poll_outcome="returned", include_poll_end=True, include_terminal_guard=False):
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "exec", 1, process_generation_id=proc, executable_binding={"synthetic": True},
            argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64,
        ),
        _event(
            "loop_guard", 2, process_generation_id=proc, driver_id="main",
            loop_iteration_id=0, time_step_ieee754_hex="0000000000000000",
            time_max_ieee754_hex="3ff0000000000000", condition_result=True,
        ),
        _event(
            "poll_begin", 3, poll_begin_id=3, process_generation_id=proc,
            solver_instance_id="main", driver_id="main", guard_seq=2,
            callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
            interstep="INTERSTEP_Verlet", input_entry_index=0,
            timestep_ieee754_hex="0000000000000000", active=False,
            cache_action="miss", cache_source_seq=None, table_raw_binding=None,
        ),
    ]
    if include_poll_end:
        events.append(_event(
            "poll_end", 4, poll_begin_id=3, process_generation_id=proc,
            outcome=poll_outcome,
        ))
        if include_terminal_guard:
            events.append(_event(
                "loop_guard", len(events), process_generation_id=proc, driver_id="main",
                loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000",
                time_max_ieee754_hex="3ff0000000000000", condition_result=False,
            ))
        exit_seq = len(events)
        events.extend([
            _event("exit", exit_seq, process_generation_id=proc, exit_code=0, signal=None),
            _event("reap", exit_seq + 1, process_generation_id=proc),
        ])
    return events


def _journal_with_polls(specs):
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "exec", 1, process_generation_id=proc, executable_binding={"synthetic": True},
            argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64,
        ),
    ]
    caches = {}
    observed_timesteps = []
    for iteration, spec in enumerate(specs):
        timestep_hex = spec.get("timestep", "0000000000000000")
        timestep = struct.unpack(">d", bytes.fromhex(timestep_hex))[0]
        time_max = math.nextafter(timestep, math.inf)
        if not math.isfinite(time_max):
            raise ValueError("synthetic true guard requires a finite next binary64 timestep")
        observed_timesteps.append(timestep)
        solver_instance_id = spec.get("solver_instance_id", "main")
        input_entry_index = spec.get("input_entry_index", 0)
        slot = caches.setdefault((solver_instance_id, input_entry_index), {
            "last_timestep": -1.0,
            "source_seq": None,
        })
        guard_seq = len(events)
        events.append(_event(
            "loop_guard", guard_seq, process_generation_id=proc, driver_id="main",
            loop_iteration_id=iteration, time_step_ieee754_hex=timestep_hex,
            time_max_ieee754_hex=struct.pack(">d", time_max).hex(), condition_result=True,
        ))
        begin_seq = len(events)
        is_hit = slot["last_timestep"] >= 0 and timestep == slot["last_timestep"]
        action = "hit" if is_hit else "miss"
        ref = slot["source_seq"] if is_hit else None
        action = spec.get("cache_action", action)
        ref = spec.get("cache_source_seq", ref)
        active = spec.get("active", False)
        events.append(_event(
            "poll_begin", begin_seq, poll_begin_id=begin_seq, process_generation_id=proc,
            solver_instance_id=solver_instance_id, driver_id="main", guard_seq=guard_seq,
            callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
            interstep="INTERSTEP_Verlet", input_entry_index=input_entry_index,
            timestep_ieee754_hex=timestep_hex, active=active,
            cache_action=action, cache_source_seq=ref,
            table_raw_binding=spec.get(
                "table_raw_binding", {"synthetic": True} if active else None
            ),
        ))
        if not is_hit:
            slot["last_timestep"] = timestep
            slot["source_seq"] = begin_seq
        if spec.get("outcome", "returned") is not None:
            events.append(_event(
                "poll_end", len(events), poll_begin_id=begin_seq,
                process_generation_id=proc, outcome=spec.get("outcome", "returned"),
            ))

    all_polls_terminal = all(spec.get("outcome", "returned") is not None for spec in specs)
    if all_polls_terminal:
        terminal_step = math.nextafter(max(observed_timesteps, default=1.0), math.inf)
        if not math.isfinite(terminal_step):
            raise ValueError("synthetic terminal guard requires a finite next binary64 timestep")
        terminal_hex = struct.pack(">d", terminal_step).hex()
        terminal_seq = len(events)
        events.append(_event(
            "loop_guard", terminal_seq, process_generation_id=proc, driver_id="main",
            loop_iteration_id=len(specs), time_step_ieee754_hex=terminal_hex,
            time_max_ieee754_hex=terminal_hex, condition_result=False,
        ))
        events.extend([
            _event("exit", len(events), process_generation_id=proc, exit_code=0, signal=None),
            _event("reap", len(events) + 1, process_generation_id=proc),
        ])
    return _journal(events)


def _journal(events, **updates):
    value = {
        "schema": JOURNAL_SCHEMA,
        "attempt_nonce_hex": NONCE,
        "source_id": "runtime-image-v5",
        "source_binary_sha256": "b" * 64,
        "coverage_start_ns_hex": MONO,
        "coverage_end_ns_hex": MONO,
        "event_count": len(events),
        "overflow": False,
        "lost_count": 0,
        "events": events,
    }
    value.update(updates)
    return json.dumps(value, separators=(",", ":")).encode()


def _source_callgraph(*, instances=None, driver_id="main", loop_model="single_solver_loop", solver_ids=None, fragments=None):
    if solver_ids is None:
        solver_ids = ["main"]
    if instances is None:
        instances = [{
            "solver_instance_id": "main",
            "driver_id": "main",
            "input_count": 1,
            "callsite_id": "cpu.pre_interaction_forces.run_cpu",
            "integrator": "Verlet",
            "intersteps": ["INTERSTEP_Verlet"],
        }]
    if fragments is None:
        fragments = [{
            "function_id": "main.dispatch",
            "source_file_object_id": "source.main_cpp",
            "byte_start": 1,
            "byte_end": 2,
            "fragment_raw_sha256": "c" * 64,
            "normalized_ast_sha256": "d" * 64,
            "ordered_call_edges": [],
        }]
    value = {
        "schema": SOURCE_CALLGRAPH_SCHEMA,
        "source_id": "runtime-image-v5",
        "source_binary_sha256": "b" * 64,
        "source_tree_sha256": "e" * 64,
        "build_provenance_ref": {
            "stage": "build", "role": "build_attestation", "object_id": "build-attestation-v5",
            "bytes": 128, "sha256": "f" * 64,
        },
        "runtime_image_ref": {
            "stage": "runtime", "role": "runtime_image", "object_id": "runtime-image-v5",
            "bytes": 256, "sha256": "b" * 64,
        },
        "source_fragments": fragments,
        "drivers": [{
            "driver_id": driver_id,
            "loop_model": loop_model,
            "solver_instance_ids": solver_ids,
        }],
        "instances": instances,
    }
    return json.dumps(value, separators=(",", ":")).encode()


def _source_callgraph_binding(raw, *, sha256=None, byte_count=None):
    import hashlib

    return {
        "stage": "build",
        "role": "source_callgraph",
        "object_id": SOURCE_CALLGRAPH_OBJECT_ID,
        "bytes": len(raw) if byte_count is None else byte_count,
        "sha256": hashlib.sha256(raw).hexdigest() if sha256 is None else sha256,
    }


def _vres_events(*, swap_intersteps=False):
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "exec", 1, process_generation_id=proc, executable_binding={"synthetic": True},
            argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64,
        ),
        _event(
            "loop_guard", 2, process_generation_id=proc, driver_id="vres",
            loop_iteration_id=0, time_step_ieee754_hex="0000000000000000",
            time_max_ieee754_hex="3ff0000000000000", condition_result=True,
        ),
    ]
    for instance_id in ("vres.00", "vres.01"):
        miss_seq = len(events)
        steps = ["INTERSTEP_SymPredictor", "INTERSTEP_SymCorrector"]
        if swap_intersteps:
            steps.reverse()
        for step_index, interstep in enumerate(steps):
            begin_seq = len(events)
            is_hit = step_index == 1
            events.append(_event(
                "poll_begin", begin_seq, poll_begin_id=begin_seq, process_generation_id=proc,
                solver_instance_id=instance_id, driver_id="vres", guard_seq=2,
                callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="VRes",
                interstep=interstep, input_entry_index=0, timestep_ieee754_hex="0000000000000000",
                active=False, cache_action="hit" if is_hit else "miss",
                cache_source_seq=miss_seq if is_hit else None, table_raw_binding=None,
            ))
            events.append(_event(
                "poll_end", len(events), poll_begin_id=begin_seq,
                process_generation_id=proc, outcome="returned",
            ))
    terminal_seq = len(events)
    events.extend([
        _event(
            "loop_guard", terminal_seq, process_generation_id=proc, driver_id="vres",
            loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000",
            time_max_ieee754_hex="3ff0000000000000", condition_result=False,
        ),
        _event("exit", terminal_seq + 1, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", terminal_seq + 2, process_generation_id=proc),
    ])
    return events


def test_valid_synthetic_journal_remains_open_and_non_authorizing():
    result = inspect_untrusted_v5_journal(_journal(_main_events()))
    assert result["status"] == "untrusted_v5_journal_shape_consistent"
    assert result["event_count"] == 7
    assert result["all_polls_terminal"] is True
    assert result["observed_process_lifecycle_complete"] is True
    assert result["process_generation_count"] == 1
    assert result["all_polls_returned"] is True
    assert result["gate_state"] == "open"
    assert result["event_source_completeness_verified"] is False
    assert result["process_lifecycle_verified"] is False
    assert result["query_causality_verified"] is False
    assert result["cache_replay_verified"] is False
    assert result["query_guard_link_count"] == 1
    assert result["query_guard_links_observed_consistent"] is True
    assert result["cache_transitions_observed_consistent"] is True
    assert result["cache_replay_diagnostic_state"] == "journal_local_consistent_unverified"
    assert result["execution_semantics_verified"] is False
    assert result["qualification_adjudicated"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_source_callgraph_structural_parse_is_explicitly_untrusted_and_checks_raw_ref():
    raw = _source_callgraph()
    result = inspect_untrusted_v5_source_callgraph(
        raw, source_callgraph_binding=_source_callgraph_binding(raw),
    )
    assert result["status"] == "untrusted_v5_source_callgraph_declared_shape_consistent"
    assert result["source_callgraph_binding_raw_hash_verified"] is True
    assert result["source_fragment_ids_allowlisted"] is True
    assert result["source_fragment_feature_coverage_verified"] is False
    assert result["source_fragments_reparsed_from_source"] is False
    assert "_instances_by_id" not in result

    with pytest.raises(JournalV5Error, match="raw bytes do not match"):
        inspect_untrusted_v5_source_callgraph(
            raw, source_callgraph_binding=_source_callgraph_binding(raw, sha256="a" * 64),
        )
    old_binding = _source_callgraph_binding(raw)
    old_binding["object_id"] = "f8-r008-source-callgraph-v4"
    with pytest.raises(JournalV5Error, match="frozen V5 object ID"):
        inspect_untrusted_v5_source_callgraph(raw, source_callgraph_binding=old_binding)


@pytest.mark.parametrize("bad_fragment", [
    {"function_id": "not.allowlisted", "source_file_object_id": "source.main_cpp", "byte_start": 1,
     "byte_end": 2, "fragment_raw_sha256": "c" * 64, "normalized_ast_sha256": "d" * 64,
     "ordered_call_edges": []},
    {"function_id": "main.dispatch", "source_file_object_id": "source.gpu_cpp", "byte_start": 1,
     "byte_end": 2, "fragment_raw_sha256": "c" * 64, "normalized_ast_sha256": "d" * 64,
     "ordered_call_edges": []},
    {"function_id": "main.dispatch", "source_file_object_id": "source.main_cpp", "byte_start": 2,
     "byte_end": 2, "fragment_raw_sha256": "c" * 64, "normalized_ast_sha256": "d" * 64,
     "ordered_call_edges": []},
])
def test_source_callgraph_rejects_unknown_or_malformed_fragment_projection(bad_fragment):
    with pytest.raises(JournalV5Error):
        inspect_untrusted_v5_source_callgraph(_source_callgraph(fragments=[bad_fragment]))


def test_source_callgraph_rejects_runtime_identity_copy_mismatch_and_bool_input_count():
    raw = _source_callgraph().replace(b'"source_id":"runtime-image-v5"', b'"source_id":"other-runtime"', 1)
    with pytest.raises(JournalV5Error, match="identity copies disagree"):
        inspect_untrusted_v5_source_callgraph(raw)

    instance = {
        "solver_instance_id": "main", "driver_id": "main", "input_count": True,
        "callsite_id": "cpu.pre_interaction_forces.run_cpu", "integrator": "Verlet",
        "intersteps": ["INTERSTEP_Verlet"],
    }
    with pytest.raises(JournalV5Error, match="builtin integer"):
        inspect_untrusted_v5_source_callgraph(_source_callgraph(instances=[instance]))


def _synthetic_source_repo(tmp_path, files):
    repo = tmp_path / "repo"
    for relative_path, contents in files.items():
        source_path = repo / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(contents)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(repo)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    for key, value in (("user.name", "synthetic"), ("user.email", "synthetic@example.invalid")):
        subprocess.run(
            ["git", "-C", str(repo), "config", key, value],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    subprocess.run(
        ["git", "-C", str(repo), "add", *files],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "synthetic source snapshot"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return repo


def _source_fragment_for_test(function_id, object_id, source_bytes):
    return {
        "function_id": function_id,
        "source_file_object_id": object_id,
        "byte_start": 0,
        "byte_end": len(source_bytes),
        "fragment_raw_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "normalized_ast_sha256": "d" * 64,
        "ordered_call_edges": [],
    }


def test_source_callgraph_fragment_raw_hash_is_rechecked_against_pinned_git_head(tmp_path):
    source_bytes = b"int main() { return 0; }\n"
    repo = _synthetic_source_repo(tmp_path, {"src/source/main.cpp": source_bytes})
    source_path = repo / "src" / "source" / "main.cpp"
    fragment = _source_fragment_for_test("main.dispatch", "source.main_cpp", source_bytes)
    graph = _source_callgraph(fragments=[fragment])
    result = inspect_untrusted_v5_source_callgraph_against_git_head(graph, repo)
    assert result["status"] == "untrusted_v5_source_fragment_bytes_match_git_head_snapshot"
    assert result["source_fragment_raw_hashes_match_git_head_snapshot"] is True
    assert result["source_function_definition_ranges_verified"] is False
    assert result["source_fragments_reparsed_from_source"] is False
    assert result["source_tree_sha256_matched_build_attestation"] is False
    assert result["source_callgraph_verified"] is False
    assert result["gate_state"] == "open"
    assert result["git_head_commit_at_start_and_end_matched"] is True

    wrong_fragment = {**fragment, "fragment_raw_sha256": "a" * 64}
    mismatch = inspect_untrusted_v5_source_callgraph_against_git_head(
        _source_callgraph(fragments=[wrong_fragment]), repo,
    )
    assert mismatch["status"] == "untrusted_v5_source_fragment_bytes_mismatch"
    assert mismatch["source_fragment_mismatch_function_ids"] == ["main.dispatch"]
    assert mismatch["gate_state"] == "open"

    source_path.write_bytes(b"staged-only difference\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "src/source/main.cpp"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    source_path.write_bytes(source_bytes)
    staged_index_result = inspect_untrusted_v5_source_callgraph_against_git_head(graph, repo)
    assert staged_index_result["source_fragment_raw_hashes_match_git_head_snapshot"] is True

    source_path.write_bytes(b"int main() { return 1; }\n")
    with pytest.raises(JournalV5Error, match="pinned Git blob"):
        inspect_untrusted_v5_source_callgraph_against_git_head(graph, repo)


def test_git_environment_redirection_and_fsmonitor_hook_are_not_used(tmp_path, monkeypatch):
    original_bytes = b"int main() { return 0; }\n"
    repo = _synthetic_source_repo(tmp_path / "original", {"src/source/main.cpp": original_bytes})
    expected_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.decode().strip()
    decoy = _synthetic_source_repo(
        tmp_path / "decoy", {"src/source/main.cpp": b"int main() { return 999; }\n"},
    )
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "fsmonitor-hook.sh"
    hook.write_text(f"#!/bin/sh\nprintf x > {shlex.quote(str(marker))}\n")
    hook.chmod(0o755)
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.fsmonitor", f"sh {shlex.quote(str(hook))}"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    observed_git_args = []
    original_git_read = journal_v5._git_read

    def record_git_args(root, args, label, *, env=None):
        observed_git_args.append(tuple(args))
        return original_git_read(root, args, label, env=env)

    monkeypatch.setattr(journal_v5, "_git_read", record_git_args)
    fragment = _source_fragment_for_test("main.dispatch", "source.main_cpp", original_bytes)
    result = inspect_untrusted_v5_source_callgraph_against_git_head(
        _source_callgraph(fragments=[fragment]), repo,
    )
    assert result["git_head_commit_observed"] == expected_head
    assert result["source_fragment_raw_hashes_match_git_head_snapshot"] is True
    assert not any(args and args[0] == "status" for args in observed_git_args)
    assert not marker.exists()


def test_git_head_is_pinned_and_movement_during_inspection_fails_closed(tmp_path, monkeypatch):
    source_path = "src/source/main.cpp"
    bytes_a = b"int main() { return 1; }\n"
    bytes_b = b"int main() { return 2; }\n"
    repo = _synthetic_source_repo(tmp_path, {source_path: bytes_a})
    commit_a = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.decode().strip()
    (repo / source_path).write_bytes(bytes_b)
    subprocess.run(
        ["git", "-C", str(repo), "add", source_path], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--quiet", "-m", "second snapshot"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    original_git_read = journal_v5._git_read
    head_capture_count = 0

    def move_head_after_capture(root, args, label, *, env=None):
        nonlocal head_capture_count
        result = original_git_read(root, args, label, env=env)
        if args == ["rev-parse", "--verify", "HEAD^{commit}"]:
            head_capture_count += 1
            if head_capture_count == 1:
                subprocess.run(
                    ["git", "-C", str(repo), "checkout", "--quiet", "--detach", commit_a],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
        return result

    monkeypatch.setattr(journal_v5, "_git_read", move_head_after_capture)
    fragment = _source_fragment_for_test("main.dispatch", "source.main_cpp", bytes_a)
    with pytest.raises(JournalV5Error, match="pinned Git blob"):
        inspect_untrusted_v5_source_callgraph_against_git_head(
            _source_callgraph(fragments=[fragment]), repo,
        )


def test_git_and_worktree_reads_stay_bound_to_open_repository_root(tmp_path, monkeypatch):
    original_bytes = b"int main() { return 1; }\n"
    replacement_bytes = b"int main() { return 2; }\n"
    repo = _synthetic_source_repo(
        tmp_path / "original", {"src/source/main.cpp": original_bytes},
    )
    replacement = _synthetic_source_repo(
        tmp_path / "replacement", {"src/source/main.cpp": replacement_bytes},
    )
    moved_repo = repo.with_name("repo-original")
    original_git_read = journal_v5._git_read
    replaced = False

    def replace_root_after_git_probe(root, args, label, *, env=None):
        nonlocal replaced
        result = original_git_read(root, args, label, env=env)
        if args == ["rev-parse", "--show-toplevel"] and not replaced:
            repo.rename(moved_repo)
            replacement.rename(repo)
            replaced = True
        return result

    monkeypatch.setattr(journal_v5, "_git_read", replace_root_after_git_probe)
    fragment = _source_fragment_for_test(
        "main.dispatch", "source.main_cpp", replacement_bytes,
    )
    with pytest.raises(JournalV5Error, match="repository root path changed"):
        inspect_untrusted_v5_source_callgraph_against_git_head(
            _source_callgraph(fragments=[fragment]), repo,
        )


def test_source_inspection_enforces_per_file_and_aggregate_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(journal_v5, "MAX_SOURCE_FILE_BYTES", 100)
    monkeypatch.setattr(journal_v5, "MAX_SOURCE_TOTAL_BYTES", 150)
    single_bytes = b"x" * 101
    repo = _synthetic_source_repo(tmp_path / "single", {"src/source/main.cpp": single_bytes})
    fragment = _source_fragment_for_test("main.dispatch", "source.main_cpp", single_bytes)
    with pytest.raises(JournalV5Error, match="per-file inspection cap"):
        inspect_untrusted_v5_source_callgraph_against_git_head(
            _source_callgraph(fragments=[fragment]), repo,
        )

    first_bytes = b"a" * 80
    second_bytes = b"b" * 80
    repo = _synthetic_source_repo(tmp_path / "aggregate", {
        "src/source/main.cpp": first_bytes,
        "src/source/JSph.cpp": second_bytes,
    })
    fragments = [
        _source_fragment_for_test("main.dispatch", "source.main_cpp", first_bytes),
        _source_fragment_for_test("jsph.load_case_config", "source.jsph_cpp", second_bytes),
    ]
    with pytest.raises(JournalV5Error, match="aggregate inspection cap"):
        inspect_untrusted_v5_source_callgraph_against_git_head(
            _source_callgraph(fragments=fragments), repo,
        )


def test_source_inspection_rejects_symlinked_source_directory(tmp_path):
    source_bytes = b"int main() { return 0; }\n"
    repo = _synthetic_source_repo(tmp_path, {"src/source/main.cpp": source_bytes})
    source_dir = repo / "src" / "source"
    moved_source_dir = repo / "src" / "source-real"
    source_dir.rename(moved_source_dir)
    source_dir.symlink_to(moved_source_dir, target_is_directory=True)
    fragment = _source_fragment_for_test("main.dispatch", "source.main_cpp", source_bytes)
    with pytest.raises(JournalV5Error, match="cannot safely read allowlisted source path"):
        inspect_untrusted_v5_source_callgraph_against_git_head(
            _source_callgraph(fragments=[fragment]), repo,
        )


def test_main_callgraph_schedule_matches_observed_guard_but_never_authorizes():
    raw_graph = _source_callgraph()
    result = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(_main_events(include_terminal_guard=True)), raw_graph,
        source_callgraph_binding=_source_callgraph_binding(raw_graph),
    )
    assert result["callgraph_driver_id_set_matches_observed"] is True
    assert result["expected_poll_count_for_observed_true_guards"] == 1
    assert result["poll_schedule_mismatch_guard_count"] == 0
    assert result["expected_poll_schedule_matches_observed"] is True
    assert result["source_callgraph_identity_copies_match_journal"] is True
    assert result["combined_untrusted_consistency"] is True
    assert result["source_callgraph_verified"] is False
    assert result["expected_query_completeness_verified"] is False
    assert result["gate_state"] == "open"
    assert result["qualification_credit"] == 0

    unbound = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(_main_events(include_terminal_guard=True)), raw_graph,
    )
    assert unbound["expected_poll_schedule_matches_observed"] is True
    assert unbound["source_callgraph_binding_raw_hash_verified"] is False
    assert unbound["combined_untrusted_consistency"] is False


def test_combined_consistency_requires_terminal_success_and_driver_loop_closure():
    graph = _source_callgraph()
    binding = _source_callgraph_binding(graph)

    missing_end = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(_main_events(include_poll_end=False)), graph,
        source_callgraph_binding=binding,
    )
    assert missing_end["expected_poll_schedule_matches_observed"] is True
    assert missing_end["all_polls_returned"] is False
    assert missing_end["combined_untrusted_consistency"] is False

    exception_events = _main_events(poll_outcome="exception", include_terminal_guard=True)
    exception_events[3]["active"] = True
    exception_events[3]["table_raw_binding"] = {"synthetic": True}
    exception = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(exception_events), graph, source_callgraph_binding=binding,
    )
    assert exception["all_polls_terminal"] is True
    assert exception["all_polls_returned"] is False
    assert exception["combined_untrusted_consistency"] is False

    no_terminal_guard = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(_main_events()), graph, source_callgraph_binding=binding,
    )
    assert no_terminal_guard["expected_poll_schedule_matches_observed"] is True
    assert no_terminal_guard["observed_driver_loops_complete"] is False
    assert no_terminal_guard["combined_untrusted_consistency"] is False

    reexec_events = _main_events(include_terminal_guard=True)
    proc = reexec_events[0]["process_generation_id"]
    reexec_events.insert(-2, _event(
        "exec", len(reexec_events) - 2, process_generation_id=proc,
        executable_binding={"synthetic": True}, argv_sha256="4" * 64,
        cwd_object_id="cwd-v2", environment_sha256="5" * 64,
    ))
    for seq, event in enumerate(reexec_events):
        event["seq"] = seq
    reexec = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(reexec_events), graph, source_callgraph_binding=binding,
    )
    assert reexec["cache_replay_diagnostic_state"] == "unresolved_output_state"
    assert reexec["combined_untrusted_consistency"] is False


def test_schedule_replay_marks_missing_entry_poll_and_wrong_callsite_incomplete():
    two_entry_instance = {
        "solver_instance_id": "main", "driver_id": "main", "input_count": 2,
        "callsite_id": "cpu.pre_interaction_forces.run_cpu", "integrator": "Verlet",
        "intersteps": ["INTERSTEP_Verlet"],
    }
    graph = _source_callgraph(instances=[two_entry_instance])
    result = inspect_untrusted_v5_journal_with_source_callgraph(_journal(_main_events()), graph)
    assert result["expected_poll_count_for_observed_true_guards"] == 2
    assert result["poll_schedule_mismatch_guard_count"] == 1
    assert result["expected_poll_schedule_matches_observed"] is False

    events = _main_events()
    events[3]["callsite_id"] = "gpu.pre_interaction_forces.run_gpu"
    result = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(events), _source_callgraph(),
    )
    assert result["poll_schedule_content_mismatch_count"] == 1
    assert result["expected_poll_schedule_matches_observed"] is False
    assert result["gate_state"] == "open"


def test_one_vres_guard_replays_two_ordered_instances_and_both_intersteps():
    instances = [
        {
            "solver_instance_id": instance_id, "driver_id": "vres", "input_count": 1,
            "callsite_id": "cpu.pre_interaction_forces.run_cpu", "integrator": "VRes",
            "intersteps": ["INTERSTEP_SymPredictor", "INTERSTEP_SymCorrector"],
        }
        for instance_id in ("vres.00", "vres.01")
    ]
    graph = _source_callgraph(
        instances=instances, driver_id="vres", loop_model="vres_driver_loop",
        solver_ids=["vres.00", "vres.01"],
    )
    result = inspect_untrusted_v5_journal_with_source_callgraph(_journal(_vres_events()), graph)
    assert result["observed_true_guard_count"] == 1
    assert result["observed_false_guard_count"] == 1
    assert result["expected_poll_count_for_observed_true_guards"] == 4
    assert result["poll_schedule_mismatch_guard_count"] == 0
    assert result["expected_poll_schedule_matches_observed"] is True
    assert result["gate_state"] == "open"

    result = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(_vres_events(swap_intersteps=True)), graph,
    )
    assert result["poll_schedule_content_mismatch_count"] == 4
    assert result["expected_poll_schedule_matches_observed"] is False


def test_missing_expected_driver_observation_is_not_called_complete():
    events = _main_events()
    events[2]["driver_id"] = "unlisted"
    events[3]["driver_id"] = "unlisted"
    result = inspect_untrusted_v5_journal_with_source_callgraph(
        _journal(events), _source_callgraph(),
    )
    assert result["callgraph_driver_id_set_matches_observed"] is False
    assert result["expected_poll_schedule_matches_observed"] is False
    assert result["combined_untrusted_consistency"] is False


def test_missing_poll_end_is_retained_as_incomplete_not_passed():
    result = inspect_untrusted_v5_journal(_journal(_main_events(include_poll_end=False)))
    assert result["poll_begin_count"] == 1
    assert result["poll_end_count"] == 0
    assert result["unterminated_poll_count"] == 1
    assert result["all_polls_terminal"] is False
    assert result["gate_state"] == "open"


def test_exception_poll_end_is_terminal_but_never_execution_success():
    events = _main_events(poll_outcome="exception")
    events[3]["active"] = True
    events[3]["table_raw_binding"] = {"synthetic": True}
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["all_polls_terminal"] is True
    assert result["poll_exception_count"] == 1
    assert result["all_polls_returned"] is False
    assert result["execution_semantics_verified"] is False


def test_exact_process_event_union_branches_are_structurally_accepted():
    parent = _process(0)
    events = [
        _event("spawn", 0, process_generation_id=parent, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=parent, executable_binding={"synthetic": True}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=parent, process_generation_id=_process(2, pid=44)),
        _event("clone_process", 3, parent_generation_id=parent, process_generation_id=_process(3, pid=45), clone_flags_hex="0000000000000000"),
        _event("thread_create", 4, process_generation_id=parent, thread_generation_id=_thread(4), clone_flags_hex="0000000000000000"),
        _event("thread_exit", 5, process_generation_id=parent, thread_generation_id=_thread(4)),
        _event("load", 6, process_generation_id=parent, object_binding={"synthetic": True}, object_kind="library"),
        _event("cgroup", 7, process_generation_id=parent, action="attach", cgroup_id="cg-v1"),
        _event("exit", 8, process_generation_id=_process(2, pid=44), exit_code=0, signal=None),
        _event("reap", 9, process_generation_id=_process(2, pid=44)),
        _event("exit", 10, process_generation_id=_process(3, pid=45), exit_code=0, signal=None),
        _event("reap", 11, process_generation_id=_process(3, pid=45)),
        _event("exit", 12, process_generation_id=parent, exit_code=0, signal=None),
        _event("reap", 13, process_generation_id=parent),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["event_count"] == 14
    assert result["process_generation_count"] == 3
    assert result["thread_generation_count"] == 1
    assert result["observed_process_lifecycle_complete"] is True
    assert result["gate_state"] == "open"


def test_unknown_event_fields_and_unmatched_poll_end_are_rejected():
    events = _main_events()
    events[0]["surprise"] = True
    with pytest.raises(JournalV5Error, match="exact schema"):
        inspect_untrusted_v5_journal(_journal(events))

    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event("poll_end", 1, poll_begin_id=0, process_generation_id=proc, outcome="returned"),
    ]
    with pytest.raises(JournalV5Error, match="must match one earlier"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("updates", [
    {"event_count": True},
    {"lost_count": True},
    {"overflow": 0},
    {"overflow": True},
    {"lost_count": 1},
])
def test_loss_overflow_and_bool_as_integer_are_rejected(updates):
    with pytest.raises(JournalV5Error):
        inspect_untrusted_v5_journal(_journal([], **updates))


def test_duplicate_keys_invalid_time_order_and_nonce_copy_are_rejected():
    with pytest.raises(JournalV5Error, match="duplicate JSON key"):
        inspect_untrusted_v5_journal(b'{"schema":"a","schema":"b"}')

    events = _main_events()
    events[2]["mono_ns_hex"] = "00000000000003e7"
    with pytest.raises(JournalV5Error, match="nondecreasing"):
        inspect_untrusted_v5_journal(_journal(
            events, coverage_start_ns_hex="00000000000003e7"
        ))

    events = _main_events()
    events[0]["attempt_nonce_hex"] = "c" * 32
    with pytest.raises(JournalV5Error, match="nonce differs"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("bad_value", [[], {}])
def test_malformed_poll_enum_values_raise_contract_error_not_typeerror(bad_value):
    events = _main_events()
    events[3]["callsite_id"] = bad_value
    with pytest.raises(JournalV5Error, match="callsite_id"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("field", ["integrator", "interstep", "cache_action"])
def test_all_poll_string_enums_reject_unhashable_json_values(field):
    events = _main_events()
    events[3][field] = []
    with pytest.raises(JournalV5Error):
        inspect_untrusted_v5_journal(_journal(events))


def test_coverage_and_exact_integer_index_rules_are_enforced():
    with pytest.raises(JournalV5Error, match="coverage start"):
        inspect_untrusted_v5_journal(_journal([], coverage_start_ns_hex="00000000000003e9"))

    events = _main_events()
    events[3]["input_entry_index"] = True
    with pytest.raises(JournalV5Error, match="builtin integer"):
        inspect_untrusted_v5_journal(_journal(events))


@pytest.mark.parametrize("bad_exit_code", [-1, 256, True])
def test_exit_code_must_be_exact_builtin_8_bit_value(bad_exit_code):
    events = _main_events()
    events[5]["exit_code"] = bad_exit_code
    with pytest.raises(JournalV5Error, match="exit code"):
        inspect_untrusted_v5_journal(_journal(events))


def test_process_query_before_root_exec_is_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event(
            "loop_guard", 1, process_generation_id=proc, driver_id="main",
            loop_iteration_id=0, time_step_ieee754_hex="0000000000000000",
            time_max_ieee754_hex="3ff0000000000000", condition_result=True,
        ),
    ]
    with pytest.raises(JournalV5Error, match="requires a running process"):
        inspect_untrusted_v5_journal(_journal(events))


def test_poll_must_match_true_guard_generation_driver_iteration_and_exact_time():
    raw = _journal_with_polls([{"timestep": "3ff0000000000000"}])
    journal = json.loads(raw)
    poll = next(event for event in journal["events"] if event["kind"] == "poll_begin")
    guard = next(event for event in journal["events"] if event["kind"] == "loop_guard")
    guard["condition_result"] = False
    with pytest.raises(JournalV5Error, match="condition_result differs"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())

    journal = json.loads(raw)
    poll = next(event for event in journal["events"] if event["kind"] == "poll_begin")
    poll["timestep_ieee754_hex"] = "0000000000000000"
    with pytest.raises(JournalV5Error, match="same-generation driver/iteration guard"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


def test_observed_driver_loop_requires_one_terminal_false_guard():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("exit", 4, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 5, process_generation_id=proc),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["observed_driver_loop_count"] == 1
    assert result["observed_driver_loop_termination_guard_count"] == 1
    assert result["observed_driver_loops_complete"] is True
    assert result["driver_loop_termination_verified"] is False

    incomplete = inspect_untrusted_v5_journal(_journal(_main_events()))
    assert incomplete["observed_driver_loops_complete"] is False


def test_driver_guard_after_false_termination_is_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("exit", 4, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 5, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="after its terminal false guard"):
        inspect_untrusted_v5_journal(_journal(events))


def test_poll_cannot_reuse_a_guard_after_terminal_false_or_newer_iteration():
    proc = _process()
    base = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
    ]
    old_guard_poll = _event(
        "poll_begin", 4, poll_begin_id=4, process_generation_id=proc,
        solver_instance_id="main", driver_id="main", guard_seq=2,
        callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
        interstep="INTERSTEP_Verlet", input_entry_index=0,
        timestep_ieee754_hex="0000000000000000", active=False,
        cache_action="miss", cache_source_seq=None, table_raw_binding=None,
    )
    terminal_then_poll = base + [
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        old_guard_poll,
        _event("poll_end", 5, poll_begin_id=4, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="outside an active observed driver loop"):
        inspect_untrusted_v5_journal(_journal(terminal_then_poll))

    next_iteration_then_stale_poll = base + [
        _event("loop_guard", 3, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        old_guard_poll,
        _event("poll_end", 5, poll_begin_id=4, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="stale driver loop guard"):
        inspect_untrusted_v5_journal(_journal(next_iteration_then_stale_poll))


def test_one_vres_driver_guard_can_serve_ordered_multiple_instances():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="vres", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
    ]
    for instance, interstep, action, source in [
        ("vres.00", "INTERSTEP_SymPredictor", "miss", None),
        ("vres.00", "INTERSTEP_SymCorrector", "hit", 3),
        ("vres.01", "INTERSTEP_SymPredictor", "miss", None),
        ("vres.01", "INTERSTEP_SymCorrector", "hit", 7),
    ]:
        seq = len(events)
        events.append(_event(
            "poll_begin", seq, poll_begin_id=seq, process_generation_id=proc,
            solver_instance_id=instance, driver_id="vres", guard_seq=2,
            callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="VRes",
            interstep=interstep, input_entry_index=0,
            timestep_ieee754_hex="0000000000000000", active=False,
            cache_action=action, cache_source_seq=source, table_raw_binding=None,
        ))
        events.append(_event(
            "poll_end", len(events), poll_begin_id=seq,
            process_generation_id=proc, outcome="returned",
        ))
    events.extend([
        _event("loop_guard", len(events), process_generation_id=proc, driver_id="vres", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("exit", len(events) + 1, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", len(events) + 2, process_generation_id=proc),
    ])
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["query_guard_link_count"] == 4
    assert result["observed_driver_loops_complete"] is True


def test_driver_guard_cannot_overtake_a_poll_end():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("loop_guard", 4, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("poll_end", 5, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="driver loop event occurs before a prior poll_end"):
        inspect_untrusted_v5_journal(_journal(events))


def test_missing_poll_end_before_next_guard_marks_loop_incomplete():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("loop_guard", 4, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="3ff0000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=False),
        _event("exit", 5, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 6, process_generation_id=proc),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["all_polls_terminal"] is False
    assert result["driver_unclosed_poll_count"] == 1
    assert result["observed_driver_loops_complete"] is False
    assert result["cache_replay_diagnostic_state"] == "unresolved_call_order"


def test_cache_single_slot_replay_uses_numeric_binary64_equality_and_current_source():
    raw = _journal_with_polls([
        {"timestep": "0000000000000000"},
        {"timestep": "8000000000000000"},  # -0.0 compares equal to +0.0 in C++.
    ])
    result = inspect_untrusted_v5_journal(raw)
    begins = [event for event in json.loads(raw)["events"] if event["kind"] == "poll_begin"]
    assert begins[0]["cache_action"] == "miss"
    assert begins[1]["cache_action"] == "hit"
    assert begins[1]["cache_source_seq"] == begins[0]["seq"]
    assert result["cache_unknown_source_count"] == 0
    assert result["cache_hit_with_unknown_source_count"] == 0


def test_negative_timestep_repeats_are_misses_under_source_guard():
    raw = _journal_with_polls([
        {"timestep": "c000000000000000"},
        {"timestep": "c000000000000000"},
    ])
    result = inspect_untrusted_v5_journal(raw)
    begins = [event for event in json.loads(raw)["events"] if event["kind"] == "poll_begin"]
    assert [event["cache_action"] for event in begins] == ["miss", "miss"]
    assert [event["cache_source_seq"] for event in begins] == [None, None]
    assert result["cache_replay_diagnostic_state"] == "journal_local_consistent_unverified"


def test_cache_slots_are_isolated_by_solver_instance_and_input_entry():
    raw = _journal_with_polls([
        {"input_entry_index": 0},
        {"input_entry_index": 1},
        {"input_entry_index": 0},
        {"solver_instance_id": "other", "input_entry_index": 0},
    ])
    inspect_untrusted_v5_journal(raw)
    begins = [event for event in json.loads(raw)["events"] if event["kind"] == "poll_begin"]
    assert [event["cache_action"] for event in begins] == ["miss", "miss", "hit", "miss"]
    assert [event["cache_source_seq"] for event in begins] == [None, None, begins[0]["seq"], None]


def test_cache_slot_does_not_cross_process_generation():
    root = _process()
    child = _process(5, pid=43)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=root, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=root, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("poll_end", 4, poll_begin_id=3, process_generation_id=root, outcome="returned"),
        _event("fork", 5, parent_generation_id=root, process_generation_id=child),
        _event("loop_guard", 6, process_generation_id=child, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 7, poll_begin_id=7, process_generation_id=child, solver_instance_id="main", driver_id="main", guard_seq=6, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=False, cache_action="miss", cache_source_seq=None, table_raw_binding=None),
        _event("poll_end", 8, poll_begin_id=7, process_generation_id=child, outcome="returned"),
        _event("exit", 9, process_generation_id=child, exit_code=0, signal=None),
        _event("reap", 10, process_generation_id=child),
        _event("exit", 11, process_generation_id=root, exit_code=0, signal=None),
        _event("reap", 12, process_generation_id=root),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["poll_begin_count"] == 2
    assert result["cache_fork_unresolved_poll_count"] == 1
    assert result["cache_transitions_observed_consistent"] is False
    assert result["cache_replay_diagnostic_state"] == "unresolved_fork_cache_state"


def test_intervening_miss_invalidates_older_same_time_cache_source():
    raw = _journal_with_polls([
        {"timestep": "0000000000000000"},
        {"timestep": "3ff0000000000000"},
        {"timestep": "0000000000000000"},
    ])
    journal = json.loads(raw)
    begins = [event for event in journal["events"] if event["kind"] == "poll_begin"]
    begins[2]["cache_action"] = "hit"
    begins[2]["cache_source_seq"] = begins[0]["seq"]
    with pytest.raises(JournalV5Error, match="cache_action differs"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


@pytest.mark.parametrize("first_outcome", ["exception", None])
def test_unknown_miss_output_poisoning_is_not_backfilled_by_same_time_hit(first_outcome):
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {"active": True, "outcome": first_outcome},
        {"timestep": "0000000000000000"},
    ]))
    assert result["cache_unknown_source_count"] == 1
    assert result["cache_hit_with_unknown_source_count"] == 1
    assert result["cache_replay_diagnostic_state"] == (
        "unresolved_call_order" if first_outcome is None else "unresolved_output_state"
    )
    assert result["cache_unclosed_prior_poll_count"] == (1 if first_outcome is None else 0)
    assert result["cache_replay_verified"] is False


def test_unterminated_cache_hit_keeps_later_same_time_hit_unverified():
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {}, {"outcome": None}, {},
    ]))
    assert result["unterminated_poll_count"] == 1
    assert result["cache_unterminated_hit_count"] == 1
    assert result["cache_hit_with_unknown_source_count"] == 0
    assert result["cache_unclosed_prior_poll_count"] == 1
    assert result["cache_replay_diagnostic_state"] == "unresolved_call_order"
    assert result["all_polls_terminal"] is False


def test_terminal_unterminated_hit_gets_incomplete_cache_diagnostic():
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {}, {"outcome": None},
    ]))
    assert result["all_polls_terminal"] is False
    assert result["gate_state"] == "open"
    assert result["cache_unterminated_hit_count"] == 1
    assert result["cache_replay_diagnostic_state"] == "incomplete_poll_state"


def test_exception_on_inactive_or_cache_hit_branch_is_rejected():
    with pytest.raises(JournalV5Error, match="inactive source branch"):
        inspect_untrusted_v5_journal(_journal_with_polls([
            {"outcome": "exception"},
        ]))
    with pytest.raises(JournalV5Error, match="cache-hit branch"):
        inspect_untrusted_v5_journal(_journal_with_polls([
            {}, {"outcome": "exception"},
        ]))


def test_cache_hit_must_reference_the_current_miss_event():
    raw = _journal_with_polls([
        {"timestep": "0000000000000000"},
        {"timestep": "0000000000000000"},
    ])
    journal = json.loads(raw)
    begins = [event for event in journal["events"] if event["kind"] == "poll_begin"]
    begins[1]["cache_source_seq"] = begins[1]["seq"] - 1
    with pytest.raises(JournalV5Error, match="current same-slot miss"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


def test_active_cache_hit_binding_matches_current_miss_with_exact_json_types():
    raw = _journal_with_polls([
        {"active": True, "table_raw_binding": {"table": {"id": 1}}},
        {"active": True, "table_raw_binding": {"table": {"id": 1}}},
    ])
    inspect_untrusted_v5_journal(raw)
    journal = json.loads(raw)
    begins = [event for event in journal["events"] if event["kind"] == "poll_begin"]
    begins[1]["table_raw_binding"] = {"table": {"id": True}}
    with pytest.raises(JournalV5Error, match="table binding differs"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())

    begins[1]["table_raw_binding"] = {"table": {"id": 1}}
    begins[0]["table_raw_binding"] = None
    with pytest.raises(JournalV5Error, match="active poll must have an object"):
        inspect_untrusted_v5_journal(json.dumps(journal).encode())


def test_poll_end_must_precede_exec_and_exec_starts_a_fresh_cache_epoch():
    proc = _process()
    guard = lambda seq: _event(
        "loop_guard", seq, process_generation_id=proc, driver_id="main",
        loop_iteration_id=seq, time_step_ieee754_hex="0000000000000000",
        time_max_ieee754_hex="3ff0000000000000", condition_result=True,
    )
    poll = lambda seq, guard_seq, action, source: _event(
        "poll_begin", seq, poll_begin_id=seq, process_generation_id=proc,
        solver_instance_id="main", driver_id="main", guard_seq=guard_seq,
        callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet",
        interstep="INTERSTEP_Verlet", input_entry_index=0,
        timestep_ieee754_hex="0000000000000000", active=False,
        cache_action=action, cache_source_seq=source, table_raw_binding=None,
    )
    exec_event = lambda seq: _event(
        "exec", seq, process_generation_id=proc, executable_binding={},
        argv_sha256="4" * 64, cwd_object_id="cwd-v2", environment_sha256="5" * 64,
    )
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), poll(3, 2, "miss", None), exec_event(4),
        _event("poll_end", 5, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="poll_end must precede a later exec"):
        inspect_untrusted_v5_journal(_journal(events))

    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), poll(3, 2, "miss", None),
        _event("poll_end", 4, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        exec_event(5), guard(6), poll(7, 6, "hit", 3),
        _event("poll_end", 8, poll_begin_id=7, process_generation_id=proc, outcome="returned"),
        _event("exit", 9, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 10, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="cache_action differs"):
        inspect_untrusted_v5_journal(_journal(events))

    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), poll(3, 2, "miss", None),
        _event("poll_end", 4, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        exec_event(5), guard(6), poll(7, 6, "miss", None),
        _event("poll_end", 8, poll_begin_id=7, process_generation_id=proc, outcome="returned"),
        _event("exit", 9, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 10, process_generation_id=proc),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["cache_exec_epoch_reset_count"] == 1
    assert result["cache_replay_diagnostic_state"] == "unresolved_output_state"

    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        guard(2), exec_event(3), poll(4, 2, "miss", None),
        _event("poll_end", 5, poll_begin_id=4, process_generation_id=proc, outcome="returned"),
        _event("exit", 6, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="same-generation driver/iteration guard"):
        inspect_untrusted_v5_journal(_journal(events))


def test_overlapping_poll_calls_for_one_cache_slot_are_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("loop_guard", 2, process_generation_id=proc, driver_id="main", loop_iteration_id=0, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 3, poll_begin_id=3, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=2, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=True, cache_action="miss", cache_source_seq=None, table_raw_binding={}),
        _event("loop_guard", 4, process_generation_id=proc, driver_id="main", loop_iteration_id=1, time_step_ieee754_hex="0000000000000000", time_max_ieee754_hex="3ff0000000000000", condition_result=True),
        _event("poll_begin", 5, poll_begin_id=5, process_generation_id=proc, solver_instance_id="main", driver_id="main", guard_seq=4, callsite_id="cpu.pre_interaction_forces.run_cpu", integrator="Verlet", interstep="INTERSTEP_Verlet", input_entry_index=0, timestep_ieee754_hex="0000000000000000", active=True, cache_action="hit", cache_source_seq=3, table_raw_binding={}),
        _event("poll_end", 6, poll_begin_id=5, process_generation_id=proc, outcome="returned"),
        _event("poll_end", 7, poll_begin_id=3, process_generation_id=proc, outcome="returned"),
        _event("exit", 8, process_generation_id=proc, exit_code=0, signal=None),
        _event("reap", 9, process_generation_id=proc),
    ]
    with pytest.raises(JournalV5Error, match="driver loop event occurs before a prior poll_end"):
        inspect_untrusted_v5_journal(_journal(events))


def test_unclosed_same_slot_poll_followed_by_another_call_is_explicitly_unresolved():
    result = inspect_untrusted_v5_journal(_journal_with_polls([
        {"outcome": None}, {},
    ]))
    assert result["poll_begin_count"] == 2
    assert result["unterminated_poll_count"] == 1
    assert result["cache_unclosed_prior_poll_count"] == 1
    assert result["cache_transitions_observed_consistent"] is False
    assert result["cache_replay_diagnostic_state"] == "unresolved_call_order"
    assert result["gate_state"] == "open"


def test_fork_from_created_root_and_multiple_root_spawn_are_rejected():
    root = _process()
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("fork", 1, parent_generation_id=root, process_generation_id=_process(1, pid=44)),
    ]
    with pytest.raises(JournalV5Error, match="parent must be a running"):
        inspect_untrusted_v5_journal(_journal(events))

    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("spawn", 1, process_generation_id=_process(1, pid=44), supervisor_identity_binding={"synthetic": True}),
    ]
    with pytest.raises(JournalV5Error, match="multiple solver root"):
        inspect_untrusted_v5_journal(_journal(events))


def test_pid_reuse_before_reap_is_rejected_but_lifecycle_truncation_is_open():
    root = _process()
    child = _process(2, pid=44)
    reused_child = _process(3, pid=44)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=root, process_generation_id=child),
        _event("clone_process", 3, parent_generation_id=root, process_generation_id=reused_child, clone_flags_hex="0000000000000000"),
    ]
    with pytest.raises(JournalV5Error, match="PID reuse"):
        inspect_untrusted_v5_journal(_journal(events))

    result = inspect_untrusted_v5_journal(_journal(_main_events()[:-1]))
    assert result["observed_process_lifecycle_complete"] is False
    assert result["gate_state"] == "open"


def test_pid_reuse_after_reap_is_accepted_as_a_new_generation():
    root = _process()
    first_child = _process(2, pid=44)
    second_child = _process(5, pid=44)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=root, process_generation_id=first_child),
        _event("exit", 3, process_generation_id=first_child, exit_code=0, signal=None),
        _event("reap", 4, process_generation_id=first_child),
        _event("clone_process", 5, parent_generation_id=root, process_generation_id=second_child, clone_flags_hex="0000000000000000"),
        _event("exit", 6, process_generation_id=second_child, exit_code=0, signal=None),
        _event("reap", 7, process_generation_id=second_child),
        _event("exit", 8, process_generation_id=root, exit_code=0, signal=None),
        _event("reap", 9, process_generation_id=root),
    ]
    result = inspect_untrusted_v5_journal(_journal(events))
    assert result["process_generation_count"] == 3
    assert result["observed_process_lifecycle_complete"] is True


def test_process_exit_before_owned_thread_exit_is_rejected():
    proc = _process()
    events = [
        _event("spawn", 0, process_generation_id=proc, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=proc, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("thread_create", 2, process_generation_id=proc, thread_generation_id=_thread(2), clone_flags_hex="0000000000000000"),
        _event("exit", 3, process_generation_id=proc, exit_code=0, signal=None),
    ]
    with pytest.raises(JournalV5Error, match="before its threads terminated"):
        inspect_untrusted_v5_journal(_journal(events))


def test_tid_reuse_across_processes_waits_for_prior_thread_exit():
    root = _process()
    child = _process(2, pid=44)
    events = [
        _event("spawn", 0, process_generation_id=root, supervisor_identity_binding={"synthetic": True}),
        _event("exec", 1, process_generation_id=root, executable_binding={}, argv_sha256="2" * 64, cwd_object_id="cwd-v1", environment_sha256="3" * 64),
        _event("fork", 2, parent_generation_id=root, process_generation_id=child),
        _event("thread_create", 3, process_generation_id=root, thread_generation_id=_thread(3, tid=43), clone_flags_hex="0000000000000000"),
        _event("thread_create", 4, process_generation_id=child, thread_generation_id=_thread(4, tid=43), clone_flags_hex="0000000000000000"),
    ]
    with pytest.raises(JournalV5Error, match="TID reuse"):
        inspect_untrusted_v5_journal(_journal(events))


def test_attempt_nonce_uses_the_frozen_exact_128_bit_hex_shape():
    bad = _journal([]).replace(NONCE.encode(), b"a" * 30)
    with pytest.raises(JournalV5Error, match="lowercase-hex"):
        inspect_untrusted_v5_journal(bad)
