# fresh089 — Root237 QA to Root230 full1201 bindings

This F4 package binds the six lattice-aligned `.190/.200/.210/.230/.240/.250`
cases to the actual Root227 individual GenCase receipts and Root237 native
initial QA.  The six qualification requests remain disabled source artifacts;
Root must review and launch them through the combined Root230 entry.

Root235 and Root236 are preserved as failed metadata-alias attempts.  Root237
is the first accepted QA provider here: its execution receipt is completed with
OS return code 0, its index and binding pass for all six cases, and each case
report is bound by path and digest.  The reports are evidence of initial native
input QA only.  They do not grant visual, precision, Q-N, production, or
independent-case credit.

The builder and child-input preflight only read JSON/XML/Python metadata and
`stat` the producer-owned BI4 files.  BI4 bytes are never opened or hashed by
this source package.  Every request keeps the generated XML and BI4 deferred;
the XML digest is carried from the Root227 producer report and the BI4 digest
is carried as a producer digest.  The solver command is the exact DP.010,
`-tmax:1.2`, `-tout:0.001` recipe with 1201 native frames.

`root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py` is the
required future execution entry.  Its Home-floor and eight-UUID policy files,
strict dispatcher, runtime, resource window, solver binary, QA receipts, and
all per-case child audit inputs are digest-bound in each request.  Nothing in
this package starts a GenCase, QA, conversion, solver, or GPU process, and it
does not write the shared registry or ledger.

To rebuild the deterministic disabled requests after a Root QA replacement:

```text
python3 workers/build_f4_root237_full1201_bindings_v1.py
```

The default inputs point at the actual Root227 binding and Root237 output.
The builder refuses a missing or failed QA receipt/index/binding/report and
refuses a producer digest mismatch.  Run the child preflight for a concrete
case with the generated manifest:

```text
python3 workers/preflight_f4_root237_child_inputs_v1.py \
  --manifest manifests/F4_DROP_LATTICE_GAP0p19000_DP010.json \
  --output /tmp/f4-root237-child-preflight.json
```

The output is an audit of input paths and provenance only.  It cannot enable a
request.
