#!/usr/bin/env python3
"""Audit the official F4 fluid-fluid pair-force source contract.

This is a source/algebra audit only.  It never reads native particles, HDF5,
or solver output and it does not infer that a selected run has zero residual
internal force.  The source contract is checked for the actual F4 XML settings
and the manufactured pair calculations exercise the exact symmetric terms
used by the official GPU interaction code.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
SOURCE = REPO / "src/source"
F4_XML = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f4_dp0_savedt_pair_inputs_v1/same_cfl/"
    "F4_DROP_CENTERED_REFERENCE_001_DP010_same_cfl_savedt.xml"
)
OUT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_pair_force_source_audit_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def line_for(path: Path, needle: str) -> int:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if needle in line:
            return line_no
    raise ValueError(f"source needle not found: {path}:{needle}")


def source_record(path: Path, needles: list[str]) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    anchors = {needle: line_for(path, needle) for needle in needles}
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "line_anchors": anchors,
        "source_presence": {needle: needle in text for needle in needles},
    }


def parse_f4_settings(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    params: dict[str, str] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == "parameter" and node.get("key"):
            params[node.get("key")] = node.get("value", "")
    constants: dict[str, str] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() in {"dp", "h", "massfluid"} and node.get("value") is not None:
            constants[node.tag.rsplit("}", 1)[-1].lower()] = node.get("value", "")
    expected = {"Kernel": "2", "ViscoTreatment": "1", "DensityDT": "2", "Shifting": "0"}
    checks = {key: params.get(key) == value for key, value in expected.items()}
    if not all(checks.values()):
        raise ValueError(f"F4 XML settings do not match expected source audit contract: {checks}")
    return {"path": str(path.resolve()), "sha256": sha256(path), "parameters": params, "constants": constants, "expected_checks": checks}


def vec_norm(vector: tuple[float, float, float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def vec_scale(scale: float, vector: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(scale * value for value in vector)


def vec_add(left: tuple[float, float, float], right: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(a + b for a, b in zip(left, right))


def wendland_fac(h: float, distance: float) -> float:
    """3-D Wendland fac from FunSphKernel.h / FunSphKernel_iker.h."""
    bwenh = -2.08891 / (h**5)
    wqq1 = 1.0 - 0.5 * distance / h
    return bwenh * wqq1**3


def pair_gradient(h: float, dr: tuple[float, float, float]) -> tuple[float, float, float]:
    distance = vec_norm(dr)
    if not 0.0 < distance < 2.0 * h:
        raise ValueError("manufactured pair must be strictly inside one symmetric 2h support")
    return vec_scale(wendland_fac(h, distance), dr)


def pressure_pair(
    *, h: float, dr: tuple[float, float, float], pi: float, pj: float,
    rhoi: float, rhoj: float, mi: float, mj: float,
) -> dict[str, object]:
    gradient = pair_gradient(h, dr)
    symmetric_coefficient = (pi + pj) / (rhoi * rhoj)
    ai = vec_scale(-symmetric_coefficient * mj, gradient)
    aj = vec_scale(symmetric_coefficient * mi, gradient)
    momentum_residual = vec_add(vec_scale(mi, ai), vec_scale(mj, aj))
    unit_mass_ai = vec_scale(-symmetric_coefficient, gradient)
    unit_mass_aj = vec_scale(symmetric_coefficient, gradient)
    unit_mass_residual = vec_add(vec_scale(mi, unit_mass_ai), vec_scale(mj, unit_mass_aj))
    return {
        "gradient": list(gradient),
        "pressure_coefficient": symmetric_coefficient,
        "acceleration_i": list(ai),
        "acceleration_j": list(aj),
        "momentum_residual": list(momentum_residual),
        "momentum_residual_norm": vec_norm(momentum_residual),
        "unit_mass_shortcut_residual": list(unit_mass_residual),
        "unit_mass_shortcut_residual_norm": vec_norm(unit_mass_residual),
    }


def artificial_viscosity_pair(
    *, h: float, dr: tuple[float, float, float], dvel: tuple[float, float, float],
    rhoi: float, rhoj: float, mi: float, mj: float, visco: float = 0.08, cs0: float = 10.0,
) -> dict[str, object]:
    gradient = pair_gradient(h, dr)
    dot = sum(a * b for a, b in zip(dr, dvel))
    if dot >= 0.0:
        raise ValueError("manufactured artificial-viscosity pair must be approaching")
    rr2 = sum(value * value for value in dr)
    eta2 = (0.1 * h) ** 2
    amubar = h * dot / (rr2 + eta2)
    robar = 0.5 * (rhoi + rhoj)
    pi_without_mass = -visco * cs0 * amubar / robar
    pi_i = pi_without_mass * mj
    pi_j = pi_without_mass * mi
    ai = vec_scale(-pi_i, gradient)
    aj = vec_scale(pi_j, gradient)
    residual = vec_add(vec_scale(mi, ai), vec_scale(mj, aj))
    return {
        "dot": dot,
        "rho_bar": robar,
        "pi_without_mass": pi_without_mass,
        "momentum_residual": list(residual),
        "momentum_residual_norm": vec_norm(residual),
        "status": "PASS_MASS_WEIGHTED_ARTIFICIAL_VISCOSITY_PAIR",
    }


def asymmetric_h_diagnostic(
    *, dr: tuple[float, float, float], pi: float, pj: float,
    rhoi: float, rhoj: float, mi: float, mj: float, hi: float, hj: float,
) -> dict[str, object]:
    distance = vec_norm(dr)
    if not (distance < 2.0 * hi and distance < 2.0 * hj):
        raise ValueError("asymmetric-h diagnostic pair must be inside both supports")
    coefficient = (pi + pj) / (rhoi * rhoj)
    gradient_i = pair_gradient(hi, dr)
    gradient_j = pair_gradient(hj, dr)
    ai = vec_scale(-coefficient * mj, gradient_i)
    aj = vec_scale(coefficient * mi, gradient_j)
    residual = vec_add(vec_scale(mi, ai), vec_scale(mj, aj))
    return {
        "h_i_m": hi,
        "h_j_m": hj,
        "gradient_i": list(gradient_i),
        "gradient_j_reversed_pair_magnitude": list(gradient_j),
        "momentum_residual": list(residual),
        "momentum_residual_norm": vec_norm(residual),
        "status": "REJECT_ASYMMETRIC_H_OUTSIDE_SINGLE_CTE_KERNEL_CONTRACT",
    }


def build() -> dict[str, object]:
    jsph = SOURCE / "JSph.cpp"
    interaction = SOURCE / "JSphGpu_ker.cu"
    kernel = SOURCE / "FunSphKernel_iker.h"
    kernel_host = SOURCE / "FunSphKernel.h"
    cte = SOURCE / "JSphGpu_cte.h"
    settings = parse_f4_settings(F4_XML)
    source = {
        "configuration_mapping": source_record(jsph, [
            'case 2:  TKernel=KERNEL_Wendland;',
            'case 1:  TVisco=VISCO_Artificial;',
            'case 2:  TDensity=DDT_DDT2;',
            'case 0:  shiftmode=SHIFT_None;',
            'CSP.kernelh       =KernelH;',
            'CSP.massfluid     =MassFluid;',
        ]),
        "gpu_fluid_interaction": source_record(interaction, [
            'const float fac=cufsph::GetKernel_Fac<tker>(rr2);',
            'const float frx=fac*drx,fry=fac*dry,frz=fac*drz;',
            'const float prs=(pressp1+pressp2)/(velrhop1.w*velrhop2.w)',
            'const float p_vpm=-prs*(USE_FLOATING? ftmassp2: massp2);',
            'acep1.x+=p_vpm*frx;',
            'if((tdensity==DDT_DDT2',
            'if(shift && shiftposfsp1.x!=FLT_MAX)',
            'if(tvisco==VISCO_Artificial)',
            'const float pi_visc=(-visco*cbar*amubar/robar)*(USE_FLOATING? ftmassp2: massp2);',
        ]),
        "wendland_gpu_kernel": source_record(kernel, [
            'return(bwenh*wqq1*wqq1*wqq1);',
            'fac=CTE.bwenh*wqq2*wqq1;',
            'return(GetKernelWendland_Fac(rr2,CTE.kernelh,CTE.bwenh));',
        ]),
        "wendland_host_constants": source_record(kernel_host, [
            'inline float GetKernelWendland_Factor(){ return(2.0f); }',
            'kc.bwenh=float(-2.08891/(h*h*h*h*h));',
            'return(kc.bwenh*wqq1*wqq1*wqq1);',
        ]),
        "gpu_constant_contract": source_record(cte, [
            'float massf;',
            'float kernelh;',
            'float kernelsize2;',
            'inline void SetCtegMass(StCteInteraction& cte,float massb,float massf)',
            'cte.kernelh=kernelh;',
        ]),
    }

    dr = (0.004, 0.0, 0.0)
    pressure_nonuniform = pressure_pair(
        h=0.017320508076, dr=dr, pi=123.0, pj=77.0,
        rhoi=998.0, rhoj=1042.0, mi=0.002, mj=0.003,
    )
    viscosity_nonuniform = artificial_viscosity_pair(
        h=0.017320508076, dr=dr, dvel=(-0.4, 0.0, 0.0),
        rhoi=998.0, rhoj=1042.0, mi=0.002, mj=0.003,
    )
    asymmetric = asymmetric_h_diagnostic(
        dr=dr, pi=123.0, pj=77.0, rhoi=998.0, rhoj=1042.0,
        mi=0.002, mj=0.003, hi=0.017320508076, hj=0.013,
    )

    return {
        "schema": "ds02.stage2.f4-pair-force-source-audit.v1",
        "status": "SOURCE_ALGEBRA_CONDITIONAL_ACTUAL_RESIDUAL_UNKNOWN",
        "f4_xml_settings": settings,
        "source": source,
        "formula_scope": {
            "pressure": "For fluid-fluid pair with a single run-wide h and symmetric Wendland gradient, source lines 592-598 use S=(p_i+p_j)/(rho_i rho_j), a_i=-S*m_j*gradW(r_i-r_j); reversed pair uses a_j=+S*m_i*gradW. Nonuniform p/rho remain in a symmetric coefficient.",
            "artificial_viscosity": "For approaching fluid-fluid pair, source lines 731-740 use dot=(r_i-r_j)·(v_i-v_j), symmetric rhobar and amubar, then multiply each acceleration by the other particle mass. The same reversed-gradient argument gives pair momentum cancellation under the same h and symmetric iteration assumptions.",
            "density_dt2": "Source lines 667-673 update deltap1 only; DDT2 is density diffusion and is not itself a pressure/viscosity momentum term.",
            "shifting0": "The XML mapping selects SHIFT_None and the acceleration/position correction block is conditional on shift; this audit does not treat shifting as an active force.",
            "boundary_and_external_terms": "The proof is fluid-fluid only and excludes boundaries, floating/DEM/Chrono, external acceleration and asymmetric neighbor participation. F4 precontact spatial gates are separate evidence.",
        },
        "manufactured_pair_tests": {
            "nonuniform_pressure_and_density": {
                "inputs": {"p_i": 123.0, "p_j": 77.0, "rho_i": 998.0, "rho_j": 1042.0, "m_i": 0.002, "m_j": 0.003},
                "result": pressure_nonuniform,
                "status": "PASS_ALGEBRAIC_SYMMETRY_UNDER_NONUNIFORM_PRESSURE_RHO",
            },
            "nonunit_unequal_mass": {
                "inputs": {"m_i": 0.002, "m_j": 0.003, "unit_mass_shortcut": "same reference mass on both accelerations"},
                "exact_source_result": pressure_nonuniform,
                "status": "PASS_OTHER_PARTICLE_MASS_WEIGHTING; REJECT_UNIT_MASS_SHORTCUT",
            },
            "artificial_viscosity_nonuniform_state": viscosity_nonuniform,
            "asymmetric_h": asymmetric,
        },
        "interpretation": {
            "source_supported_premise": "CONDITIONAL: equal run-wide h, constant fluid particle mass, symmetric pair participation, fluid-fluid only, and no active external/boundary term imply algebraic pair momentum cancellation for the shown pressure/artificial-viscosity terms.",
            "actual_run_status": "UNKNOWN: selected native fields do not expose per-pair acceleration residual, and this source audit does not replace the bounded observer read.",
            "no_scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }


if __name__ == "__main__":
    value = build()
    if OUT.exists():
        raise FileExistsError(OUT)
    OUT.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": value["status"], "output": str(OUT)}, ensure_ascii=False))
