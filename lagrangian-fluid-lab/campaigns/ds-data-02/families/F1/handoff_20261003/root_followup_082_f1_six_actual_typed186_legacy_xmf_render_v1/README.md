# F1 fresh082: actual Root186 typed temporal XMF/render handoff

This source-only handoff assembles six existing F1 typed conversions that have
actual Root186 `completed/0` receipts:

- ECC H110 VX010 and VX020: 161 saved frames, 1.6 s window.
- ECC H190 VX010 and VX020: 161 saved frames, 1.6 s window.
- DUAL H220 VX010 and VX020: 401 saved frames, 4.0 s window.

The HDF5 converter reports use `hash_scopes.physical_condition_sha256` with
`legacy-owner-scope.v0`. Each binding records that hash as
`legacy_h5_physical_condition_sha256`. The canonical physical identity is
bound independently to the immutable fresh079 source owner and its normalized
`physical_binding` JSON SHA. The two hashes are checked to remain distinct;
there is no attempt to make a legacy converter scope equal a canonical physical
binding.

`workers/export_xmf_legacy_aware.py` is a Root193 CPU worker. At actual launch
it validates the completed GenCase/native/Root181 metadata chain, verifies the
H5 attribute against the converter report's legacy hash, and writes a full
saved-frame temporal XMF. The source turn did not open or hash H5; the typed
H5 SHA is adopted from the completed converter report's verified
`output_sha256`.

`workers/render_native023.py` is the copied Root023 renderer
(`5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66`). Root194
requests use CPU2 software/offscreen ParaView and scan valid native positions
across every XDMF time for camera bounds. They retain the full native reader
and use display-only cutaways. Expected contact sheets are 7 for ECC and 17
for DUAL H220.

All twelve Root193/194 requests are disabled, have future output hashes null,
and carry no Q-N, cross-resolution precision, visual acceptance, production, or
independent-case claim. Root should enable each XMF request first and then its
render request after the XMF receipt is `completed/0`.

Validation is metadata-only:

```text
python3 validate_source_contract.py
```

No GenCase, solver, converter, XMF, ParaView, shared registry, or ledger task
was launched by this source handoff. No BI4/H5/CSV arrays were read or copied.
