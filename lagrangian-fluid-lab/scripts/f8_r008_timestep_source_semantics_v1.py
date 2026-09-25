#!/usr/bin/env python3
"""Audit source-level F8 R008 timestep and completion semantics only.

This does not authenticate the source tree, a loaded binary, a solver attempt,
or any runtime output. It exists to prevent recorded RunPARTs DtMax diagnostics
from being mislabeled as actual solver-step adjudication without the required
runtime integrator and completion evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET
from typing import Any, Mapping


LAB = Path(__file__).resolve().parents[1]
REPO = LAB.parent
SCOPE_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
PACK_PATH = SCOPE_ROOT / "definition-control-pack-v1/receipt.json"
OUTPUT = LAB / SCOPE_ROOT / "native-fluid-table-schema-v2/timestep-source-semantics-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_timestep_source_semantics.v1"
RECORD_ID = "f8-r008-timestep-source-semantics-v1"
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)

SOURCE_PATHS = {
    "config": "src/source/JSph.cpp",
    "cli": "src/source/JSphCfgRun.cpp",
    "cpu_dt": "src/source/JSphCpu.cpp",
    "cpu_loop": "src/source/JSphCpuSingle.cpp",
    "cpu_dispatch": "src/source/JSphCpuSingle.h",
}
AUDIT_IMPLEMENTATION_PATH = Path("scripts/f8_r008_timestep_source_semantics_v1.py")
AUDIT_TEST_PATH = Path("tests/test_f8_r008_timestep_source_semantics_v1.py")
RUNTIME_CONTROL_KEYS = (
    "StepAlgorithm", "VerletSteps", "DtIni", "DtMin", "DtFixed", "DtFixedFile",
    "CoefDtMin", "DtAllParticles", "CFLnumber", "TimeMax", "TimeOut",
    "TimeOutExtra", "MinFluidStop", "NstepsBreak",
)
RUNTIME_EVIDENCE_SCHEMA = "core.cfd.f8.r008_runtime_completion_evidence.v1"
RUNTIME_EVIDENCE_FIELDS = frozenset({
    "backend", "frozen_time_max_s", "effective_time_max_s", "final_time_s",
    "absolute_tolerance_s", "relative_tolerance", "tolerance_preregistration_claim",
    "tolerance_receipt_sha256", "process_exit_code", "nstepsbreak_observed",
    "minimum_fluid_stop_observed", "terminate_file_observed", "terminate_applied",
    "terminate_warning_observed", "unregistered_control_override_observed",
    "gpu_enabled", "openmp_enabled", "vres_enabled",
})

# Each source fragment is checked inside one named C++ function after removing
# comments and treating string/character literals as indivisible tokens.
FUNCTION_SPECS = {
    "config": {
        "LoadConfigParameters": {
            "signature": "void JSph::LoadConfigParameters(const JXml* cxml)",
            "anchors": {
                "xml_step_algorithm_default": 'switch(eparms.GetValueInt("StepAlgorithm",true,1)){',
                "step_algorithm_1_is_verlet": "case 1: TStep=STEP_Verlet; break;",
                "step_algorithm_2_is_symplectic": "case 2: TStep=STEP_Symplectic; break;",
                "xml_verlet_steps_default": 'VerletSteps=eparms.GetValueInt("VerletSteps",true,40);',
                "xml_time_max": 'TimeMax=eparms.GetValueDouble("TimeMax");',
                "xml_time_out": 'TimePart=eparms.GetValueDouble("TimeOut");',
                "xml_dt_ini_default": 'DtIni=max(0.0,eparms.GetValueDouble("DtIni",true,0));',
                "xml_dt_min_default": 'DtMin=max(0.0,eparms.GetValueDouble("DtMin",true,0));',
                "xml_dt_fixed_default": 'double valuefixeddt=max(0.0,eparms.GetValueDouble("DtFixed",true,0));',
                "minimum_fluid_stop_default": 'MinFluidStop=eparms.GetValueFloat("MinFluidStop",true,0);',
            },
            "order": [["xml_step_algorithm_default", "step_algorithm_1_is_verlet",
                       "step_algorithm_2_is_symplectic"]],
        },
        "LoadConfigCommands": {
            "signature": "void JSph::LoadConfigCommands(const JSphCfgRun* cfg)",
            "anchors": {
                "runtime_config_can_override_integrator": "if(cfg->TStep)TStep=cfg->TStep;",
                "runtime_config_can_override_cfl": "if(cfg->CFLnumber>0)CFLnumber=cfg->CFLnumber;",
                "runtime_config_can_override_time_max": "if(cfg->TimeMax>0)TimeMax=cfg->TimeMax;",
                "nsteps_break_assignment": "NstepsBreak=cfg->NstepsBreak;",
                "nsteps_break_nonzero_warning": 'if(NstepsBreak)Log->PrintfWarning("The execution will be cancelled after %d simulation steps.",NstepsBreak);',
            },
            "order": [["nsteps_break_assignment", "nsteps_break_nonzero_warning"]],
        },
        "LoadCaseConfig": {
            "signature": "void JSph::LoadCaseConfig(const JSphCfgRun* cfg)",
            "anchors": {
                "load_xml_parameters": "LoadConfigParameters(cxml);",
                "load_command_overrides": "LoadConfigCommands(cfg);",
            },
            "order": [["load_xml_parameters", "load_command_overrides"]],
        },
        "SaveRunPartsCsv": {
            "signature": "void JSph::SaveRunPartsCsv(const StInfoPartPlus& infoplus,double tpart,double tsim)const",
            "anchors": {
                "runparts_writes_recorded_dtmax": "scsv << fun::RealStr(partnsteps? PartDtMin: 0) << fun::RealStr(partnsteps? PartDtMax: 0);",
            },
            "order": [],
        },
        "SaveRunPartsCsvFinal": {
            "signature": "void JSph::SaveRunPartsCsvFinal()const",
            "anchors": {
                "footer_append_guard": "if(scsv.GetAppendMode()){",
                "footer_contains_time_column_definition": 'scsv << "# TimeStep [s]:  Physical time of simulation." << jcsv::Endl();',
            },
            "order": [],
        },
        "SaveData": {
            "signature": "void JSph::SaveData(unsigned npsave,const JDataArrays& arrays,unsigned ndom,const tdouble6* vdom,StInfoPartPlus infoplus)",
            "anchors": {
                "save_part_data_before_dt_range_reset": "SavePartData(npsave,nout,arrays,ndom,vdom,infoplus);",
                "part_dt_range_reset": "PartDtMin=DBL_MAX; PartDtMax=-DBL_MAX;",
                "save_data_checks_termination": "CheckTermination();",
            },
            "order": [["save_part_data_before_dt_range_reset", "part_dt_range_reset",
                       "save_data_checks_termination"]],
        },
        "CheckTermination": {
            "signature": "void JSph::CheckTermination()",
            "anchors": {
                "termination_file_path": 'const string file=DirOut+"TERMINATE";',
                "termination_change_detection": "if(tmodif && tmodif!=TerminateMt){",
                "termination_time_clamped_to_current": "if(tmax<TimeStep)tmax=TimeStep;",
                "termination_warning": 'Log->PrintfWarning("TERMINATE file has updated TimeMax from %gs to %gs (current time: %fs).",TimeMax,tmax,TimeStep);',
                "termination_time_max_assignment": "if(!Mgpu)TimeMax=tmax;",
                "termination_mtime_remembered": "TerminateMt=tmodif;",
            },
            "order": [["termination_file_path", "termination_change_detection",
                       "termination_time_clamped_to_current", "termination_warning",
                       "termination_time_max_assignment", "termination_mtime_remembered"]],
        },
        "ShowResume": {
            "signature": "void JSph::ShowResume(bool stop,float tsim,float ttot,bool all,std::string infoplus)",
            "anchors": {
                "finished_label_uses_stop_argument": 'Log->Printf("\\n[Simulation %s  %s]",(stop? "INTERRUPTED": "finished"),fun::GetDateTime().c_str());',
            },
            "order": [],
        },
    },
    "cli": {
        "LoadOpts": {
            "signature": "void JSphCfgRun::LoadOpts(const std::string* optlis,int optn,int lv,const std::string& file)",
            "anchors": {
                "cpu_backend_cli_option": 'if(txword=="CPU"){',
                "cpu_backend_enable": "Cpu=true;",
                "gpu_backend_cli_option": 'else if(txword=="GPU"){',
                "gpu_backend_enable": "Gpu=true;",
                "symplectic_cli_override": 'else if(txword=="SYMPLECTIC")TStep=STEP_Symplectic;',
                "verlet_cli_override": 'else if(txword=="VERLET"){',
                "cfl_cli_option": 'else if(txword=="CFL"){',
                "cfl_cli_value_assignment": "CFLnumber=atof(txoptfull.c_str());",
                "tmax_cli_option": 'else if(txword=="TMAX"){',
                "tmax_cli_value_assignment": "TimeMax=atof(txoptfull.c_str());",
                "tout_cli_option": 'else if(txword=="TOUT"){',
                "tout_cli_value_assignment": "TimePart=atof(txoptfull.c_str());",
                "nsteps_cli_option": 'else if(txword=="NSTEPS"){',
                "nsteps_value_assignment": "NstepsBreak=atoi(txoptfull.c_str());",
            },
            "order": [["symplectic_cli_override", "verlet_cli_override"],
                      ["cfl_cli_option", "cfl_cli_value_assignment"],
                      ["tmax_cli_option", "tmax_cli_value_assignment"],
                      ["tout_cli_option", "tout_cli_value_assignment"],
                      ["nsteps_cli_option", "nsteps_value_assignment"]],
        },
    },
    "cpu_dt": {
        "DtVariable": {
            "signature": "double JSphCpu::DtVariable(bool final)",
            "anchors": {
                "recorded_part_max_updates_from_dt": "if(PartDtMax<dt)PartDtMax=dt;",
                "recorded_part_max_inside_final_guard": "if(final){",
                "dtvariable_returns_recorded_dt": "return(dt);",
            },
            "order": [["recorded_part_max_inside_final_guard", "recorded_part_max_updates_from_dt",
                       "dtvariable_returns_recorded_dt"]],
        },
    },
    "cpu_loop": {
        "ComputeStep_Ver": {
            "signature": "double JSphCpuSingle::ComputeStep_Ver()",
            "anchors": {
                "verlet_dt_is_final_dtvariable": "const double dt=DtVariable(true);",
                "verlet_advances_with_dt": "ComputeVerlet(dt);",
                "verlet_returns_applied_dt": "return(dt);",
            },
            "order": [["verlet_dt_is_final_dtvariable", "verlet_advances_with_dt",
                       "verlet_returns_applied_dt"]],
        },
        "ComputeStep_Sym": {
            "signature": "double JSphCpuSingle::ComputeStep_Sym()",
            "anchors": {
                "symplectic_uses_previous_dt": "const double dt=SymplecticDtPre;",
                "symplectic_predictor_candidate_not_final": "const double dt_p=DtVariable(false);",
                "symplectic_corrector_candidate_final": "const double dt_c=DtVariable(true);",
                "symplectic_next_step_uses_minimum_candidate": "SymplecticDtPre=min(dt_p,dt_c);",
                "symplectic_returns_previous_applied_dt": "return(dt);",
            },
            "order": [["symplectic_uses_previous_dt", "symplectic_predictor_candidate_not_final",
                       "symplectic_corrector_candidate_final",
                       "symplectic_next_step_uses_minimum_candidate",
                       "symplectic_returns_previous_applied_dt"]],
        },
        "Run": {
            "signature": "void JSphCpuSingle::Run(std::string appname,const JSphCfgRun* cfg,JLog2* log)",
            "anchors": {
                "run_loop_stops_at_time_max": "while(TimeStep<TimeMax){",
                "run_loop_advances_by_compute_step": "const double stepdt=ComputeStep();",
                "run_loop_adds_effective_step": "TimeStep+=stepdt;",
                "part_save_guard": "if(TimeStep>=TimePartNext || minfluidstopped){",
                "minimum_fluid_stop_predicate": "minfluidstopped=(npfnormal<NpfMinimum || !Np);",
                "minimum_fluid_stop_rewrites_time_max": "TimeMax=TimeStep;",
                "nsteps_break_can_exit_early": "if(NstepsBreak && Nstep>=NstepsBreak)break;",
                "finishrun_receives_only_minfluid_stop": "FinishRun(minfluidstopped);",
            },
            "order": [["run_loop_stops_at_time_max", "run_loop_advances_by_compute_step",
                       "run_loop_adds_effective_step", "minimum_fluid_stop_predicate", "part_save_guard",
                       "minimum_fluid_stop_rewrites_time_max", "nsteps_break_can_exit_early",
                       "finishrun_receives_only_minfluid_stop"]],
        },
        "FinishRun": {
            "signature": "void JSphCpuSingle::FinishRun(bool stop)",
            "anchors": {
                "finishrun_passes_stop_flag_to_summary": 'JSph::ShowResume(stop,tsim,ttot,true,"");',
                "finishrun_writes_footer": "if(SvData&SDAT_Info)SaveRunPartsCsvFinal();",
            },
            "order": [["finishrun_passes_stop_flag_to_summary", "finishrun_writes_footer"]],
        },
        "SaveData": {
            "signature": "void JSphCpuSingle::SaveData()",
            "anchors": {"derived_save_calls_base": "JSph::SaveData(npsave,arrays,1,&vdom,infoplus);"},
            "order": [],
        },
    },
    "cpu_dispatch": {
        "ComputeStep": {
            "signature": "double ComputeStep()",
            "anchors": {"cpu_dispatches_verlet_or_symplectic": "return(TStep==STEP_Verlet? ComputeStep_Ver(): ComputeStep_Sym());"},
            "order": [],
        },
    },
}


class TimestepSemanticsError(ValueError):
    """The current source/scope does not match this versioned static audit."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TimestepSemanticsError(message)


def _read_regular(root: Path, relative: str | Path) -> tuple[bytes, dict[str, Any]]:
    rel = Path(relative)
    _require(not rel.is_absolute() and bool(rel.parts) and ".." not in rel.parts,
             "audit evidence path must be a bounded relative path")
    _require(O_NOFOLLOW != 0 and O_DIRECTORY != 0,
             "platform lacks required O_NOFOLLOW/O_DIRECTORY protections")
    root_fd = os.open(root, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    parent_fd = root_fd
    try:
        for part in rel.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                              dir_fd=parent_fd)
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(rel.parts[-1], os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                     f"audit evidence must be a single-link regular file: {rel}")
            _require(before.st_size <= MAX_EVIDENCE_BYTES,
                     f"audit evidence exceeds the fixed byte limit: {rel}")
            chunks: list[bytes] = []
            size = 0
            while True:
                block = os.read(fd, min(1024 * 1024, MAX_EVIDENCE_BYTES + 1 - size))
                if not block:
                    break
                size += len(block)
                _require(size <= MAX_EVIDENCE_BYTES,
                         f"audit evidence exceeds the fixed byte limit: {rel}")
                chunks.append(block)
            after = os.fstat(fd)
            named = os.stat(rel.parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            identity = lambda value: (
                value.st_dev, value.st_ino, value.st_mode, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns, value.st_nlink,
            )
            _require(identity(before) == identity(after) == identity(named)
                     and size == before.st_size,
                     f"audit evidence changed while being read: {rel}")
            payload = b"".join(chunks)
            os.lseek(fd, 0, os.SEEK_SET)
            verify_hash = hashlib.sha256()
            verify_size = 0
            while True:
                block = os.read(fd, min(1024 * 1024, MAX_EVIDENCE_BYTES + 1 - verify_size))
                if not block:
                    break
                verify_size += len(block)
                _require(verify_size <= MAX_EVIDENCE_BYTES,
                         f"audit evidence exceeds the fixed byte limit: {rel}")
                verify_hash.update(block)
            after_verify = os.fstat(fd)
            named_verify = os.stat(rel.parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            _require(identity(before) == identity(after_verify) == identity(named_verify)
                     and verify_size == size
                     and verify_hash.digest() == hashlib.sha256(payload).digest(),
                     f"audit evidence changed while being read: {rel}")
        finally:
            os.close(fd)
    finally:
        if parent_fd != root_fd:
            os.close(parent_fd)
        os.close(root_fd)
    return payload, {"path": rel.as_posix(), "bytes": len(payload),
                     "sha256": hashlib.sha256(payload).hexdigest()}


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_NUMBER = re.compile(r"(?:0[xX][0-9A-Fa-f]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)[uUlLfF]*")
_RAW_PREFIX = re.compile(r"(?:u8|u|U|L)?R\"")
_QUOTED_PREFIX = re.compile(r"(?:u8|u|U|L)?(?=[\"'])")
_MULTI_PUNCTUATION = tuple(sorted(("->*", "...", "::", "->", "++", "--", "&&", "||", "==",
                                   "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "<<", ">>",
                                   "##", "<=>", "&=", "|=", "^=", ".*"), key=len, reverse=True))


class _CppToken(tuple):
    __slots__ = ()

    def __new__(cls, value: str, line: int, offset: int):
        return tuple.__new__(cls, (value, line, offset))

    @property
    def value(self) -> str:
        return self[0]

    @property
    def line(self) -> int:
        return self[1]

    @property
    def offset(self) -> int:
        return self[2]


def _cpp_tokens(source: str) -> list[_CppToken]:
    """Small fail-closed lexer for C++ comments, literals, and brace structure."""
    _require(re.search(r"\\(?:\r\n|\n)", source) is None,
             "C++ line continuations are unsupported in audited source")
    tokens: list[_CppToken] = []
    i = 0
    line = 1
    length = len(source)
    while i < length:
        char = source[i]
        if char.isspace():
            if char == "\n":
                line += 1
            i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i + 2)
            if end < 0:
                i = length
            else:
                line += 1
                i = end + 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            _require(end >= 0, "C++ source contains an unterminated block comment")
            line += source.count("\n", i, end + 2)
            i = end + 2
            continue

        raw_prefix = _RAW_PREFIX.match(source, i)
        if raw_prefix:
            token_line = line
            open_paren = source.find("(", raw_prefix.end())
            _require(open_paren >= 0 and open_paren - raw_prefix.end() <= 16,
                     "C++ source contains an invalid raw string delimiter")
            delimiter = source[raw_prefix.end():open_paren]
            terminator = ")" + delimiter + '"'
            end = source.find(terminator, open_paren + 1)
            _require(end >= 0, "C++ source contains an unterminated raw string")
            stop = end + len(terminator)
            tokens.append(_CppToken("<literal>" + source[i:stop], token_line, i))
            line += source.count("\n", i, stop)
            i = stop
            continue

        quoted_prefix = _QUOTED_PREFIX.match(source, i)
        quote_at = quoted_prefix.end() if quoted_prefix else i
        if quote_at < length and source[quote_at] in "\"'":
            token_line = line
            quote = source[quote_at]
            j = quote_at + 1
            while j < length:
                if source[j] == "\\":
                    if j + 1 < length and source[j + 1] == "\n":
                        line += 1
                    j += 2
                    continue
                if source[j] == quote:
                    j += 1
                    break
                if source[j] == "\n":
                    line += 1
                j += 1
            _require(j <= length and source[j - 1] == quote,
                     "C++ source contains an unterminated string/character literal")
            tokens.append(_CppToken("<literal>" + source[i:j], token_line, i))
            i = j
            continue

        identifier = _IDENTIFIER.match(source, i)
        if identifier:
            tokens.append(_CppToken(identifier.group(), line, i))
            i = identifier.end()
            continue
        number = _NUMBER.match(source, i)
        if number:
            tokens.append(_CppToken(number.group(), line, i))
            i = number.end()
            continue
        punctuation = next((item for item in _MULTI_PUNCTUATION if source.startswith(item, i)), None)
        if punctuation:
            tokens.append(_CppToken(punctuation, line, i))
            i += len(punctuation)
            continue
        tokens.append(_CppToken(char, line, i))
        i += 1
    return tokens


def _values(tokens: list[_CppToken]) -> list[str]:
    return [token.value for token in tokens]


def _find_sequences(haystack: list[str], needle: list[str]) -> list[int]:
    return [start for start in range(len(haystack) - len(needle) + 1)
            if haystack[start:start + len(needle)] == needle]


def _function_body(source: str, signature: str, label: str) -> list[_CppToken]:
    tokens = _cpp_tokens(source)
    values = _values(tokens)
    signature_values = _values(_cpp_tokens(signature))
    starts = _find_sequences(values, signature_values)
    _require(len(starts) == 1, f"C++ function signature is missing or ambiguous: {label}")
    after = starts[0] + len(signature_values)
    _require(after < len(tokens) and values[after] == "{",
             f"C++ function signature does not lead directly to a body: {label}")
    depth = 0
    for stop in range(after, len(tokens)):
        if values[stop] == "{":
            depth += 1
        elif values[stop] == "}":
            depth -= 1
            if depth == 0:
                return tokens[after + 1:stop]
            _require(depth > 0, f"C++ function body has unbalanced braces: {label}")
    raise TimestepSemanticsError(f"C++ function body is unterminated: {label}")


def _audit_function(source: str, function_name: str, spec: Mapping[str, Any], source_key: str,
                    conditional_ranges: list[tuple[int, int, bool]]):
    label = f"{source_key}.{function_name}"
    body = _function_body(source, spec["signature"], label)
    body_values = _values(body)
    refs: dict[str, Any] = {}
    positions: dict[str, int] = {}
    for name, fragment in spec["anchors"].items():
        fragment_values = _values(_cpp_tokens(fragment))
        matches = _find_sequences(body_values, fragment_values)
        _require(len(matches) == 1, f"function-scoped source fragment is missing or ambiguous: {label}.{name}")
        position = matches[0]
        positions[name] = position
        refs[name] = {"line": body[position].line, "text": fragment}
        _require(not any(start < body[position].line < end and not include_guard
                         for start, end, include_guard in conditional_ranges),
                 f"source anchor is inside conditional compilation: {label}.{name}")
    for order in spec["order"]:
        _require(all(positions[left] < positions[right] for left, right in zip(order, order[1:])),
                 f"function-scoped source control/data-flow order changed: {label}.{order}")

    direct_statements = {
        "LoadConfigParameters": (
            "xml_step_algorithm_default", "xml_verlet_steps_default", "xml_time_max",
            "xml_time_out", "xml_dt_ini_default", "xml_dt_min_default",
            "xml_dt_fixed_default", "minimum_fluid_stop_default",
        ),
        "LoadConfigCommands": (
            "runtime_config_can_override_integrator", "runtime_config_can_override_cfl",
            "runtime_config_can_override_time_max", "nsteps_break_assignment",
            "nsteps_break_nonzero_warning",
        ),
        "LoadCaseConfig": ("load_xml_parameters", "load_command_overrides"),
        "DtVariable": ("recorded_part_max_inside_final_guard", "dtvariable_returns_recorded_dt"),
        "CheckTermination": (
            "termination_file_path", "termination_change_detection",
            "termination_mtime_remembered",
        ),
        "SaveData": tuple(name for name in positions if name in (
            "save_part_data_before_dt_range_reset", "part_dt_range_reset", "save_data_checks_termination",
            "derived_save_calls_base")),
        "ComputeStep_Ver": ("verlet_dt_is_final_dtvariable", "verlet_advances_with_dt",
                            "verlet_returns_applied_dt"),
        "ComputeStep_Sym": ("symplectic_uses_previous_dt", "symplectic_predictor_candidate_not_final",
                            "symplectic_corrector_candidate_final",
                            "symplectic_next_step_uses_minimum_candidate",
                            "symplectic_returns_previous_applied_dt"),
    }.get(function_name, ())
    for name in direct_statements:
        expected_depth = 1 if name in (
            "recorded_part_max_updates_from_dt", "termination_time_clamped_to_current",
            "termination_warning", "termination_time_max_assignment",
        ) else 0
        if name == "recorded_part_max_updates_from_dt":
            continue
        _require(_is_statement_at_depth(body_values, positions[name], expected_depth),
                 f"critical operation is conditional, nested, or not a standalone statement: {label}.{name}")
    if "recorded_part_max_updates_from_dt" in positions:
        _require(_is_statement_at_depth(body_values, positions["recorded_part_max_updates_from_dt"], 1),
                 f"PartDtMax update is not a direct statement inside DtVariable(final): {label}")
    if "termination_time_max_assignment" in positions:
        _require(_is_statement_at_depth(body_values, positions["termination_time_max_assignment"], 1),
                 f"TERMINATE TimeMax update is not a direct statement in its file-change branch: {label}")
    if function_name in ("ComputeStep_Ver", "ComputeStep_Sym"):
        variables = ("dt",) if function_name == "ComputeStep_Ver" else ("dt", "dt_p", "dt_c")
        for variable in variables:
            _require_const_single_declaration(body_values, variable, label)
        return_count = body_values.count("return")
        _require(return_count == 1,
                 f"integrator function gained an early/alternate return path: {label}")
    if function_name == "Run":
        _require_const_single_declaration(body_values, "stepdt", label)
        _require_no_local_shadow(body_values, "TimeStep", label)

    # Explicitly check selected lexical scopes; mere global ordering is not enough.
    if "recorded_part_max_inside_final_guard" in positions:
        opening = positions["recorded_part_max_inside_final_guard"] + len(
            _values(_cpp_tokens(spec["anchors"]["recorded_part_max_inside_final_guard"]))
        ) - 1
        closing = _matching_brace(body_values, opening, label)
        _require(opening < positions["recorded_part_max_updates_from_dt"] < closing,
                 f"PartDtMax update is no longer guarded by DtVariable(final): {label}")
    if "termination_change_detection" in positions:
        change_open = positions["termination_change_detection"] + len(
            _values(_cpp_tokens(spec["anchors"]["termination_change_detection"]))
        ) - 1
        change_end = _matching_brace(body_values, change_open, label)
        for name in ("termination_time_clamped_to_current", "termination_warning",
                     "termination_time_max_assignment"):
            _require(change_open < positions[name] < change_end,
                     f"TERMINATE action escaped its file-mtime change branch: {label}.{name}")
    if "xml_step_algorithm_default" in positions:
        switch_open = positions["xml_step_algorithm_default"] + len(
            _values(_cpp_tokens(spec["anchors"]["xml_step_algorithm_default"]))
        ) - 1
        switch_end = _matching_brace(body_values, switch_open, label)
        for name in ("step_algorithm_1_is_verlet", "step_algorithm_2_is_symplectic"):
            _require(switch_open < positions[name] < switch_end
                     and _is_statement_at_depth(body_values, positions[name], 1),
                     f"StepAlgorithm case mapping escaped its XML switch: {label}.{name}")
    if "nsteps_cli_option" in positions:
        opening = positions["nsteps_cli_option"] + len(
            _values(_cpp_tokens(spec["anchors"]["nsteps_cli_option"]))
        ) - 1
        closing = _matching_brace(body_values, opening, label)
        _require(opening < positions["nsteps_value_assignment"] < closing,
                 f"NstepsBreak assignment is outside its CLI option branch: {label}")
    for option, assignment in (("cfl_cli_option", "cfl_cli_value_assignment"),
                               ("tmax_cli_option", "tmax_cli_value_assignment"),
                               ("tout_cli_option", "tout_cli_value_assignment")):
        if option in positions:
            opening = positions[option] + len(_values(_cpp_tokens(spec["anchors"][option]))) - 1
            closing = _matching_brace(body_values, opening, label)
            _require(opening < positions[assignment] < closing,
                     f"{assignment} is outside its CLI option branch: {label}")
    for option, assignment, branch_name in (
        ("cpu_backend_cli_option", "cpu_backend_enable", "CPU"),
        ("gpu_backend_cli_option", "gpu_backend_enable", "GPU"),
    ):
        if option in positions:
            opening = positions[option] + len(_values(_cpp_tokens(spec["anchors"][option]))) - 1
            closing = _matching_brace(body_values, opening, label)
            _require(opening < positions[assignment] < closing,
                     f"{branch_name} backend assignment escaped its CLI branch: {label}")
    if "minimum_fluid_stop_predicate" in positions:
        run_loop_start = positions["run_loop_stops_at_time_max"]
        run_loop_open = run_loop_start + len(_values(_cpp_tokens(spec["anchors"]["run_loop_stops_at_time_max"]))) - 1
        run_loop_end = _matching_brace(body_values, run_loop_open, label)
        for name in ("run_loop_advances_by_compute_step", "run_loop_adds_effective_step",
                     "part_save_guard", "minimum_fluid_stop_predicate", "minimum_fluid_stop_rewrites_time_max",
                     "nsteps_break_can_exit_early"):
            _require(run_loop_open < positions[name] < run_loop_end,
                     f"{name} moved out of the CPU time loop: {label}")
        for name in ("run_loop_advances_by_compute_step", "run_loop_adds_effective_step",
                     "part_save_guard", "minimum_fluid_stop_predicate",
                     "nsteps_break_can_exit_early"):
            _require(_is_statement_at_depth(body_values, positions[name], 1),
                     f"CPU loop operation became conditional, nested, or shadowed: {label}.{name}")
        _require(_is_statement_at_depth(body_values,
                                        positions["minimum_fluid_stop_rewrites_time_max"], 3),
                 f"minimum-fluid TimeMax rewrite escaped its direct stop branch: {label}")
        _require(run_loop_end < positions["finishrun_receives_only_minfluid_stop"],
                 f"FinishRun is no longer called after the CPU time loop: {label}")
        _require(_is_statement_at_depth(body_values, positions["finishrun_receives_only_minfluid_stop"], 0),
                 f"FinishRun became conditional after the CPU time loop: {label}")
        minfluid_if = _find_sequences(body_values, _values(_cpp_tokens("if(minfluidstopped){")))
        _require(len(minfluid_if) == 1, f"minimum-fluid stop branch is missing or ambiguous: {label}")
        minfluid_open = minfluid_if[0] + len(_values(_cpp_tokens("if(minfluidstopped){"))) - 1
        minfluid_end = _matching_brace(body_values, minfluid_open, label)
        _require(minfluid_if[0] < positions["minimum_fluid_stop_rewrites_time_max"] < minfluid_end,
                 f"minimum-fluid TimeMax rewrite escaped its stop branch: {label}")
        save_if = positions["part_save_guard"] + len(_values(_cpp_tokens(spec["anchors"]["part_save_guard"]))) - 1
        save_end = _matching_brace(body_values, save_if, label)
        save_call = _find_sequences(body_values[save_if + 1:save_end], _values(_cpp_tokens("SaveData();")))
        _require(len(save_call) == 1,
                 f"CPU main-loop save branch no longer calls the audited derived SaveData: {label}")
        save_body = body_values[save_if + 1:save_end]
        _require(_is_direct_statement(save_body, save_call[0]),
                 f"CPU main-loop SaveData call became conditional or nested: {label}")
    if "footer_append_guard" in positions:
        _require(_is_direct_statement(body_values, positions["footer_append_guard"]),
                 f"RunPARTs append guard is conditional or nested: {label}")
        opening = positions["footer_append_guard"] + len(
            _values(_cpp_tokens(spec["anchors"]["footer_append_guard"]))
        ) - 1
        closing = _matching_brace(body_values, opening, label)
        _require(opening < positions["footer_contains_time_column_definition"] < closing,
                 f"RunPARTs footer definition escaped its append-mode guard: {label}")
    return body, refs


def _is_direct_statement(values: list[str], position: int) -> bool:
    return _is_statement_at_depth(values, position, 0)


def _is_statement_at_depth(values: list[str], position: int, expected_depth: int) -> bool:
    depth = 0
    for value in values[:position]:
        if value == "{":
            depth += 1
        elif value == "}":
            depth -= 1
    previous = values[position - 1] if position else "{"
    return depth == expected_depth and previous in (";", "{", "}", ":")


def _require_const_single_declaration(values: list[str], variable: str, label: str) -> None:
    declarations = _local_declarations(values, variable)
    doubles = _find_sequences(values, ["double", variable])
    _require(len(doubles) == 1 and declarations == [doubles[0] + 1] and doubles[0] > 0
             and values[doubles[0] - 1] == "const",
             f"critical timestep binding is shadowed or mutable ({variable}): {label}")


def _local_declarations(values: list[str], variable: str) -> list[int]:
    type_tokens = {"double", "float", "int", "long", "short", "unsigned", "auto",
                   "bool", "char", "size_t", "tfloat", "ullong"}
    declarations: set[int] = set()
    for index, token in enumerate(values):
        if token != variable:
            continue
        if index > 0 and values[index - 1] in type_tokens:
            declarations.add(index)
        elif index > 1 and values[index - 1] in ("*", "&") and values[index - 2] in type_tokens:
            declarations.add(index)
    return sorted(declarations)


def _require_no_local_shadow(values: list[str], variable: str, label: str) -> None:
    _require(not _local_declarations(values, variable),
             f"member binding is shadowed by a local declaration ({variable}): {label}")


def _cpp_conditional_ranges(source: str) -> list[tuple[int, int, bool]]:
    """Return preprocessor conditional ranges, exempting only the fixed header guard."""
    tokens = _cpp_tokens(source)
    values = _values(tokens)
    directives: list[tuple[int, str, str | None, int]] = []
    for index, token in enumerate(tokens):
        if token.value != "#":
            continue
        line_start = source.rfind("\n", 0, token.offset) + 1
        if source[line_start:token.offset].strip():
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].line != token.line:
            continue
        keyword = values[index + 1]
        operand = values[index + 2] if index + 2 < len(tokens) and tokens[index + 2].line == token.line else None
        directives.append((token.line, keyword, operand, index))

    starts = [(line, keyword, operand) for line, keyword, operand, _ in directives
              if keyword in ("if", "ifdef", "ifndef")]
    first_conditional = starts[0] if starts else None
    stack: list[tuple[int, str, str | None, int, bool]] = []
    conditional_ranges: list[tuple[int, int, bool]] = []
    for event_index, (line, keyword, operand, token_index) in enumerate(directives):
        if keyword in ("if", "ifdef", "ifndef"):
            is_outer_include_guard = (
                not stack and first_conditional == (line, keyword, operand)
                and keyword == "ifndef" and operand == "_JSphCpuSingle_"
                and event_index + 1 < len(directives)
                and directives[event_index + 1][1:3] == ("define", operand)
            )
            stack.append((line, keyword, operand, event_index, is_outer_include_guard))
        elif keyword == "endif":
            _require(bool(stack), "C++ source contains an unmatched #endif")
            start, _, _, _, include_guard = stack.pop()
            conditional_ranges.append((start, line, include_guard))
    _require(not stack, "C++ source contains an unterminated conditional-compilation region")
    return conditional_ranges


def _matching_brace(values: list[str], opening: int, label: str) -> int:
    _require(0 <= opening < len(values) and values[opening] == "{",
             f"expected opening brace not found: {label}")
    depth = 0
    for index in range(opening, len(values)):
        if values[index] == "{":
            depth += 1
        elif values[index] == "}":
            depth -= 1
            if depth == 0:
                return index
            _require(depth > 0, f"unbalanced brace nesting: {label}")
    raise TimestepSemanticsError(f"unclosed scoped block: {label}")


def _strict_json(payload: bytes) -> Any:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "scope receipt contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TimestepSemanticsError("scope receipt is not strict UTF-8 JSON") from error


def diagnose_runtime_completion_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Compare caller claims; never produces a trusted completion/admission verdict."""
    _require(type(evidence) is dict and set(evidence) == RUNTIME_EVIDENCE_FIELDS,
             "runtime completion evidence fields do not match the frozen schema")
    _require(type(evidence["backend"]) is str,
             "runtime completion backend identifier is malformed")
    time_fields = ("frozen_time_max_s", "effective_time_max_s", "final_time_s",
                   "absolute_tolerance_s", "relative_tolerance")
    numeric: dict[str, float] = {}
    for field in time_fields:
        value = evidence[field]
        _require(type(value) in (int, float),
                 f"runtime completion field is not a finite number: {field}")
        try:
            converted = float(value)
        except (OverflowError, ValueError) as error:
            raise TimestepSemanticsError(
                f"runtime completion field is not a finite number: {field}"
            ) from error
        _require(math.isfinite(converted),
                 f"runtime completion field is not a finite number: {field}")
        numeric[field] = converted
    frozen = numeric["frozen_time_max_s"]
    absolute = numeric["absolute_tolerance_s"]
    relative = numeric["relative_tolerance"]
    _require(frozen > 0 and absolute >= 0 and relative >= 0,
             "runtime completion time values or tolerances are outside their domain")
    _require(numeric["effective_time_max_s"] >= 0 and numeric["final_time_s"] >= 0,
             "runtime completion times cannot be negative")
    _require(type(evidence["tolerance_preregistration_claim"]) is bool,
             "runtime completion preregistration claim is malformed")
    tolerance_hash = evidence["tolerance_receipt_sha256"]
    _require(type(tolerance_hash) is str and re.fullmatch(r"[0-9a-f]{64}", tolerance_hash),
             "runtime completion tolerance receipt hash is malformed")
    _require(type(evidence["process_exit_code"]) is int
             and type(evidence["process_exit_code"]) is not bool,
             "runtime completion process exit code is malformed")
    bool_fields = RUNTIME_EVIDENCE_FIELDS - {
        "backend", *time_fields, "tolerance_preregistration_claim", "tolerance_receipt_sha256",
        "process_exit_code",
    }
    for field in sorted(bool_fields):
        _require(type(evidence[field]) is bool,
                 f"runtime completion flag is not boolean: {field}")

    tolerance = absolute + relative * abs(frozen)
    _require(math.isfinite(tolerance), "runtime completion tolerance overflowed")
    violations: list[str] = []
    if not evidence["tolerance_preregistration_claim"]:
        violations.append("tolerance_not_claimed_preregistered")
    if evidence["backend"] != "standard_cpu_single":
        violations.append("backend_not_standard_cpu_single")
    if abs(numeric["effective_time_max_s"] - frozen) > tolerance:
        violations.append("effective_time_max_differs_from_frozen_time_max")
    if abs(numeric["final_time_s"] - frozen) > tolerance:
        violations.append("final_time_outside_preregistered_tolerance")
    if evidence["process_exit_code"] != 0:
        violations.append("solver_process_did_not_exit_successfully")
    for field, violation in (
        ("nstepsbreak_observed", "nstepsbreak_observed"),
        ("minimum_fluid_stop_observed", "minimum_fluid_stop_observed"),
        ("terminate_file_observed", "terminate_file_observed"),
        ("terminate_applied", "terminate_time_max_was_changed_by_terminate"),
        ("terminate_warning_observed", "terminate_warning_observed"),
        ("unregistered_control_override_observed", "unregistered_runtime_override_observed"),
        ("gpu_enabled", "gpu_backend_enabled"),
        ("openmp_enabled", "openmp_backend_enabled"),
        ("vres_enabled", "vres_backend_enabled"),
    ):
        if evidence[field]:
            violations.append(violation)
    return {
        "schema": RUNTIME_EVIDENCE_SCHEMA,
        "state": "untrusted_runtime_evidence_diagnostic_only",
        "conditions_satisfied_untrusted": not violations,
        "tolerance_s": tolerance,
        "violations": violations,
        "evidence_authenticated": False,
        "solver_timestep_adjudicated": False,
        "normal_completion_verified": False,
        "trusted_acceptance_verdict_issued": False,
    }


def _audit_blobs(
    source_blobs: Mapping[str, bytes],
    pack_blob: bytes,
    definition_blobs: Mapping[str, bytes],
) -> dict[str, Any]:
    _require(set(source_blobs) == set(SOURCE_PATHS), "source bundle has an unexpected file set")
    source_refs: dict[str, Any] = {}
    source_text: dict[str, str] = {}
    for key, relative in SOURCE_PATHS.items():
        payload = source_blobs[key]
        _require(type(payload) is bytes and 0 < len(payload) <= MAX_EVIDENCE_BYTES,
                 f"source payload is invalid or oversized: {key}")
        try:
            decoded = payload.decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise TimestepSemanticsError(f"source is not strict UTF-8: {key}") from error
        source_text[key] = decoded
        conditional_ranges = _cpp_conditional_ranges(decoded)
        source_refs[key] = {"path": relative, "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "functions": {}}
        for function_name, spec in FUNCTION_SPECS[key].items():
            _, refs = _audit_function(decoded, function_name, spec, key, conditional_ranges)
            source_refs[key]["functions"][function_name] = {
                "signature": spec["signature"],
                "anchors": refs,
            }

    try:
        pack = _strict_json(pack_blob)
    except TimestepSemanticsError:
        raise
    _require(type(pack) is dict and type(pack.get("cases")) is list
             and pack.get("schema") == "core.cfd.f8.r008_definition_control_pack.v1"
             and pack.get("record_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008-definition-control-pack-v1"
             and pack.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
             "R008 definition/control pack receipt has an unexpected shape")
    counts = pack.get("case_counts")
    _require(counts == {"control_files": 47, "definition_files": 47,
                        "production": 32, "qualification": 15, "total": 47}
             and len(pack["cases"]) == 47,
             "R008 frozen pack no longer has the exact 15+32 definition denominator")
    expected_definition_paths: set[str] = set()
    case_ids: set[str] = set()
    qualification_count = 0
    production_count = 0
    verified_definitions: list[dict[str, Any]] = []
    explicit_step_algorithm: list[str] = []
    explicit_runtime_controls: dict[str, dict[str, str]] = {}
    for case in pack["cases"]:
        _require(type(case) is dict and type(case.get("definition")) is dict,
                 "R008 case row lacks a Definition reference")
        _require(type(case.get("case_id")) is str and case["case_id"] not in case_ids,
                 "R008 case IDs must be unique strings")
        case_ids.add(case["case_id"])
        ref = case["definition"]
        _require(set(ref) == {"bytes", "path", "role", "sha256"}
                 and type(ref["path"]) is str and type(ref["bytes"]) is int
                 and type(ref["sha256"]) is str,
                 "R008 Definition reference has an unexpected shape")
        path = ref["path"]
        expected_prefix = (SCOPE_ROOT / "definition-control-pack-v1").as_posix() + "/"
        _require(path.startswith(expected_prefix) and path.endswith("_Def.xml")
                 and ".." not in Path(path).parts and path not in expected_definition_paths,
                 "R008 Definition path is outside the frozen pack or duplicated")
        if "/qualification/" in path:
            qualification_count += 1
            _require(case.get("qualification_only") is True,
                     "R008 qualification Definition has an inconsistent row role")
        elif "/production/" in path:
            production_count += 1
            _require(case.get("qualification_only") is False,
                     "R008 production Definition has an inconsistent row role")
        else:
            raise TimestepSemanticsError("R008 Definition path is outside qualification/production")
        expected_definition_paths.add(path)
        payload = definition_blobs.get(path)
        _require(type(payload) is bytes and len(payload) == ref["bytes"]
                 and hashlib.sha256(payload).hexdigest() == ref["sha256"],
                 f"R008 Definition bytes do not match the pack receipt: {path}")
        _require(b"<!DOCTYPE" not in payload and b"<!ENTITY" not in payload,
                 f"R008 Definition uses a disallowed XML declaration: {path}")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as error:
            raise TimestepSemanticsError(f"R008 Definition XML is malformed: {path}") from error
        _require(root.tag == "case", f"R008 Definition root element is not case: {path}")
        parameters = root.findall(".//execution/parameters/parameter")
        runtime_values: dict[str, str] = {}
        for key in RUNTIME_CONTROL_KEYS:
            matching = [parameter.get("value") for parameter in parameters
                        if parameter.get("key") == key]
            _require(len(matching) <= 1 and all(type(value) is str for value in matching),
                     f"R008 Definition has duplicate or malformed runtime key {key}: {path}")
            if matching:
                runtime_values[key] = matching[0]
        if "StepAlgorithm" in runtime_values:
            explicit_step_algorithm.append(path)
        if runtime_values:
            explicit_runtime_controls[path] = runtime_values
        verified_definitions.append({"path": path, "bytes": len(payload),
                                     "sha256": ref["sha256"],
                                     "runtime_parameter_overrides": runtime_values})
    _require(set(definition_blobs) == expected_definition_paths,
             "Definition payload inventory differs from the frozen pack")
    _require(len(case_ids) == 47 and qualification_count == 15 and production_count == 32,
             "R008 Definition paths do not preserve the frozen 15+32 partition")

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_source_semantics_audited_runtime_configuration_unverified",
        "source_authenticated": False,
        "runtime_binary_identity_verified": False,
        "execution_attempt_identity_verified": False,
        "effective_integrator_verified": False,
        "solver_timestep_adjudicated": False,
        "native_integrity_adjudicated": False,
        "normal_completion_verified": False,
        "full_t1_decision": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
        "backend_scope": {
            "audited_backend": "standard_cpu_single_only",
            "runtime_backend_verified": False,
            "gpu_semantics_audited": False,
            "vres_semantics_audited": False,
            "other_backend_evidence_accepted": False,
        },
        "receipt_publication_scope": {
            "publication": "anonymous_inode_atomic_no_replace",
            "concurrent_no_clobber": True,
            "hostile_same_uid_mutation_defended": False,
            "group_or_other_writable_output_ancestry_rejected": True,
        },
        "runtime_completion_evidence_contract": {
            "schema": RUNTIME_EVIDENCE_SCHEMA,
            "required_fields": sorted(RUNTIME_EVIDENCE_FIELDS),
            "accepted_backend": "standard_cpu_single",
            "time_tolerance_formula": "absolute_tolerance_s + relative_tolerance * abs(frozen_time_max_s)",
            "time_acceptance_rule": "abs(effective_time_max_s-frozen_time_max_s)<=tolerance_s and abs(final_time_s-frozen_time_max_s)<=tolerance_s",
            "required_false_flags": [
                "nstepsbreak_observed", "minimum_fluid_stop_observed", "terminate_file_observed",
                "terminate_applied", "terminate_warning_observed", "unregistered_control_override_observed",
                "gpu_enabled", "openmp_enabled", "vres_enabled",
            ],
            "required_process_exit_code": 0,
            "tolerance_must_be_preregistered_and_hash_bound": True,
            "tolerance_receipt_hash_authentication_required_before_use": True,
            "diagnostic_helper": "diagnose_runtime_completion_evidence",
            "diagnostic_only_no_trusted_verdict": True,
            "evidence_authentication_performed_here": False,
        },
        "execution_authority": {"solver": False, "worker": False, "gpu": False,
                                "queue": False, "registry_mutation": 0,
                                "ledger_mutation": 0, "denominator_mutation": 0},
        "implementation": _read_regular(LAB, AUDIT_IMPLEMENTATION_PATH)[1],
        "test": _read_regular(LAB, AUDIT_TEST_PATH)[1],
        "source_evidence": source_refs,
        "frozen_definition_pack": {
            "receipt": {"path": PACK_PATH.as_posix(), "bytes": len(pack_blob),
                        "sha256": hashlib.sha256(pack_blob).hexdigest()},
            "definition_count": len(verified_definitions),
            "qualification_definition_count": qualification_count,
            "production_definition_count": production_count,
            "definition_bytes_and_hashes_verified": True,
            "explicit_step_algorithm_overrides": explicit_step_algorithm,
            "explicit_runtime_control_overrides_by_definition": explicit_runtime_controls,
            "runtime_control_keys_without_frozen_definition_values": [
                key for key in RUNTIME_CONTROL_KEYS
                if all(key not in item["runtime_parameter_overrides"]
                       for item in verified_definitions)
            ],
            "definitions": verified_definitions,
            "pack_source_authenticated": False,
        },
        "static_findings": {
            "xml_step_algorithm_absent_from_all_frozen_definitions": not explicit_step_algorithm,
            "solver_xml_default_step_algorithm": "Verlet (StepAlgorithm=1) only when no later runtime override applies",
            "cli_or_runtime_config_can_override_step_algorithm": True,
            "cli_or_runtime_config_can_override_cfl_time_max_and_output_cadence": True,
            "cli_can_select_gpu_backend": True,
            "effective_runtime_step_algorithm": "unverified",
            "cpu_verlet_dtmax_equals_applied_step_when_runtime_integrator_is_verified": True,
            "cpu_symplectic_recorded_part_dtmax_is_actual_used_dt_max": False,
            "runparts_footer_can_be_appended_by_finishrun": True,
            "runparts_footer_append_condition": "SDAT_Info enabled and the RunPARTs file is in append mode",
            "runparts_footer_proves_normal_completion": False,
            "nstepsbreak_can_exit_loop_before_time_max": True,
            "finished_log_marker_is_sufficient_to_exclude_nstepsbreak": False,
            "minimum_fluid_stop_can_rewrite_effective_time_max": True,
            "terminate_file_can_rewrite_cpu_time_max": True,
            "terminate_file_is_checked_during_save_data": True,
            "runparts_dtmax_semantics_scope": "standard_cpu_single_only",
        },
        "future_runtime_adjudication_requirements": [
            "authenticate exact R008 Definition/control inputs, solver command, executable/build and loaded source/runtime identity",
            "prove the runtime selected the audited standard CPU single backend and reject GPU, VRes, OpenMP, or any other unaudited backend",
            "freeze and verify effective StepAlgorithm=Verlet plus all relevant timestep, CFL, VerletSteps, TimeMax, output-time and stopping controls; reject unregistered argv/config overrides",
            "prove no NstepsBreak/debug-step limit or minimum-fluid stop was active, no TERMINATE file was created/observed/applied, no TERMINATE warning occurred, and the solver process exited successfully under the trusted supervisor",
            "bind terminal solver time to final_time >= frozen_TimeMax using a predeclared floating-point/output-time tolerance; reject early stop, overshoot beyond tolerance, or a changed effective TimeMax",
            "bind complete RunPARTs/Run.out evidence and the final-time check to frozen TimeMax and all 15 registered attempts",
            "verify native-state integrity and complete output inventory independently; the RunPARTs footer alone is insufficient",
            "accept only standard_cpu_single for this source audit; GPU, VRes, or any other backend requires a separate backend-specific source-semantic audit",
        ],
    }


def build_audit() -> dict[str, Any]:
    source_blobs = {key: _read_regular(REPO, path)[0] for key, path in SOURCE_PATHS.items()}
    pack_blob = _read_regular(LAB, PACK_PATH)[0]
    pack = _strict_json(pack_blob)
    _require(type(pack) is dict and type(pack.get("cases")) is list,
             "R008 definition/control pack receipt has an unexpected shape")
    definition_blobs = {}
    for case in pack["cases"]:
        ref = case.get("definition") if type(case) is dict else None
        _require(type(ref) is dict and type(ref.get("path")) is str,
                 "R008 case row lacks a Definition reference")
        path = ref["path"]
        definition_blobs[path] = _read_regular(LAB, path)[0]
    return _audit_blobs(source_blobs, pack_blob, definition_blobs)


def _open_output_directory() -> int:
    _require(O_NOFOLLOW != 0 and O_DIRECTORY != 0,
             "platform lacks required O_NOFOLLOW/O_DIRECTORY protections")
    parent = OUTPUT.parent.relative_to(LAB)
    fd = os.open(LAB, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    try:
        for index, component in enumerate(parent.parts):
            try:
                next_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                                   dir_fd=fd)
            except FileNotFoundError:
                mode = 0o700 if index == len(parent.parts) - 1 else 0o755
                try:
                    os.mkdir(component, mode, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                                  dir_fd=fd)
            info = os.fstat(next_fd)
            _require(info.st_uid == os.getuid() and not (info.st_mode & 0o022),
                     "receipt output path contains a directory writable by another identity")
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write_receipt_at(parent_fd: int, name: str, payload: bytes) -> None:
    _require(name == "receipt.json", "source-audit output basename is fixed")
    _require(O_NOFOLLOW != 0, "platform lacks required O_NOFOLLOW protection")
    tmpfile_flag = getattr(os, "O_TMPFILE", 0)
    _require(tmpfile_flag != 0,
             "platform/filesystem lacks O_TMPFILE required for race-free receipt publication")
    flags = os.O_WRONLY | tmpfile_flag | O_CLOEXEC
    fd = os.open(".", flags, 0o600, dir_fd=parent_fd)
    linked = False
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while publishing static source audit receipt")
            view = view[written:]
        os.fsync(fd)
        initial = os.fstat(fd)
        _require(stat.S_ISREG(initial.st_mode) and initial.st_nlink == 0,
                 "receipt staging inode is not an unlinked regular file")
        # Publish directly from the still-open anonymous inode.  No attacker-
        # replaceable temporary pathname exists between fsync and publication.
        os.link(f"/proc/self/fd/{fd}", name, dst_dir_fd=parent_fd,
                follow_symlinks=True)
        linked = True
        published = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require((published.st_dev, published.st_ino, published.st_mode)
                 == (initial.st_dev, initial.st_ino, initial.st_mode)
                 and stat.S_ISREG(published.st_mode) and published.st_nlink == 1,
                 "published receipt does not reference the fsynced temporary inode")
        os.fsync(parent_fd)
    finally:
        os.close(fd)
        if linked:
            os.fsync(parent_fd)


def write_audit_receipt_once() -> dict[str, Any]:
    receipt = build_audit()
    payload = (json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    parent_fd = _open_output_directory()
    try:
        _write_receipt_at(parent_fd, "receipt.json", payload)
    finally:
        os.close(parent_fd)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="publish a new no-clobber static-source receipt once")
    args = parser.parse_args()
    receipt = write_audit_receipt_once() if args.write else build_audit()
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
