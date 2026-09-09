# L1-R continuation

Continuation correction (2026-09-10): the historical Q2 description below
means an official **boundary-configuration** derivative, not the complete
official numerical strategy. Current evidence and reviewer handoff are in
`continuation/`; historical case IDs and failed results are retained.

This directory is an isolated continuation of the L1 evidence at commit
`404c565c9b43e5470f1830e1e9b81843465c2c38`. The retained
`campaigns/l1-qualification/` tree is read-only evidence for this round; no
old case, attempt, HDF5, or audit is replaced.

The user adopted the attached L1-R plan as the work direction. The historical
ChatGPT conversation itself was not readable in this local session, so this
directory records only claims supported by the attached plan, the repository,
and executed local evidence. It does not represent a cloud reviewer sign-off.

Current workstreams:

- `q0/REVISED_AUDIT_SUMMARY.json` and `Q0-AUDIT.md`: finite physical-wall
  re-audit of the retained W1 space cells and W2-A.
- `q1/Q1-OFFICIAL-RESULTS.json`: same-version official mDBC asset inventory,
  untouched GenCase products, and the official raw-control run.
- `q2/Q2-MDBC-BRIDGE-RESULTS.json`: one bounded bridge case using the complete
  official mDBC recipe; the run completed but its finite-wall audit failed.
- `q1/Q1-OFFICIAL.md`, `q2/Q2-MDBC-BRIDGE.md`, and
  `L1R-REVIEW-HANDOFF.md`: human-readable result and reviewer handoff notes.

Generated raw solver/data artifacts are intentionally ignored by the lab
policy. Their paths and hashes are recorded in the compact manifests and the
handoff document.
