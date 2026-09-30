import unittest
from policy_reference import admit_native_case, can_finish, PROHIBITED

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.c = dict(task_kind="production", family_id="F3", recipe_id="r1", qualified_scope_id="s1",
                      physical_case_id="p1", lineage_group_id="l1", integrity_passed=True,
                      within_verified_domain=True, full_event_window=True, split_lineage_passed=True,
                      active_inputs_verified=True, target_view="core_3d", solver_dimension=3, lifecycle="closed")
        self.r = dict(family_id="F3", recipe_id="r1", qualified_scope_id="s1", role="reference",
                      numerical_reference_status="qualified", data_semantics="native_numerical_trajectory")
        self.b = dict(owner_adoption_valid=True, within_budget=True, within_deadline=True, resource_lease_valid=True)
    def allowed(self): return admit_native_case(self.c,self.r,self.b).allowed
    def test_complete_scoped_data_passes(self): self.assertTrue(self.allowed())
    def test_no_external_validation_needed_for_declared_numerical_scope(self):
        self.r["external_validation_status"]="not_assessed";self.assertTrue(self.allowed())
    def test_material_optional(self):
        self.r["material_tracer_status"]="failed";self.assertTrue(self.allowed())
    def test_no_model_needed(self):
        self.r["model_status"]="missing";self.assertTrue(self.allowed())
    def test_unrelated_failure_does_not_block(self):
        self.r["unrelated_family_failures"]=["F1","F6"];self.assertTrue(self.allowed())
    def test_cross_family_receipt_rejected(self):
        self.r["family_id"]="F1";self.assertFalse(self.allowed())
    def test_canary_not_reference(self):
        self.r["role"]="canary";self.assertFalse(self.allowed())
    def test_integrity_only_not_numerical_reference(self):
        self.r["numerical_reference_status"]="Q-N-integrity-pass";self.assertFalse(self.allowed())
    def test_missing_full_event_rejected(self):
        self.c["full_event_window"]=False;self.assertFalse(self.allowed())
    def test_z_coordinates_do_not_establish_3d(self):
        self.c["solver_dimension"]=2;self.c["coordinate_components"]=3;self.assertFalse(self.allowed())
    def test_open_requires_accounting(self):
        self.c["lifecycle"]="open";self.c["target_view"]="open_3d";self.assertFalse(self.allowed())
        self.c["lifecycle_accounting_passed"]=True;self.assertTrue(self.allowed())
    def test_expired_authorization_rejected(self):
        self.b["within_deadline"]=False;self.assertFalse(self.allowed())
    def test_learner_actions_forbidden(self):
        for kind in PROHIBITED:
            self.c["task_kind"]=kind;self.assertFalse(self.allowed())
    def test_shared_actual_input_defect_blocks(self):
        self.c["active_inputs_verified"]=False;self.assertFalse(self.allowed())
    def test_checkpoint_not_terminal(self):
        self.assertFalse(can_finish(product_complete=False,ready_task_count=3,required_branches_have_terminal_evidence=False))
    def test_no_ready_but_unimplemented_branch_not_complete(self):
        self.assertFalse(can_finish(product_complete=False,ready_task_count=0,required_branches_have_terminal_evidence=False))
    def test_bounded_negative_with_evidence(self):
        self.assertTrue(can_finish(product_complete=False,ready_task_count=0,required_branches_have_terminal_evidence=True))
    def test_resource_stop_allows_partial_only(self):
        self.assertTrue(can_finish(product_complete=False,ready_task_count=3,required_branches_have_terminal_evidence=False,hard_resource_stop=True))

if __name__ == "__main__": unittest.main()
