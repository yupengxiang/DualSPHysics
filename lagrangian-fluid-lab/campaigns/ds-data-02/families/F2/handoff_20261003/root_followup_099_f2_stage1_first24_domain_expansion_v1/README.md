# F2 fresh099 first24 source-only expansion

This package adds sixteen prospective F2 conditions to the existing first8
source set. The new tuples are:

* receiver `x = 0.46, 0.48, 0.52, 0.54, 0.57, 0.59, 0.62, 0.64 m`;
* reviewed open-rim receiver `y = 0.14 m`, fill `0.8`, `dp = 0.01 m`, and
  three source layers with zero initial velocity;
* each receiver position paired once with the reviewed `0.65 s` forcing and
  once with the reviewed `1.20 s` forcing, both ending at `-105 degrees`.

The official P01 XML is copied per case and stripped to the receiver low-x
point and motion-file identity. The generated source remains 3-D with the
unchanged `4.0 s`, `0.01 s`, and 401-frame recipe. `source/` contains only XML,
motion text, and metadata; no GenCase/BI4/CSV/VTK/H5 output is present.

Every case has disabled, `source_only` GenCase, native initial-QA, native
solver, and future NVMe typed requests. Each request has a closed digest map
over source/contract files and the case owner metadata. Future counts, masses,
receipt hashes, native scope, typed hashes, qualification, precision, Q-N, and
production approval are null or explicitly ungranted. The native command is
exactly `DualSPHysics5.4_linux64 {gencase_prefix} ... -tmax:4.0 -tout:0.01`;
no extra mDBC/no-slip option is added.

Root326, P01, P03, and mother decisions are recorded as read-only domain
evidence. Their visual decisions establish a bounded open-rim offset control
range; they do not grant new cases visual or numerical acceptance. Initial tilt,
short-spout, and other opening holdouts are excluded because this package has
no reviewed official XML implementation for those mechanisms.

Run the package-local validator to audit XML, motion, identity uniqueness,
disabled flags, input digest closure, and null future evidence:

```text
python3 workers/fresh099_source_contract_validator.py \
  --output evidence/source-contract-audit.json
```

The validator reads only source/contract text and JSON. It does not start a
worker or open scientific arrays.
