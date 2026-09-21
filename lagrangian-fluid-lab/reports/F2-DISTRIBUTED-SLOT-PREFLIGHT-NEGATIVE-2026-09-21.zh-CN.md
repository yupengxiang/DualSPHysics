# F2 distributed-slot CPU/native preflight negative evidence

Status: **hard negative; zero T1 credit; solver route closed for this input stem**.

The fresh GenCase/native preflight generated 340,003 boundary and 321,600 fluid particles. Native source mass error was 0.500000% and passed the mass gate, but 124,608 boundary normals and 124,608 NormalSize values were zero.

The failure is partitioned by the generated Mk field: the outer tank (Mk=17) and the distributed gate frame (Mk=18) both contain zero-normal particles. This audit proposes only a falsifiable layer-offset hypothesis; it does not modify the failed Definition or rerun it.

No solver, GPU, queue, ledger, registry, matrix, or qualification credit was used.

## Hash closure

- `preflight`: `78c8620a0c1953289b7ed8a4434fa90135c85a4a1617a36780a5813f7db9bbb8` (6692 bytes)
- `bound_vtk`: `14a53fc960413256e5e57340ff720db74bd7062632add26dc1627a9c4f238c5d` (14620426 bytes)
- `generated_xml`: `4cc4d48f6afe46f22adf61985fa0580c5038926876843e20db227a660f074d8e` (9681 bytes)
- `audit_implementation`: `651396c68435eacf630f3e0e7b017d3efd59deddb49184ca477e5777a87bb752` (8906 bytes)
