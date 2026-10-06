# fresh158 — disabled typed downstream handoff

This F5-only source package binds Root854 M085_T100 and Root864 M086_T085 typed `completed/0` metadata and prepares a distinct disabled chain for Root939 M095_T080. It does not read, hash, copy, or launch H5/BI4/CSV/DAT/VTK/science arrays, and it does not alter consumed artifacts or the shared ledger.

M085 report legacy scope is `bbcefe897128ba8b35d5a7f2701733956251cfd4ee6fd34f6eb1eec05a434b16` while its request forecast is `bbcefe897128ba8b35d5a7f2701733956251cfd4ee6fd34f6eb1eec05a434b16`; canonical owner is `0521b11e6a5eab05ca3c8e41058cc55971f6c1dd599650b6947daaaa77837965`. M086 report legacy scope is `ff41cd47740e7d7532982b004ef761ec97feb4b72cbfc77bcd7b3666df0d72c1`, canonical owner is `89a891b45dae3220aaa64f9b8764645cece3164633fb45fc57c0ad8f51c734f3`, and its producer case identity has the `_M086_T085_NEXT34` suffix. These values stay separate.

Use the stage requests in this order after Root materializes each disabled request: terminal typed receipt/report → XMF → actual XMF manifest → full801 bed audit → Root023 render/manual review. The XMF worker takes `--binding --output-dir`. The bed worker takes `--binding --trajectory-h5 --xdmf --output-dir`; the old `--output` spelling is deliberately absent. M086 requires a Root-owned identity adapter before the hard-coded fresh138 bed worker; preserve the nested producer receipt case ID.

M095 Root939 is currently `completed`. Its mutable snapshot request currently asks for `{attempt_root}/trajectory.h5` and `{attempt_root}/conversion-report.json`; the parent plan also names `ar/trajectory.h5` and `ar/conversion-report.json`. Bind the terminal producer receipt/report paths, rather than guessing either layout. All M095 typed, XMF, bed, and render hashes are null here.

All requests are `disabled=true`, `execution_allowed=false`, and `launch_allowed=false`, with Root142 CPU audit/runtime closure, Home floor 500 GiB, render cap 2, no Q-N, and zero case increment. Historical A/B penetration failures and the 5e-6-vs-1e-6 precision negative remain retained.
