import importlib.util
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial import cKDTree

source = Path(__file__).with_name('immutable-source-worker-v2.py')
spec = importlib.util.spec_from_file_location('f2_source_worker_v2', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_root = module.receipt_output_root
original_audit = module.audit


def prepared_root(receipt_path, receipt):
    root = original_root(receipt_path, receipt)
    prepared = root / 'prepared'
    report = prepared / 'prepared-input-report.json'
    if report.is_file():
        metadata = json.loads(report.read_text())
        prefix = Path(metadata['prefix'])
        assert prefix.parent == prepared
        assert prefix.with_suffix('.xml').is_file()
        assert prefix.with_suffix('.bi4').is_file()
        return prepared
    return root


def audit(args):
    original_output = args.output
    base_output = str(Path(original_output).with_name('source-v2-initial-summary.json'))
    args.output = base_output
    report = original_audit(args)
    args.output = original_output
    assert report['status'] == 'pass', report['checks']
    csv_path = Path(report['csv_summary']['csv']['path'])
    with csv_path.open() as stream:
        columns = stream.readline().strip().split(',')
    values = np.loadtxt(csv_path, delimiter=',', skiprows=1)
    assert values.ndim == 2 and values.shape[1] == len(columns)
    def field(name):
        return values[:, columns.index(name)]
    positions = np.column_stack([field('Pos.' + axis + ' [m]') for axis in 'xyz'])
    velocities = np.column_stack([field('Vel.' + axis + ' [m/s]') for axis in 'xyz'])
    uids = field('Idp')
    types = field('Type')
    marks = field('Mk')
    mass = field('Mass [kg]')
    density = field('Rhop [kg/m^3]')
    xml_path = Path(report['actual_xml_contract']['path'])
    xml = ET.parse(xml_path).getroot()
    particles = xml.find('./execution/particles')
    total = int(particles.attrib['np'])
    expected_type = np.full(total, -1, dtype=np.int8)
    expected_mk = np.full(total, -1, dtype=np.int16)
    for kind, code in [('fixed', 0), ('moving', 1), ('floating', 2), ('fluid', 3)]:
        for node in particles.findall(kind):
            begin, count, mark = [int(node.attrib[key]) for key in ['begin', 'count', 'mk']]
            expected_type[begin:begin + count] = code
            expected_mk[begin:begin + count] = mark
    order = np.argsort(uids)
    dp = float(xml.find('./execution/constants/dp').attrib['value'])
    maximum_coordinate = max(float(np.max(np.abs(positions))), dp)
    float32_ulp = 2 ** (math.floor(math.log2(maximum_coordinate)) - 23)
    tolerance = 2 * math.sqrt(3) * float32_ulp + 1e-8
    assert tolerance < 0.001 * dp
    fluid = types == 3
    clearances = {}
    for name, solid in [('fixed', types == 0), ('moving', types == 1)]:
        if solid.any():
            distance, _ = cKDTree(positions[solid]).query(positions[fluid], k=1, workers=1)
            clearances[name] = {'minimum_center_distance_m': float(distance.min()),
                                'minimum_center_distance_dp': float(distance.min() / dp),
                                'below_one_dp_after_representation_tolerance': int(np.count_nonzero(distance < dp - tolerance))}
    checks = {
        'all_native_fields_finite': bool(np.isfinite(values).all()),
        'uid_axis_exact_complete_unique': bool(len(uids) == total and np.array_equal(uids[order], np.arange(total))),
        'type_mk_partition_exact_by_uid': bool(np.array_equal(types[order], expected_type) and np.array_equal(marks[order], expected_mk)),
        'positive_native_mass_and_density': bool((mass > 0).all() and (density > 0).all()),
        'initial_velocity_zero': bool(np.max(np.abs(velocities)) <= 1e-7),
        'true3d_fluid_extent': bool((np.ptp(positions[fluid], axis=0) > dp).all()),
        'all_coordinate_centers_unique': bool(len(np.unique(positions, axis=0)) == total),
        'fluid_fixed_moving_clearance_one_dp_with_disclosed_float32_tolerance': all(c['below_one_dp_after_representation_tolerance'] == 0 for c in clearances.values()),
        'actual_csv_total_and_fluid_counts': bool(len(uids) == total and fluid.sum() == report['gencase_receipt']['dynamic_counts']['fluid_particles']),
    }
    report['additional_actual_native_integrity'] = {
        'checks': checks, 'csv_sha256': module.sha256(csv_path),
        'global_fluid_solid_center_clearances': clearances,
        'representation_precision': {'native_coordinate_dtype': 'float32', 'csv_coordinate_float32_ulp_m': float32_ulp,
                                     'clearance_tolerance_m': tolerance, 'nominal_required_clearance_dp': 1.0,
                                     'native_geometry_or_mass_changed': False},
        'fluid_native_mass_kg': float(mass[fluid].sum()), 'fluid_particles': int(fluid.sum()),
        'continuum_mass_policy': 'Report separately from source geometry; no native weight rescale.',
        'physical_initial_state_changed': False,
    }
    report['checks'].update(checks)
    report['status'] = 'pass' if all(report['checks'].values()) else 'fail'
    Path(original_output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'case_id': args.case_id, 'status': report['status'], 'actual_integrity': checks}), flush=True)
    return report


module.receipt_output_root = prepared_root
module.audit = audit
raise SystemExit(module.main())
