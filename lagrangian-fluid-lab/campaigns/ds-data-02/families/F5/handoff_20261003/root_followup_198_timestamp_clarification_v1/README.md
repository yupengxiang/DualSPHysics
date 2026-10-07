# F5 fresh198 timestamp clarification

This additive sidecar leaves the committed fresh198 package unchanged. The fresh198 `visual-decision.json` contains `reviewed_at_utc=2026-10-07T00:55:00+00:00`; that value was manually recorded and is later than the authoritative UTC clock observation `2026-10-07T00:49:01.801203688Z` made while preparing this sidecar. It is therefore not used as a precise review-time authority.

The visual review itself remains complete for all 34 contact sheets and nine keyframes. The visual decision, QI evidence, scope hashes, and producer facts are unchanged. Root should record adoption using its own receipt and verification clock.
