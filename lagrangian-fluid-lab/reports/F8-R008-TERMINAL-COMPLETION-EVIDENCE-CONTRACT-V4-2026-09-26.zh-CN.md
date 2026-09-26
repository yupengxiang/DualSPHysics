# F8 R008 Terminal Completion Evidence Contract v4

**Status:** proposal-only, diagnostic-only, no execution/readiness/qualification authority. This document is a normative amendment to v3: all v3 clauses remain in force except where this file explicitly replaces or tightens them. V1–V3 and their review records remain immutable history. No trust root, watcher, runtime inventory, input trace, or verifier implementation is established by this proposal.

## 1. Fixed scope and proof boundary

The contract verifies only that one fresh CPU R008 process consumed the pinned inputs, completed a positive-duration run, wrote the pinned outputs, exited normally, and left outputs stable and readable after exit. It does not establish numerical correctness, excluded-fluid absence, T1, T2, power-loss durability, or permission to run a solver. Existing frozen 15-row scope, thresholds, time windows, failure denominator, and gate semantics do not change.

The verifier must derive every completion fact from pinned source/configuration and raw artifacts. Receipt-authored `passed`, `complete`, `flush`, or equivalent claims remain forbidden. If a proof is unavailable, the result is `terminal_completion=missing/open`.

## 2. Positive-horizon and in-loop terminal-save requirements (replaces v3 §4 items 1–3)

The frozen case must have finite `T_end > 0`; its canonical binary64 encoding must match the Definition-derived effective horizon. For the same attempt, the verifier requires all of the following:

1. `RunPARTs.csv` has at least two data rows. The first row is exactly the frozen initial `Part=0`, `Step=0`, `TimeStep=0`; at least one later row represents a completed main-loop save.
2. The terminal log reports exact integer `Nstep >= 1` and one `Simulation finished`, with no interrupted/cancelled/minimum-fluid/`NSTEPS` stop condition.
3. The final main BI4 `PART_####` has `Cpart >= 1`, `Step == Nstep`, and finite `TimeStep >= T_end`; its final RunPARTs row matches `Part`, `Step`, time token, and inventory. The sum of row step increments equals `Nstep`, and row count equals the terminal PART count.
4. The verifier's hash-pinned source profile proves that the initial zero-step `SaveData()` is outside the simulation loop and that a later `SaveData()` is reached only from an executed positive-step loop iteration. The recorded terminal PART must bind to that later save, not merely to the initial PART.

Thus an exit-code-zero run with `TimeMax=0`, only `PART_0000`, zero steps, or a fabricated terminal filename is rejected even if its log says “finished”. The raw RunPARTs/BI4 comparison and post-exit reopen/hash requirements of v3 remain mandatory.

## 3. Automatically loaded `DsphConfig.xml` (extends v3 input inventory and input-access proof)

The pinned v5.4 source has `JCfgRunBase::LoadArgv()` call `LoadDsphConfig(AppInfo.GetProgramPath())` before parsing command-line options (`src/source/JCfgRunBase.cpp`); `JDsphConfig::Init(path)` probes `<program-directory>/DsphConfig.xml` and loads it when present (`src/source/JDsphConfig.cpp`, `JCfgRunBaseDef.h`). This is an input even when argv contains no `OPT` token.

The frozen input inventory therefore has an exact `runtime_config` entry with one of these mutually exclusive states:

- `present`: bind the program-directory root ID and relative path, no-follow inode/type/size, full SHA-256, and exact bytes. The supervisor input trace must prove the child opened and read those same bytes; the verifier parses the pinned XML profile and recomputes all effective configuration values it can affect.
- `absent`: before exec, the supervisor proves with a held, no-follow program-directory descriptor that the exact `DsphConfig.xml` name is absent; the program directory and its parent chain are frozen read-only for the child lifetime. The input trace must show no successful lookup/open of that path.

Unknown state, symlink, mutable directory, unresolved probe, or mismatch is reject. This rule supplements—not replaces—the Definition/control/initial-state manifest and syscall trace. `opt_sources=[]` is not evidence that this automatic input is absent.

## 4. Output isolation, exit-to-hash race, and stable snapshot (replaces v3 output-root/watch clauses)

The output root is a fresh per-attempt directory in a supervisor-controlled private mount/namespace, identified by a held directory descriptor and device/inode. Only the identified child process tree may write it during execution. The supervisor must terminate/reap the entire process group and descendants before declaring process exit complete.

`termination_watch` begins before exec and remains losslessly active until **after** the verifier has reopened, parsed, and hashed every required artifact. Its coverage includes child exit, descendant reap, output sealing, and final hash. Any output create/write/rename/unlink after child exit and before sealing is a hard reject; any mutation after sealing is also a hard reject. A zero-event list without an independently authenticated, lossless watcher is insufficient.

After exit and descendant reap, the supervisor must establish a write-exclusion barrier on the held output tree (private namespace plus read-only seal, or an equivalently strong kernel-enforced mechanism), prove there are no remaining writable handles/actors, record the seal time and mechanism in the supervisor-signed evidence, and keep the tree sealed through verification. Hash and parse bytes through the same no-follow held descriptors; compare `fstat` identity/size before and after each read. A path-based reopen, caller-set `exclusive_writer=true`, or watcher that stops at child exit does not close the race. If the platform cannot provide and attest this barrier, output integrity remains `missing/open`.

This is a stable post-exit read boundary, not `fsync` or power-loss durability. The v3 durability disclaimer remains in force.

## 5. Trust bootstrap, registry chain, revocation, and trusted time (replaces v3 §3.4 trust bootstrap)

No receipt may establish its own trust. The verifier starts with task-external policy bytes containing the trusted root key IDs/public keys and the SHA-256 of one canonical genesis-anchor object. The expected digest and root key material are provisioned outside the candidate directory and are not supplied by the receipt, solver, or caller.

The genesis anchor is canonical JSON with exact fields and no extensions:

```text
{schema, trust_root_id, registry_key_id, registry_public_key_base64,
 time_key_id, time_public_key_base64, dependency_pin_set_id, signature_base64}
```

`schema` is `core.cfd.f8.r008.supervisor_genesis_anchor.v1`; IDs match `^[a-z][a-z0-9_.-]{0,63}$`; public keys are canonical padded RFC 4648 base64 decoding to exactly 32 Ed25519 bytes. Verify the externally pinned anchor SHA first, then verify `signature_base64` (64 decoded bytes) with the externally pinned root key over `ASCII("CORE-F8-R008-SUPERVISOR-GENESIS-V1") || 0x00 || canonical(anchor without signature_base64)`. The anchor fixes the registry/time keys and exact dependency pin-set identifier; it is not self-signed.

The registry is likewise canonical JSON, exact-keyed, and signed by the genesis registry key with domain `CORE-F8-R008-SUPERVISOR-TRUST-REGISTRY-V1\0`. Its exact root keys are `{schema,trust_root_id,registry_key_id,sequence,issued_time_ns,not_before_ns,not_after_ns,revoked_key_ids,keys,dependency_pin_set_id,dependency_pins,signature_base64}`. It binds an exact positive-integer `sequence`, validity interval, sorted unique revoked key IDs, sorted unique scope-limited supervisor/verifier keys, host/scope allowlists, and exactly the seven v3 dependency pins with their v1 schema IDs and canonical-payload SHA-256 values. Each key record has exact keys `{key_id,public_key_base64,not_before_ns,not_after_ns,revoked,scope_ids,host_ids,roles}`; IDs and allowlists are sorted/unique, `revoked` is a JSON boolean, and roles are drawn from the fixed enum `{supervisor,verifier}`. Each dependency record has exact keys `{dependency_id,schema_id,schema_version,payload_sha256,not_before_ns,not_after_ns}` and must equal the genesis-pinned set. Unknown keys, dependency IDs, schemas, duplicate records, invalid validity interval, or a revoked/expired key fail closed. The verifier compares `sequence` to task-external monotone state: lower sequence rejects; equal sequence is accepted only with the identical registry digest; a higher sequence is atomically persisted outside the candidate namespace before use. No in-receipt key rotation or dependency registration is allowed.

Validity and revocation are checked against a fresh task-external trusted-time token, exact-keyed canonical JSON `{schema,nonce,unix_time_ns,key_id,signature_base64}`. Its schema is `core.trust.time_attestation.v1`; `nonce` is the verifier's fresh 32-byte lowercase hex challenge; `unix_time_ns` is an exact positive JSON integer; `key_id` equals the genesis-pinned time key ID; the signature is Ed25519 by that key over `ASCII("CORE-TRUST-TIME-ATTEST-V1") || 0x00 || canonical(token without signature_base64)`. Reject replayed nonce, invalid signature, a response received more than 60 seconds after the verifier sent that nonce (measured on the verifier's monotonic clock), registry/key/dependency validity failure, or revocation. No trusted-time token means no authenticated terminal evidence.

The verifier then validates the receipt attestation, attempt/host/scope, the seven exact dependency pins, and only then the process/input/output claims. All canonical encodings, signature domains, and strict base64 rules in v3 remain in force. These schemas specify a future trust protocol; the required external anchor, registry, keys, trusted-time service, and verifier are not currently available.

## 6. Runtime locale and formatter attestation (replaces v3 locale self-claim clauses)

`LC_ALL=C` and `LC_NUMERIC=C` in argv/environment are necessary but not sufficient. The pinned `runtime_environment` dependency must include the executable, dynamic loader, libc, libm, libstdc++, and complete transitive loaded-library closure with paths, file identities, and hashes. The trusted supervisor records the actual `LC_NUMERIC` value as observed inside the child immediately before Definition parsing, option/TMAX parsing, and every RunPARTs numeric formatting phase; each observation is tied to monotonic time and thread ID. Every required observation is exactly `C`.

The supervisor profile must also prove lossless process-wide monitoring of `setlocale()` and thread-local `uselocale()` on every child thread. The pinned build uses an exact link-wrapper profile for `setlocale`, `uselocale`, thread creation, `dlopen`, and `dlsym`; every wrapper event is recorded, dynamic loading/symbol lookup that can bypass the wrappers is denied, and every child thread is registered and probed before it can parse or format numeric data. Instrumented probes immediately before Definition/TMAX parsing and each RunPARTs numeric-format call query the active thread locale and `LC_NUMERIC`; all values must be exactly `C`. The initial transition to `C` is allowed; any subsequent locale change, unregistered thread, lost event, or non-C observation rejects the attempt. The pinned source/build/runtime closure must prove all relevant calls resolve through this wrapper profile. Record its exact schema/version/hash, event count, loss count, thread coverage, and verification time. A caller-supplied locale string or environment snapshot alone is not proof. If this runtime attestation is unavailable, exact RealStr token comparison remains `missing/open`.

## 7. BI4 byte order is decoded from each authenticated header (replaces v3 §3.5 hardcoded endian)

Do not assume little-endian. The hash-pinned v5.4 `JBinaryData` header is read first (64 bytes; `byteorder` at offset 60, `si64` at offset 61). Validate the exact title/padding and `si64 ∈ {0,1}`. Normalize the header's byte-order byte as `byteorder - 10` when `si64=1`, otherwise `byteorder`; the result must be `0` (little-endian) or `1` (big-endian), matching the source enum. Decode every multibyte header/item/array value using that per-file order and the pinned BI4 rules; reject unknown or contradictory values. The receipt records the raw header bytes/hash and derived byte order, but the verifier independently derives it from the same sealed file bytes. Source anchors: `src/source/JBinaryData.h:189` and `src/source/JBinaryData.cpp:1293,1346–1351`.

## 8. Exact nested schemas and common scalar constraints (tightens all v3 schema tables)

Every JSON object in the receipt, genesis anchor, registry, time token, dependency payload, input/output manifest, trace, and watcher schemas has a complete required-key set and `additionalProperties=false`; nested objects are not open-ended. Every field has exact JSON type and bound. Integer fields are JSON integer tokens checked with exact type (reject `bool`); JSON floats are forbidden. Hashes are 64 lowercase hex; canonical UUIDs are lowercase UUIDv4; root/key/scope IDs match `^[a-z][a-z0-9_.-]{0,63}$`; file paths are 1–1024 ASCII bytes, normalized relative POSIX paths with no absolute path, empty/`.`/`..` component, NUL, backslash, symlink traversal, or duplicate. Base64 must strict-decode and re-encode byte-identically. Arrays have explicit minimum/maximum lengths, sortedness/uniqueness where prescribed, and aggregate byte/depth limits from v3. Canonical UTF-8 JSON bytes, duplicate-key rejection, field ordering, and no-trailing-byte rules remain exactly as in v3.

For existing v3 objects, the v3 field tables are the complete required sets; this section disallows any interpretation that an unlisted nested key, root ID, enum, or bound may be caller-defined. For new objects in this amendment, the exact field sets and values are those written in §§3, 5, 6, and 7; implementation must publish machine-readable schemas before any implementation review. Where this prose has not pinned an enum/range or an external profile hash, the item remains `missing/open`, not implementation discretion.

## 9. Verification order and unchanged authorization boundary

The fail-closed order is: (1) bounded strict parse/canonical bytes/exact schemas; (2) external policy digest and genesis signature; (3) fresh trusted-time token, registry signature, expiry/revocation, key/scope/host and seven dependency pins; (4) receipt signature and attempt identity; (5) source/build/runtime closure, parser/profile, Definition/control/initial-state/runtime-config inputs and syscall trace; (6) process, locale, watcher, descendant-reap and output-seal evidence; (7) no-follow stable reads, BI4 per-file byte-order parse, RunPARTs/log/terminal-save recomputation and full output inventory. Any missing, reordered, unauthenticated, lossy, mutable, or unequal evidence returns `missing/open` and zero credit.

This proposal authorizes no GenCase, native decoder, solver, worker, GPU, queue, production HDF5/PART/BI4 access, trust-registry mutation, ledger mutation, or gate change. R008 remains `T1_numerical=false`, readiness false, credit zero unless and until separately authorized execution passes all frozen gates.

## 10. Independent review checklist

1. Does the positive-horizon proof exclude a successful initial-only `PART_0000` run while matching the pinned v5.4 save loop?
2. Is automatic `DsphConfig.xml` discovery fully covered, including absent-path proof and immutable program-directory semantics?
3. Does output sealing plus lossless watch close every child-exit-to-hash writer race, including descendants and open write handles?
4. Is the external genesis → registry → scope key/dependency pin → receipt chain cryptographically and temporally complete, with replay/revocation handling?
5. Do runtime locale observations and `setlocale`/`uselocale` monitoring actually bind parse/format semantics across all threads and loaded code?
6. Does per-file BI4 endianness follow the authenticated 64-byte header without assuming host order?
7. Are exact nested required keys, enums, ranges, path/ID constraints, and verifier order sufficiently deterministic to implement without trust-bearing caller choices?

Review scope is read-only contract review only. No production input, GenCase, native decoder, solver, worker, GPU, queue, or registry/ledger state is to be touched.
