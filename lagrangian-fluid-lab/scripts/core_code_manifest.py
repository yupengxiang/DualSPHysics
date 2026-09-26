"""Single declared file closure for portable Core runtime entrypoints.

Keep bundle contents and reproduction code evidence derived from this same
ordered list.  In particular, ``core_benchmark`` imports ``core_package`` at
runtime to verify immutable bundles; that dynamically reached dependency is
part of the runtime closure even though it is not imported at module load.
"""

CORE_RUNTIME_CODE_FILES = (
    "core_benchmark.py",
    "core_runtime.py",
    "core_contract.py",
    "core_dataset.py",
    "core_models.py",
    "core_learning.py",
    "core_cfd_dataset.py",
    "core_package.py",
    "core_evaluation.py",
    "core_physics.py",
    "core_reproduction_check.py",
    "core_fsverity.py",
    "core_strict_json.py",
    "f7_pump_geometry_adapter_v1.py",
    "passive_tracers.py",
    "f3_control.py",
    "core_code_manifest.py",
)
