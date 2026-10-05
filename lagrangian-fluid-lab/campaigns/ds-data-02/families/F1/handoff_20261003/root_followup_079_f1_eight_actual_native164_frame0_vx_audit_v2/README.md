# F1 fresh079: Root164 native frame-0 Vx audit, strict PartVTK summary-time fix

This source-only handoff keeps the Root179 native-Mk=1 binding repair and adds a narrow time parser fix. Root180 established that official PartVTK particle CSVs begin with a `TimeStep [s], Np, ..., Nfluid` header, its next non-empty numeric row, a blank line, and then particle columns. The worker now locates those named fields, parses only the following row, requires `Np` and `Nfluid` to match each binding, and retains the existing finite/velocity/time-tolerance gates. It never turns a missing or nonnumeric time into zero.

Root179's failed canary remains historical evidence and is not promoted. Root enables only these disabled requests after reviewing the new worker; no future frame-0 BI4 hash, audit report hash, or VX qualification is fabricated in this package.

The worker is `7620914b1e192e6676b18719381a7a8f8c8fb4e85ce5286b11e5a46bb1ece543`. The source turn read no scientific BI4/H5/CSV arrays and did not launch a task.
