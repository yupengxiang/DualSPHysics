# F5 fresh070: actual A061 frame-zero fixed-bed distribution audit

This is a source-only, disabled CPU audit request for the already completed A061 chain. It binds the actual Root075 genuine GenCase receipt and generated XML, Root083 native QA, typed065 conversion, and Root129 XDMF/manifest/receipt. The worker reads frame 0 read-only only when Root manually enables the request.

The purpose is to separate an initial fixed-bed support/fill problem from a later DBC or solver problem. It reports the actual total and fluid counts from the Gen075 receipt and generated XML, all fixed/moving/fluid type counts, UID/finite/overlap checks, fixed support in each of the six exact profile x segments with y levels and mid-y coverage, the mk40 mixed geometry cohort warning, and initial fluid/profile separation inside y = [-0.15, 0.15] m. It does not substitute a hardcoded expected-fluid count.

The large typed H5 SHA is accepted only from the completed conversion report and Root129 manifest/receipt declarations. The worker checks those declarations but never hashes the H5. Small JSON/XML/XDMF metadata are verified against their bound SHA values. The worker does not launch GenCase, conversion, solver, PartVTK, or rendering and does not write any source or shared state.

The prior Root131 dynamic result remains a real negative: at frame 25 (0.5000603704 s), 10,170/40,710 were below 1 DP and 9,118 below 2 DP, with maximum depth 0.5023042402 m; at frame 50 (1.0000641873 s), 13,395/40,710 (32.903%) were below 1 DP and 12,257 below 2 DP, with maximum depth 0.5562836166 m. UID loss/nonfinite rows were zero. This fresh070 initial audit cannot reverse that result or authorize full801.

## Root execution

Use `initial-fixed-bed-distribution-audit-request.json` with a fresh DATA attempt and enable it only after reviewing `binding.json`. The command writes only `{attempt_root}/initial-bed-distribution-audit/a061-initial-fixed-bed-distribution-audit.json`. Root must review the per-segment support and initial separation before deciding whether any new repair is justified; a structural or initial-support result is not dynamic acceptance.
