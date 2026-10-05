# F1 fresh093 GenCase initial-QA contract repair

Fresh091 is preserved as immutable historical evidence. Root actual attempts showed a pre-PartVTK failure because `workers/gencase_initial_qa.py` accessed `case["prefix"]`, while all 24 fresh091 bindings omitted that key. Fresh093 copies the same worker without changing its scientific checks and adds the derived prepared-prefix field to every binding. The metadata-only AST audit enumerates every `case[...]` and `binding[...]` access and checks all 24 bindings.

The 24 GenCase receipts/reports/XML are actual completed/0 metadata inputs. BI4 remains producer-attested provenance and is a future Root worker input; this source package never reads or hashes BI4, CSV, H5, DAT, or VTK payloads. All fresh093 QA requests are disabled and future receipt/report hashes remain null. A passing fresh093 QA has not been claimed here.
