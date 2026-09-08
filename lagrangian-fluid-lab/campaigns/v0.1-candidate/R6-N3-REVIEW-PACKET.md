# R6-N3 reviewer packet

This packet is for the cloud reviewer.  It is based on baseline
`dcfef001eed3889ca6a055619a31dd4964515638` and the N3 reports below; all conclusions are
candidate numerical evidence only.

## Requested review

1. Confirm whether the P1 `PartOut`/`RunPARTs` joins support the conclusion that
   the old fine-grid losses are density exclusions rather than top absorption.
2. Assess whether `cflnumber=0.1` is an acceptable single-factor numerical
   repair probe.  The endpoint and h10 bridge are deliberately not promoted to
   formal T1 because h09/h11 coarse/medium were not rerun at that recipe and
   the h10 coarse-to-medium TV diagnostic failed (`0.0569047619 > 0.05`).
3. Check the P3 source-wise full-time semantics: target occupancy, first
   passage, terminal category, unknown/error, support rejection, and no
   survivor renormalization.
4. Check P4 parity and the decision to retain the CPU tracer path because CUDA
   is only `1.406719036635956`× end-to-end versus CPU Torch.
5. Recommend the next bounded gate, including whether the missing same-recipe
   endpoint resolutions justify a new solver budget.

## Evidence files

- P0: `campaigns/v0.1-candidate/r6-n3-phase-profile.json`
- P1: `campaigns/v0.1-candidate/r6-n3-endpoint-forensics.json`
- P2 endpoints: `campaigns/v0.1-candidate/r6-n3-endpoint-closure.json`
- P2 bridge: `campaigns/v0.1-candidate/r6-n3-bridge-h10.json`
- P3: `campaigns/v0.1-candidate/r6-n3-material-reference.json`
- P4: `campaigns/v0.1-candidate/r6-n3-performance.json`

## Current disposition

`formal_release=false`, `development_authorized=false`, `G4=not launched`.
Please treat all raw attempt directories as local provenance rather than Git
artifacts; the machine reports contain SHA-256 hashes and exact paths.
