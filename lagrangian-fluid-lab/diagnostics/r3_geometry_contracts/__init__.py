"""CPU-only, candidate-only geometry contract diagnostics.

The module in :mod:`probe` deliberately does not import the production
tracer or model code.  It contains small synthetic oracles for the geometry
and input contracts that are easy to accidentally weaken when a consumer is
implemented from exported SPH data.
"""

from .probe import (
    build_g4_model_input,
    build_report,
    build_support_diagnostic,
    dynamic_triangle_diagnostic,
    render_markdown,
    run_mixed_label_diagnostic,
    swept_wall_diagnostic,
    validate_model_input_contract,
)

__all__ = [
    "build_g4_model_input",
    "build_report",
    "build_support_diagnostic",
    "dynamic_triangle_diagnostic",
    "render_markdown",
    "run_mixed_label_diagnostic",
    "swept_wall_diagnostic",
    "validate_model_input_contract",
]
