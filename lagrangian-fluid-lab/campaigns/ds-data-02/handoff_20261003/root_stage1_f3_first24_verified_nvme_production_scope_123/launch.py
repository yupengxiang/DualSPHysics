"""Root routing through unchanged strict dispatcher and runtime under explicit visual adapter."""
import sys
from pathlib import Path
sys.path.insert(0, '/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts')
sys.path.insert(0, '/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_followup_055_stage1_production_adapter_v2')
import ds_data02_stage1_dispatch_v2 as adapter
if __name__ == "__main__":
    raise SystemExit(adapter.main())
