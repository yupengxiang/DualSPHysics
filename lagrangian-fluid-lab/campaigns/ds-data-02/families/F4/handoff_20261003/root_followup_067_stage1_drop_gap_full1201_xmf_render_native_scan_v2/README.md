# F4 full 1201 XMF and native-valid-point camera handoff (fresh067)

This source-only package binds the two actual completed Root077 native and Root103 typed endpoint inputs. Both endpoints have 1201 saved frames, 83233 particles, and 59072 fluid particles. Their canonical physical condition hashes and opaque HDF5 hashes are retained from fresh066; HDF5 and numerical arrays were not opened here.

The disabled Root105 XMF requests preserve actual typed time values, all 1201 frames, and the 51 contact-page keys. Future case.xmf, manifest, and execution-receipt SHA values are null. The paired ParaView requests remain disabled until the matching XMF result is actually completed and bound; all future render SHA values are null.

fresh067 removes camera-driving camera_bounds and domain_bounds from bindings and future manifests. XML physical tank and definition bounds remain only as xml_defined_physical_tank_bounds and xml_defined_domain_bounds provenance. The renderer rejects camera/domain fields and scans every selected saved frame's valid native positions through XdmfReader. The source reader remains unclipped.

No GenCase, solver, XMF export, ParaView render, HDF5/BI4/CSV array read, or shared registry/ledger write was performed. Root may enable XMF, bind its actual receipt/manifest, then enable the matching render request. Both endpoints retain independent case count increment 0 and pending visual/numerical/production review.
