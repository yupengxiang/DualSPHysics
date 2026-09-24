"""Immutable scalar-scope production registration and evidence-gated 8→32 batches."""
import math
from scripts.core_dataset import new_scope_split

FIRST_EIGHT = (0,4,8,13,18,23,27,31)
QUALIFICATION_SCHEMA = 'core.qualification.v1'


def register_scope(family, scope_id, parameter_name, lower, upper, qualification_points):
    if family not in ('F1','F2','F3','F4','F5','F6') or not scope_id or not parameter_name:
        raise ValueError('explicit mechanism family, scope and parameter are required')
    points = new_scope_split(lower,upper)
    qualification_points = [float(x) for x in qualification_points]
    if not all(math.isfinite(x) for x in qualification_points):
        raise ValueError('finite qualification parameters required')
    for row in points:
        if any(math.isclose(row['parameter'],x,rel_tol=0,abs_tol=1e-12) for x in qualification_points):
            raise ValueError('production and qualification physical parameter collision; revise whole design')
        row.update(case_id=f'{scope_id}_DEV_{row["index"]:02d}',
                   family=family, scope_id=scope_id,
                   stage='production', qualification_only=False,
                   first_batch=row['index'] in FIRST_EIGHT)
    return {'schema':'core.production_design.v1','family':family,'scope_id':scope_id,
            'parameter_name':parameter_name,'parameter_range':[lower,upper],
            'qualification_parameters':qualification_points,'case_count':32,'cases':points,
            'first_batch_indices':list(FIRST_EIGHT),
            'qualification_status':'not_inferred_from_registration'}


def next_batch(design, qualification, audits):
    """Caller must load hash-verified receipts; no file-existence completion rule."""
    qualification_schema = qualification.get('schema')
    if type(qualification_schema) is not str or qualification_schema != QUALIFICATION_SCHEMA:
        raise ValueError('qualification schema mismatch')
    if qualification.get('scope_id') != design['scope_id'] or qualification.get('family') != design['family']:
        raise ValueError('qualification is for another scope or mechanism')
    if not qualification.get('T1_numerical') or not qualification.get('matrix_complete'):
        return {'status':'awaiting_T1','ready':[], 'failed':[], 'missing':[]}
    cases={r['case_id']:r for r in design['cases']}
    if len(cases)!=32 or set(audits)-set(cases):
        raise ValueError('registration altered or audit outside preregistered denominator')
    failed=[]
    for key, receipt in audits.items():
        if receipt.get('case_id')!=key or receipt.get('schema')!='core.case_audit.v1':
            raise ValueError('audit identity/schema mismatch')
        if not all(receipt.get(field) is True for field in ('hard_integrity_pass','full_temporal_scan','full_particle_axis')):
            failed.append(key)
    missing=[key for key in cases if key not in audits]
    if failed:
        return {'status':'scope_review_required','ready':[], 'failed':failed,'missing':missing}
    first=[key for key,row in cases.items() if row['first_batch']]
    pending_first=[key for key in first if key not in audits]
    return {'status':'first_8' if pending_first else 'remaining_24' if missing else 'complete_32',
            'ready':pending_first or missing,'failed':[],'missing':missing,
            'registered_denominator':32,'passed_count':len(audits)}
