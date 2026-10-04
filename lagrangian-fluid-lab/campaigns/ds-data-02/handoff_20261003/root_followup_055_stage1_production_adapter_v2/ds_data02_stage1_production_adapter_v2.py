"""Compatibility import name for the Stage 1 visual dispatch adapter v2.

The implementation lives in :mod:`ds_data02_stage1_dispatch_v2`; this module
keeps the descriptive ``production_adapter_v2`` name available to integration
scripts and request builders without introducing a second dispatch path.
"""

from ds_data02_stage1_dispatch_v2 import (  # noqa: F401
    LEGACY_TOP_LEVEL_STATUS,
    SEMANTIC_SIDECAR_SCHEMA,
    VISUAL_STAGE_PROFILE,
    install_stage1_authorizer_alias,
    main,
    run_request,
    semantic_sidecar,
    validate_visual_request,
    write_semantic_sidecar,
)


__all__ = [
    "LEGACY_TOP_LEVEL_STATUS",
    "SEMANTIC_SIDECAR_SCHEMA",
    "VISUAL_STAGE_PROFILE",
    "install_stage1_authorizer_alias",
    "main",
    "run_request",
    "semantic_sidecar",
    "validate_visual_request",
    "write_semantic_sidecar",
]
