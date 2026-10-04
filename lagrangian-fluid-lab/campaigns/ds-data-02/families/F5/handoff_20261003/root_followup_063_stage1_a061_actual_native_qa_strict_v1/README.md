# F5 A061 actual native QA strict worker (063)

This fresh CPU audit is bound to Root's genuine A061 GenCase attempt 075:

```text
total_particles=214385
fluid_particles=40710
solver_dimension_from_gencase=3
```

The worker is adapted from the successful Root compact QA054 worker, but uses
the A061 explicit source profile and the actual 075 total. It runs official
PartVTK against the fresh 075 XML/BI4 and checks the generated native rows:

- finite coordinates, positive mass/density, 3-D XML and receipt;
- consecutive unique native `Idp`, exact XML type/Mk block agreement, and the
  expected type set `{0,1,3}`;
- zero initial velocity, fluid count 40710, and exact coordinate uniqueness;
- pairwise fixed/moving/fluid coordinate no-overlap;
- native fluid CSV mass versus the bound continuum mass, reported without
  rescaling;
- source definition and 075 XML/BI4 hashes unchanged;
- fluid initial coordinates not below the exact piecewise source profile in
  the bed y-domain `-0.15 <= y <= 0.15`.

The Mk40 diagnostic filters the actual fixed rows to strict interior bed y
coordinates and reports profile-segment support only. Mk40 is a mixed
boundary cohort that includes walls, so the report explicitly makes no
continuous-bed or Mk40-bed-only claim. Repair success remains unknown until
the later short event and framewise bed-domain penetration audit.

`request.json` is a disabled strict CPU request. It writes only a fresh 063
attempt output directory; it never modifies the genuine 075 attempt. No
worker, PartVTK, solver, or raw-array audit was run while preparing this
handoff.
