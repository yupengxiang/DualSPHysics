# F5 fresh099: bounded excitation recovery source pack

Root369 reviewed every full801 rendered state and held F5 case credit because the sequence was geometrically reasonable but did not demonstrate a runup event. Root370 then supplied the missing control evidence: the 641-row prescribed motion was executed across all 801 states, with control x peak-to-peak `0.04869627239749903` m, moving displacement max `0.024332325905561447` m, and moving-vs-prescribed error `7.282415375104486e-09` m. The source package therefore treats “motion did not execute” as closed and leaves “wave/runup amplitude was insufficient” as a bounded, testable hypothesis.

This pack keeps the successful C082S1 solid-fluid geometry, initial placement recipe, source `mkbound=40` to native bed `Mk50` mapping, DP `0.02` m, 3-D controls, 16 s event window, and all prior precision/dynamic negatives. It declares at most two control conditions:

- `C082S1_MOTION_A120`: scale the registered compact packet x displacement by `1.2`; this is the primary event-coverage candidate and lies in the existing F5 legal amplitude set.
- `C082S1_MOTION_A080`: scale it by `0.8`; this is a predeclared low-amplitude control, used only if Root needs an amplitude-response comparison.

The only changed source field is the motion asset reference. The source task does not open or rehash the existing DAT. `workers/scale_compact_motion.py` is disabled and must be run by Root's registered CPU worker if either candidate is selected; its runtime receipt records the fresh input/output SHA, row count, and time-axis checks. Candidate XMLs and canonical owner JSONs have separate source-plan and physical-condition hashes. Future motion, GenCase, native, H5, XMF, audit, and render hashes remain null or explicit root-bind placeholders.

Every request is disabled with Root as launch owner, `kind` and allowlisted CPU task kinds present, strict/runtime/root-policy/resource inputs recorded, no arrays or ledger writes, no solver/converter launch, and zero independent case increment. The chain is motion transform -> genuine GenCase -> actual placement/Mk50 QA -> 1 s/51-state native diagnostic -> particle-level bed audit. A candidate must pass each actual gate before the next one is enabled. Full16/full801 approval and case credit are never inferred by this package.

Root314's exact-lattice precision negative, Root369's visual hold, Root370's motion diagnostic, and the previous A/B/C geometry evidence remain historical evidence. This pack does not relabel any of them and does not relax a penetration or precision threshold.
