# F2 Gem commensurate handoff (2026-10-02)

This directory is an isolated new scope for F2. The original F2 48-case
registry, consumed XML/BI4/H5/VTK files, and their reports remain unchanged.
The scope has no qualification or production claim. The six GenCase results
below are CPU structural evidence for two new physical mothers, each viewed at
coarse, medium, and fine `dp`.

## Root cause and bounded repair

The consumed Gem P01 source used three inclusive `drawbox solid` fluid blocks,
each `0.325 x 0.22 x 0.088 m`, at `dp=0.02`. The source denominator is

```
3 * 0.325 * 0.22 * 0.088 = 0.018876 m3 = 18.876 kg
```

The actual old Fluid.vtk from both center and offset runs contains a `17 x 13
x 14` lattice, with effective occupied volume `0.34 x 0.26 x 0.28 =
0.024752 m3 = 24.752 kg`. The observed error against the declared continuum is
`31.12947658402203%`. The legacy report records the old receipt bytes, source
XML/Fluid.vtk hashes, and `not_a_denominator_typo=true`:

`audits/legacy-root-cause-20261002.json`

The bounded repair uses three disjoint source bands along `y`, each `0.08 m`,
with one continuous cell-centred fluid region
`low=(0.0525,-0.12,0.70) m`, `size=(0.32,0.24,0.32) m`. Its volume is
`0.024576 m3` and intended mass is `24.576 kg` at `rho0=1000 kg/m3`.
The exact populations are 384, 3072, and 24576 particles for `dp=0.04,
0.02,0.01 m`; every source band is disjoint and contributes 1/3 of the
population. The point-min values are numerical lattice phases selected to
contain the complete Gem tray and to make `low+dp/2` a grid node. They do not
move the continuous wall planes or change the copied motion/control.

The old handoff's first cell-centre run was retained as negative evidence: its
historical point-min clipped the tray. The v2 phase repair is in
`f2_handoff_20261002_v2.py` and its definitions/requests are under
`gridphase_v2/`.

## Frozen source and hash bindings

The copied Gem source bytes are exact copies of integration P01:

| Input | SHA-256 |
| --- | --- |
| `source_assets/F2_GEM_CENTER_P01_Def.xml` | `9e499e5e988d50aecf3ac2765f3222e784cc7aa305f0f19d38414ffa061a9840` |
| `source_assets/F2_GEM_OFFSET_P01_Def.xml` | `a408d8df645f496ddfeaaa4ff3b021673bf29958883817239c708dd2ec7d65b2` |
| both copied motion files | `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70` |
| `f2_handoff_20261002_v2.py` | `0433d794d36c7d74956bbc66b792243595aab992578bfde93e310821e02ff69e` |
| `f2_handoff_20261002_v2_audit.py` | `a007af8c9ebd2cda3c806c826b076cba6716470909e57d444e1b6448dbea5a1c` |
| `gridphase_v2/manifest.json` | `d0a455498158ff6d74251a2eeb7da7a570934cc5d6ee8aff42314b86577b8ad2` |

The physical geometry/control hash is resolution-invariant within each
background. The numerical recipe hash includes `dp`, grid phase, population
commands, solver parameters, and save window, so it is intentionally distinct
between the three numerical views. Center and offset have different physical
hashes because their receiver layouts differ. The motion content is fixed at
the copied `-105 degree` prescribed rotation over the 4 s event window.

## Actual CPU evidence

All six requests were run through the shared v2 runtime with four CPU threads,
return code 0, three-dimensional GenCase output, and no solver/GPU launch. The
runner SHA in every receipt is
`5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60`.

| Case | Attempt and receipt | Fluid / total particles | PID | Receipt SHA-256 |
| --- | --- | ---: | ---: | --- |
| `F2H10V2_CENTER_V1_COARSE` | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_CENTER_V1_COARSE/gencase-f2-f2h10v2-center-coarse-20261002-002/execution-receipt.json` | 384 / 28647 | 3788559 | `ecc35b9d472866e3fa98b742bb719c07b7461683fe2ee4adb8eceb788ce04c9d` |
| `F2H10V2_CENTER_V1_MEDIUM` | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_CENTER_V1_MEDIUM/gencase-f2-f2h10v2-center-medium-20261002-002/execution-receipt.json` | 3072 / 103512 | 3789532 | `2fe1c95c852fa41d97475e17a2c50ed5f06d209801f54800d2f090983e8bf88c` |
| `F2H10V2_CENTER_V1_FINE` | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_CENTER_V1_FINE/gencase-f2-f2h10v2-center-fine-20261002-002/execution-receipt.json` | 24576 / 416395 | 3789498 | `66be39d6d369a62c56abce49e8efe47afd9bb17df4a891fe46ffc23c5177e06a` |
| `F2H10V2_OFFSET_V1_COARSE` | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_OFFSET_V1_COARSE/gencase-f2-f2h10v2-offset-coarse-20261002-002/execution-receipt.json` | 384 / 28647 | 3789549 | `5e2cbd5af0ab1ae2a9da34db71f20bfc55a20d497129a5ac951c5fd5378f10c9` |
| `F2H10V2_OFFSET_V1_MEDIUM` | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_OFFSET_V1_MEDIUM/gencase-f2-f2h10v2-offset-medium-20261002-002/execution-receipt.json` | 3072 / 106200 | 3789511 | `3b1e55f14fad70d8ab33694a776444bf77fb047aefcacd155d0be79b7496c249` |
| `F2H10V2_OFFSET_V1_FINE` | `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_OFFSET_V1_FINE/gencase-f2-f2h10v2-offset-fine-20261002-002/execution-receipt.json` | 24576 / 416395 | 3789541 | `e057eb68bac59073fdd7713efc4164ff7748ead75fa3022218cb25620b5f7063` |

The audit request was also executed by the same shared runner:

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_INITIAL_AUDIT/f2h10v2-initial-audit-20261002-001/execution-receipt.json`

Its receipt SHA is
`e64991916b6e8494b83de5d8f479a19e1b04426b745acb4de0bb8f82244cb0cc`, and
the report is
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_INITIAL_AUDIT/f2h10v2-initial-audit-20261002-001/report/gem-handoff-initial-structure-audit.json`
with SHA
`1ac7fd6f5dd98996d2fb358f6d1370a1d0721e6ce8fb5be7f1e22e72acab03c5`.

The report has `PASS_INITIAL_STRUCTURE` for all six views. It independently
observes 3D output, the expected fluid count and three native fluid source IDs,
unique typed IDs and positions, zero fluid-boundary overlap, and complete
finite cup, receiver, and tray faces. This is structural evidence only; the
report explicitly carries `qualification_claim=none` and
`production_claim=none`.

## Mass semantics correction

The v2 structural audit's `checks.mass_within_budget=true` compares the
measured PartVTK CSV sum with the expected rounded PartVTK serialized particle
mass. That field is useful for checking serialization consistency, but it is
not a strict continuous-mass approval. The exact cell lattice differs from the
continuous `24.576 kg` by `2.220446049250313e-16`, while the measured CSV sums
are:

| Resolution | Measured CSV mass | Relative error against exact lattice |
| --- | ---: | ---: |
| coarse | `24.576001152000092 kg` | `4.6875003656410286e-08` |
| medium | `24.57600122879828 kg` | `4.99999297520759e-08` |
| fine | `24.576000000007053 kg` | `2.8688162956314045e-13` |

The correction is frozen in
`audits/mass-semantics-correction-20261002.json` (SHA
`68f6c4d99908a960074a6f2e0f6837d4d6c5bed4cbf75e8c81e7cf37fab44ff6`). It does
not normalize any mass, reassign support particles, or relax the `1e-12`
budget. Coarse and medium therefore remain open for a separate numerical mass
decision even though their exact continuous lattice geometry is commensurate;
fine's displayed serialization error is below the budget. No one of these
facts grants QI/QN or production eligibility.

## Next ready action

The v2 manifest and six completed receipts are ready for the parent process to
construct three-dp solver qualification requests per background, with the
actual GenCase directories as input prefixes and the frozen definition,
motion, metadata, and manifest hashes above. GPU/solver work was not started
by this handoff. A subsequent qualification must bind full-state conversion,
moving-body state, lifecycle/exclusion accounting, and separate internal
time/save controls before any QI or QN decision.
