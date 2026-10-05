# F5 fresh074: Root165 actual-bound B071 initial QA and bed coverage

Root163 genuine GenCase completed with actual B071 metadata: generated XML `F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071.xml`, actual total 174896, fixed 130392, moving 3794, fluid 40710 and 3-D. The XML path is bound as the generated case XML; the `_Def.xml` file remains the source definition only. No autofill success or physical bed-repair success is claimed.

This package contains two disabled Root-owned CPU requests:

1. `initial-qa-request.json` binds the completed receipt, prepared report, generated XML and BI4 (the BI4 SHA is carried from the completed GenCase report and is not read by this source agent). The wrapper validates receipt/XML metadata and delegates the unchanged QA054 helper. It checks actual total/fluid/3-D, finite rows, positive mass/density, UID/type/Mk, zero velocity and fixed/moving/fluid spatial no-overlap; mass is reported without rescaling.
2. `central-fixed-bed-coverage-request.json` binds the same actual GenCase outputs and the exact B profile. It reuses the fresh069 coverage worker semantics: XML fixed-Mk40 ranges intersected with native Type=0, six x segments, surface bands 0.5/1/2 DP, central `abs(y)<=0.01 m`, all fixed support y levels, initial fluid below-profile count/fraction, UID/nonfinite and overlap evidence. The typed HDF5/XDMF fields are intentionally pending and the request stays disabled until Root binds the actual typed conversion.

The coverage report explicitly treats Mk40 as a mixed boundary namespace and never calls it a bed-only proof. It reports initial geometry only and cannot authorize short/full native dynamics. Both requests bind `root_inventory_policy_source_sha256` and the Root142 profile. The static resource approval remains bound; live ledger is not an immutable request input.

This source-only handoff performed no GenCase, PartVTK, conversion, solver or array read.
