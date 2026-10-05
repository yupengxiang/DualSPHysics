# F5 fresh088: binding-contract repair after Root279/280 pre-array failures

Root265 remains the only fresh void-fill GenCase artifact bound here: actual metadata is 194427 total, 162005 fixed, 4480 moving, 0 floating, 27942 fluid, 3-D. Its receipt SHA is `672a22e4062cbc858b796e86d2127f1116b9d62a08e4da641d99846a226ce8fa`, XML SHA `4c4a57a3fefb3991443507b08184b0bcc6e63309daabbb7b3a28265079f0415a`, prepared-report SHA `5a72b305616c99477cdfe1964fb7b2e4f56f385dc3584e734efb8c4af1a2473b`, and producer-declared BI4 SHA `ea361f560a6b6aa3f10d46ed379efde01a026a46dd3e515b5ebc61b8540064bc`.

Root279 and Root280 both failed before PartVTK/CSV science. Root279 compared the GenCase receipt's nested attempt `root-stage1-f5-c082r1-official-void-fill-genuine-gencase-265` with the QA attempt `root-stage1-f5-c082r1-voidfill-actual-native-initial-qa-279`. Root280's copied diagnostic worker expected `binding.actual_gencase`, which the fresh087 adapter did not supply. Their receipt/stdout hashes are retained in `failed-279-280-evidence.json`; they are not interpreted as physical failures or passes.

The fresh088 QA worker uses explicit `qa_attempt_id` and `gencase_attempt_id`, and checks the GenCase receipt against the latter. The corrected cohort worker binds `actual_gencase` to the old R1/234 producer of the registered Root246 CSV (`194427/158559/4210/31658`) and records Root265 (`194427/162005/4480/27942`) separately as a new candidate. This prevents count mixing. Its y cohort remains `-7..+7`; Root264's wrongly labelled output remains preserved.

The only source-semantic observation is that changing the fluid primitive from `drawbox boxfill=solid` to official `fillbox modefill=void` preserved total rows but changed category metadata by +3446 fixed, +270 moving, and -3716 fluid. This is an observed ownership/classification redistribution, not a proven mechanism or physical acceptance.

Fresh088 provides disabled requests for actual QA 281, corrected cohort diagnostic 282, and Type0/Mk50 six-segment footprint audit 283. No solver, converter, dynamic audit, full16, or full801 stage is enabled. No threshold is relaxed, and no arrays are opened by source preparation.
