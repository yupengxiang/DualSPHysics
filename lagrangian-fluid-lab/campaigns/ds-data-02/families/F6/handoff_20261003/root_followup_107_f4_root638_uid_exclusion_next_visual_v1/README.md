# fresh107: Root638 UID-exclusion evidence and next visual cases

This F6-owned read-only sidecar leaves fresh105/fresh106 and all consumed products immutable. It adds two items:

1. For `...uz0p60000`, it records native receipt/stdout evidence (`Excluded particles: 2`, `Excluded particles due to Density: 2`, execution code 0) and compares it with the typed report's two missing UIDs beginning at frame 1043. The evidence supports count-level corroboration only. It does not bind the same two UIDs because the excluded identity payload was not read.
2. It indexes the next two Root638 `completed/0` F4 cases that have no `visual-approved-by-root` decision: `uz0p60000` and `yoffm0p04000/uz0p40000`. Each case includes actual native, frame0-QA, typed, XMF, manifest, render, contact-page, keyframe, and numerical-limit metadata.

No BI4/H5/CSV/DAT/VTK/array payload was opened or hashed; PNGs were represented by filenames and existence only. No job or shared state was changed.

Validate with:

```sh
python3 workers/validate_fresh107.py
```
