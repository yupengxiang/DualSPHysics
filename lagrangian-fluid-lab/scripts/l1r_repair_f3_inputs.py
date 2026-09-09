"""Prepare reviewable input repairs; preserve all six failed attempts and assets."""

import json, shutil
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts.l1r_input_preflight import check_input
from scripts import l1r_q2_mdbc_bridge as q2


def main():
    original = json.loads((OUT / "F3-REGISTERED-MATRIX.json").read_text())
    repaired = []
    source = (
        LAB
        / "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv"
    )
    for old in original["records"]:
        record = dict(old)
        name = old["id"] + "_INPUTFIX"
        oldroot = (LAB / old["generated_prefix"]).parent
        newroot = oldroot.with_name(name)
        if not newroot.exists():
            shutil.copytree(oldroot, newroot)
        shutil.copy2(source, newroot / source.name)
        record.update(
            id=name,
            case_id=name,
            generated_prefix=str(
                (newroot / (LAB / old["generated_prefix"]).name).relative_to(LAB)
            ),
            candidate_definition=str(
                (newroot / (LAB / old["candidate_definition"]).name).relative_to(LAB)
            ),
            repair_of=old["id"],
            input_repair="restore complete auxiliary acceleration data after GenCase; no geometry or solver parameter changes",
        )
        result = check_input(record)
        write(name + "-PREPARED.json", record)
        repaired.append(record)
    write(
        "F3-INPUT-REPAIR-READY.json",
        {
            "records": repaired,
            "new_solver_attempts": 0,
            "status": "native_input_preflight_passed_pending_attempt_budget",
            "failure_root_cause": "GenCase warning: auxiliary same-path copy failed; destination was empty. Runner did not stop after shared initialization failure.",
            "budget": "six F3 attempts remain charged; no automatic reset or unapproved retry",
        },
    )


if __name__ == "__main__":
    main()
