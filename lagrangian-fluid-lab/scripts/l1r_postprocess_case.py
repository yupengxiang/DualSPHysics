"""Postprocess an existing completed solver, without launching or changing it."""

import argparse, json, time
from pathlib import Path
from scripts.l1r_continuation_evidence import LAB, OUT, write, runtime_domain
from scripts.l1r_native_normalize import normalize
from scripts import r5_f1_solver_gate as gate


def _process(record, solver):
    start = time.monotonic()
    name = record["id"]
    attempt = Path(solver["attempt_directory"])
    output = LAB / "campaigns/l1-resume/data/continuation" / (name + ".h5")
    if not output.exists():
        partial = output.with_suffix(".h5.partial")
        if partial.exists():
            partial.rename(output.with_suffix(".interrupted-csv.h5"))
        normalized = normalize(record, attempt, output)
        write(name + "-NORMALIZATION.json", normalized)
    record["wall_spec"]["runtime_domain"] = runtime_domain(attempt)
    result = gate.audit_hdf5(record, output, attempt)
    result["postprocess_elapsed_seconds"] = time.monotonic() - start
    write(name + "-AUDIT.json", result)
    return result


def process(record, solver):
    from scripts.l1r_cpu_slots import cpu_slot

    with cpu_slot():
        return _process(record, solver)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name")
    a = p.parse_args()
    r = json.loads((OUT / (a.name + "-PREPARED.json")).read_text())
    s = json.loads((OUT / (a.name + "-SOLVER.json")).read_text())
    process(r, s)
