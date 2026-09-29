# DS-DATA-01 task graph

```text
                         ┌──────────────┐
                         │ D00 scope    │
                         │ + snapshot   │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                         │ D01 official │
                         │ inventory     │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                         │ D02 replay +  │
                         │ mechanism map │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                         │ D03 per-scope │
                         │ quality gates │
                         └───┬────┬───┬──┘
                             │    │   │
                   ┌─────────▼┐ ┌─▼──┐ ┌▼────────┐
                   │ D04 split │ │D06 │ │ D07     │
                   │ + params  │ │tags│ │evaluator│
                   └────┬──────┘ └─┬──┘ └──┬──────┘
                        │          │       │
                        └────┬─────┴───────┘
                             ▼
                         ┌──────┐
                         │ D05  │
                         │prod. │
                         └──┬───┘
                            ▼
                         ┌──────┐
                         │ D08  │
                         │handoff│
                         └──────┘
```

Each family/scope has its own canary → audit → 4–8-case batch → continuation
path. A failed canary records a bounded negative and does not close unrelated
families. The D07 evaluator may be implemented and tested with reference
self-comparisons and synthetic perturbations without any learner.

The historical learning queue is outside this graph. Its receipts are kept
for provenance but cannot block D02–D08.
