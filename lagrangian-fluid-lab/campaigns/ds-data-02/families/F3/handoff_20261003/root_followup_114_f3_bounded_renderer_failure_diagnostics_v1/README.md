# fresh114 F3 bounded renderer failure evidence

fresh114 is an independent F3-scoped successor derived from the committed
fresh112 worker. It changes only rejection diagnostics; fresh112, Root934,
and their receipts remain byte-for-byte untouched.

When a Root023 renderer fails, is rejected before publication, or raises in
the wrapper, the worker captures evidence before removing its own private
NVMe stage:

- the exact renderer `argv` used by `Popen`;
- the renderer PID and process-group ID captured immediately after spawn;
- the observed return code and a bounded reason;
- at most the final 16 KiB of the wrapper-owned stdout and stderr logs.

The rejection JSON is written before cleanup and rewritten after cleanup with
the actual `stage_removed_after_rejection` state. Thus a cleanup error still
leaves bounded evidence. The worker never reads or hashes H5, BI4, CSV, DAT,
VTK, or other scientific payloads. The successful publication path and its
Root112 receipt contract are unchanged. The package contains no enabled
request and starts no job.

`metadata/root920-root934-comparison.json` is a JSON-only comparison of the
successful Root920 request and failed Root934 request. It records their PV
environment, argv/entry differences, manifest references, and the Root937
imports-only result without opening scientific payloads. It does not infer a
renderer root cause; Root142 must run the registered no-H5 diagnostic.
Root937's imports-only probe covered `vtkmodules.util.numpy_support`; it did
not cover the renderer-specific `paraview.vtk.util.numpy_support` helper, so it
is not an exact helper import proof.

Validation:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 scripts/validate_fresh114.py
```
