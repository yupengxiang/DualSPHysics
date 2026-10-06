# F3 fresh146 first8/first24 membership audit

This is a metadata-only membership proof. It uses the frozen first8 decision, the ordered first24 case manifest, and Root1198’s current 48-case F3 roster. It matches case IDs and physical IDs without selecting by sorted order or counting resolution/retry aliases.

All 8 first8 entries and all 24 first24 entries occur in the current 48-case roster. The first8 hashes match the roster exactly. For first24, 22 hashes match, AY0270 is pending with a null roster canonical hash, and AY0340 has an intentional source-plan versus canonical decision hash split documented by its accepted decision (`legacy-owner-scope.v0`, no cross-resolution equality claim).

The package reads only JSON metadata. It does not open, copy, hash, or view scientific payloads or PNGs, and it does not launch jobs or alter shared state. The registered-render recheck found no newly published terminal completed render, so no visual review was performed here.

Run `python3 scripts/validate_fresh146.py` for structural and hash-closure validation.
