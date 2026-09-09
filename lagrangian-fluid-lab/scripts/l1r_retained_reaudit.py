"""Re-audit retained Q0 cases without overwriting original reports."""

from scripts import l1r_q0_resume_audit as q0
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_cpu_slots import cpu_slot

if __name__ == "__main__":
    q0.Q0_ROOT = OUT / "q0-final"
    q0.REPORT = q0.Q0_ROOT / "SUMMARY.json"
    q0.Q0_ARTIFACT_ROOT = LAB / "campaigns/l1-resume/artifacts/q0-final"
    q0.PLAN_BASELINE = "f104e5409cec2c8dd4043f93ffc4f6c7cda96646"
    q0.ATTACHMENT = OUT / "source/L1R_Continuation_f104e540/CONTINUATION_PLAN_ZH.md"
    with cpu_slot():
        q0.run()
