# fresh112 F3-scoped NVMe publication lifecycle hardening

fresh112 is a new disabled source package derived from the committed fresh110
F6/Root722 templates. fresh110 and fresh111 remain byte-for-byte untouched.
The worker is generic over the request's family, frame count, and particle
axis; the 24 shipped disabled templates remain the reviewed F6 full241 cases.

The hardening closes the fresh111 audit findings:

- SIGTERM/SIGINT handlers remain installed through report rewrite, publication,
  and own-stage cleanup. Renderer termination is restricted to the process
  group created with `start_new_session=True`.
- The Home sibling transaction catches `BaseException`, removes its own
  temporary sibling, and rolls back its own published directory if the
  post-rename Home-floor check fails. It never signals or removes another
  process or product.
- The receipt byte total reaches a fixed point before copying. The final file
  walk/hash, stage cap, report cap, pre-publish floor check, and post-rename
  500 GiB floor check all run while `resource-ledger.lock` is held.
- JSON values/keys and PVSM text are recursively checked by path-component
  containment. Private stage and NVMe roots are rejected. Registered external
  trajectory H5 references are preserved as references and are never opened or
  hashed by this wrapper.
- Final report output paths must resolve beneath the final Home product,
  avoiding raw string-prefix acceptance.

The package has 24 disabled requests with null reservation/current attempt and
null future scientific hashes. Root must create a separate enabled binding,
provide a live reservation, and bind metadata input hashes before execution.
The package never launches ParaView, reads or hashes BI4/H5/CSV/DAT/VTK
payloads, writes the shared ledger, or changes Root920/other controllers.

Toy tests cover complete publication, fixed-point receipt bytes, external H5
reference retention, recursive private-path rejection, process-group
termination, `SystemExit` during atomic copy, and `SystemExit` after the
renderer. The 24 disabled requests are preflighted by the validator.

Validation:

```text
python3 scripts/validate_fresh112.py
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

