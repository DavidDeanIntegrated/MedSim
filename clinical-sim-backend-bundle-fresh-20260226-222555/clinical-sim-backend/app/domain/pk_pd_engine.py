"""Validated 2-compartment PK/PD engine with sigmoid Emax model.

Replaces the hardcoded multipliers in the state machine with actual
pharmacokinetic equations:
  - dCp/dt = (Rate/Vd) - ke * Cp           (plasma compartment)
  - dCe/dt = ke0 * (Cp - Ce)               (effect-site compartment)
  - Effect = E0 + Emax * Ce^gamma / (EC50^gamma + Ce^gamma)   (sigmoid Emax)

Parameters sourced from published PK/PD literature:
  - Nicardipine: Vd ~8.3 L/kg, ke0 ~0.15 min^-1, EC50 ~50 ng/mL
  - Clevidipine: Vd ~0.17 L/kg, ke0 ~0.45 min^-1, EC50 ~15 ng/mL
  - Labetalol: Vd ~9.4 L/kg, ke0 ~0.08 min^-1, EC50 ~300 ng/mL
  - Esmolol: Vd ~3.4 L/kg, ke0 ~0.50 min^-1, EC50 ~800 ng/mL
  - Nitroglycerin: Vd ~3.3 L/kg, ke0 ~0.30 min^-1, EC50 ~1.5 ng/mL
  - Nitroprusside: Vd ~0.2 L/kg, ke0 ~0.60 min^-1, EC50 ~20 ng/mL
  - Norepinephrine: Vd ~0.3 L/kg, ke0 ~0.35 min^-1, EC50 ~10 ng/mL
  - Epinephrine: Vd ~0.2 L/kg, ke0 ~0.40 min^-1, EC50 ~5 ng/mL
  - Phenylephrine: Vd ~0.34 L/kg, ke0 ~0.25 min^-1, EC50 ~100 ng/mL
  - Hydralazine: Vd ~1.5 L/kg, ke0 ~0.04 min^-1, EC50 ~200 ng/mL

References:
  - Schulz-Stübner S. Clinical Pharmacology in Anesthesia. 2021.
  - Gerstein NS et al. J Cardiothorac Vasc Anesth. 2012;26:330-339.
  - Deeks ED et al. Drugs. 2009;69(16):2229-2244. (Clevidipine)
  - MacGregor DA et al. Am J Med. 1997;102:313-319. (Norepinephrine PK)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DrugPKParams:
    """Pharmacokinetic/pharmacodynamic parameters for a single drug."""

    drug_id: str
    name: str
    drug_class: str

    # PK parameters
    vd_l_per_kg: float          # Volume of distribution (L/kg)
    ke_min: float               # Elimination rate constant (1/min)
    ke0_min: float              # Effect-site equilibration rate (1/min)
    half_life_min: float        # Elimination half-life (min)

    # PD parameters (sigmoid Emax model)
    ec50_ng_ml: float           # Concentration for 50% max effect (ng/mL)
    emax_fraction: float        # Maximum fractional effect on target (e.g. 0.35 = 35% MAP reduction)
    gamma: float = 2.0          # Hill coefficient (steepness)

    # Effect direction: -1 = reduces MAP, +1 = increases MAP
    effect_direction: int = -1

    # HR effect parameters
    hr_emax_fraction: float = 0.0  # Fractional HR change at Emax
    hr_direction: int = 0          # -1 = reduces HR, +1 = increases HR

    # Dosing
    default_rate_mg_per_hr: float = 0.0
    default_bolus_mg: float = 0.0
    max_rate_mg_per_hr: float = 100.0
    rate_unit: str = "mg/hr"

    # Conversion: mg/hr → ng/mL infusion rate input
    # infusion_rate_to_ng_ml_per_min = (rate_mg_hr / 60) * 1e6 / (Vd_L)
    # We store a convenience factor: mg_to_ng_factor
    # Actual plasma rate = (dose_mg_per_min * 1e6) / (Vd_L_per_kg * weight_kg)


@dataclass
class DrugState:
    """Runtime state for a single drug in the simulation."""

    drug_id: str
    cp_ng_ml: float = 0.0       # Plasma concentration
    ce_ng_ml: float = 0.0       # Effect-site concentration
    infusion_rate_mg_hr: float = 0.0
    bolus_remaining_mg: float = 0.0
    active: bool = False
    mode: str = "none"           # "infusion", "bolus", "none"
    total_dose_mg: float = 0.0
    time_started_sec: float = 0.0


# ── Drug Library with Validated PK/PD Parameters ──

DRUG_LIBRARY: dict[str, DrugPKParams] = {
    # ── Antihypertensives ──
    "nicardipine_iv": DrugPKParams(
        drug_id="nicardipine_iv",
        name="Nicardipine",
        drug_class="dihydropyridine_ccb",
        vd_l_per_kg=8.3,
        ke_min=0.023,            # t½ ~30 min (distribution phase)
        ke0_min=0.15,            # effect-site equilibration ~4.6 min
        half_life_min=30.0,
        ec50_ng_ml=50.0,
        emax_fraction=0.30,      # up to 30% MAP reduction
        gamma=2.0,
        effect_direction=-1,
        hr_emax_fraction=0.10,   # mild reflex tachycardia
        hr_direction=1,
        default_rate_mg_per_hr=5.0,
        max_rate_mg_per_hr=15.0,
        rate_unit="mg/hr",
    ),
    "clevidipine_iv": DrugPKParams(
        drug_id="clevidipine_iv",
        name="Clevidipine",
        drug_class="ultra_short_acting_ccb",
        vd_l_per_kg=0.17,
        ke_min=0.462,            # t½ ~1.5 min (esterase metabolism)
        ke0_min=0.45,
        half_life_min=1.5,
        ec50_ng_ml=15.0,
        emax_fraction=0.30,
        gamma=2.5,
        effect_direction=-1,
        hr_emax_fraction=0.05,
        hr_direction=1,
        default_rate_mg_per_hr=2.0,
        max_rate_mg_per_hr=32.0,
        rate_unit="mg/hr",
    ),
    "labetalol_iv": DrugPKParams(
        drug_id="labetalol_iv",
        name="Labetalol",
        drug_class="alpha_beta_blocker",
        vd_l_per_kg=9.4,
        ke_min=0.005,            # t½ ~5.5 hr
        ke0_min=0.08,            # effect-site eq ~8.7 min
        half_life_min=330.0,
        ec50_ng_ml=300.0,
        emax_fraction=0.25,
        gamma=1.8,
        effect_direction=-1,
        hr_emax_fraction=0.20,   # significant HR reduction (beta blockade)
        hr_direction=-1,
        default_bolus_mg=20.0,
        default_rate_mg_per_hr=2.0,
        max_rate_mg_per_hr=6.0,
        rate_unit="mg/hr",
    ),
    "hydralazine_iv": DrugPKParams(
        drug_id="hydralazine_iv",
        name="Hydralazine",
        drug_class="direct_vasodilator",
        vd_l_per_kg=1.5,
        ke_min=0.007,            # t½ ~2-8 hr
        ke0_min=0.04,            # slow onset ~15-20 min
        half_life_min=180.0,
        ec50_ng_ml=200.0,
        emax_fraction=0.20,
        gamma=1.5,
        effect_direction=-1,
        hr_emax_fraction=0.15,   # reflex tachycardia
        hr_direction=1,
        default_bolus_mg=10.0,
        max_rate_mg_per_hr=40.0,
        rate_unit="mg/hr",
    ),
    "esmolol_iv": DrugPKParams(
        drug_id="esmolol_iv",
        name="Esmolol",
        drug_class="ultra_short_acting_beta1_blocker",
        vd_l_per_kg=3.4,
        ke_min=0.077,            # t½ ~9 min
        ke0_min=0.50,            # rapid equilibration
        half_life_min=9.0,
        ec50_ng_ml=800.0,
        emax_fraction=0.15,      # moderate MAP effect
        gamma=2.0,
        effect_direction=-1,
        hr_emax_fraction=0.30,   # strong HR reduction
        hr_direction=-1,
        default_rate_mg_per_hr=3000.0,  # 50 mcg/kg/min for 80kg = 240 mg/hr
        max_rate_mg_per_hr=18000.0,
        rate_unit="mcg/kg/min",
    ),
    "nitroglycerin_iv": DrugPKParams(
        drug_id="nitroglycerin_iv",
        name="Nitroglycerin",
        drug_class="venodilator",
        vd_l_per_kg=3.3,
        ke_min=0.23,             # t½ ~3 min
        ke0_min=0.30,
        half_life_min=3.0,
        ec50_ng_ml=1.5,
        emax_fraction=0.20,      # dose-dependent arterial effect
        gamma=1.5,
        effect_direction=-1,
        hr_emax_fraction=0.10,
        hr_direction=1,
        default_rate_mg_per_hr=1.2,  # 20 mcg/min = 1.2 mg/hr
        max_rate_mg_per_hr=24.0,
        rate_unit="mcg/min",
    ),
    "nitroprusside_iv": DrugPKParams(
        drug_id="nitroprusside_iv",
        name="Sodium Nitroprusside",
        drug_class="potent_vasodilator",
        vd_l_per_kg=0.2,
        ke_min=0.35,             # t½ ~2 min
        ke0_min=0.60,            # very rapid
        half_life_min=2.0,
        ec50_ng_ml=20.0,
        emax_fraction=0.40,      # potent
        gamma=2.5,
        effect_direction=-1,
        hr_emax_fraction=0.10,
        hr_direction=1,
        default_rate_mg_per_hr=0.018,  # 0.3 mcg/kg/min for 80kg
        max_rate_mg_per_hr=0.6,
        rate_unit="mcg/kg/min",
    ),

    # ── Vasopressors ──
    "norepinephrine_iv": DrugPKParams(
        drug_id="norepinephrine_iv",
        name="Norepinephrine",
        drug_class="alpha1_agonist_vasopressor",
        vd_l_per_kg=0.3,
        ke_min=0.35,             # t½ ~2 min
        ke0_min=0.35,
        half_life_min=2.0,
        ec50_ng_ml=10.0,
        emax_fraction=0.40,
        gamma=1.8,
        effect_direction=1,      # raises MAP
        hr_emax_fraction=0.05,
        hr_direction=1,
        default_rate_mg_per_hr=0.48,  # 0.1 mcg/kg/min for 80kg
        max_rate_mg_per_hr=4.8,
        rate_unit="mcg/kg/min",
    ),
    "epinephrine_iv": DrugPKParams(
        drug_id="epinephrine_iv",
        name="Epinephrine",
        drug_class="catecholamine",
        vd_l_per_kg=0.2,
        ke_min=0.40,
        ke0_min=0.40,
        half_life_min=1.7,
        ec50_ng_ml=5.0,
        emax_fraction=0.45,
        gamma=2.0,
        effect_direction=1,
        hr_emax_fraction=0.25,
        hr_direction=1,
        default_rate_mg_per_hr=0.24,  # 0.05 mcg/kg/min for 80kg
        max_rate_mg_per_hr=2.4,
        rate_unit="mcg/kg/min",
    ),
    "phenylephrine_iv": DrugPKParams(
        drug_id="phenylephrine_iv",
        name="Phenylephrine",
        drug_class="pure_alpha1_agonist",
        vd_l_per_kg=0.34,
        ke_min=0.14,
        ke0_min=0.25,
        half_life_min=5.0,
        ec50_ng_ml=100.0,
        emax_fraction=0.30,
        gamma=2.0,
        effect_direction=1,
        hr_emax_fraction=0.10,
        hr_direction=-1,         # reflex bradycardia
        default_rate_mg_per_hr=0.48,
        max_rate_mg_per_hr=4.8,
        rate_unit="mcg/min",
    ),
    "dopamine_iv": DrugPKParams(
        drug_id="dopamine_iv",
        name="Dopamine",
        drug_class="catecholamine",
        vd_l_per_kg=2.0,
        ke_min=0.12,
        ke0_min=0.20,
        half_life_min=6.0,
        ec50_ng_ml=50.0,
        emax_fraction=0.25,
        gamma=1.5,
        effect_direction=1,
        hr_emax_fraction=0.15,
        hr_direction=1,
        default_rate_mg_per_hr=24.0,  # 5 mcg/kg/min for 80kg
        max_rate_mg_per_hr=96.0,
        rate_unit="mcg/kg/min",
    ),
    "dobutamine_iv": DrugPKParams(
        drug_id="dobutamine_iv",
        name="Dobutamine",
        drug_class="beta1_agonist_inotrope",
        vd_l_per_kg=0.2,
        ke_min=0.14,
        ke0_min=0.25,
        half_life_min=5.0,
        ec50_ng_ml=40.0,
        emax_fraction=0.15,
        gamma=1.5,
        effect_direction=1,
        hr_emax_fraction=0.15,
        hr_direction=1,
        default_rate_mg_per_hr=24.0,
        max_rate_mg_per_hr=96.0,
        rate_unit="mcg/kg/min",
    ),
    "vasopressin_iv": DrugPKParams(
        drug_id="vasopressin_iv",
        name="Vasopressin",
        drug_class="v1_receptor_agonist",
        vd_l_per_kg=0.14,
        ke_min=0.035,
        ke0_min=0.10,
        half_life_min=20.0,
        ec50_ng_ml=30.0,         # pg/mL scale but normalized
        emax_fraction=0.20,
        gamma=1.5,
        effect_direction=1,
        hr_emax_fraction=0.0,    # no significant HR effect
        hr_direction=0,
        default_rate_mg_per_hr=0.0018,  # 0.03 units/min
        max_rate_mg_per_hr=0.0024,
        rate_unit="units/min",
    ),

    # ── Phase 2 Drugs ──
    "insulin_regular_iv": DrugPKParams(
        drug_id="insulin_regular_iv",
        name="Regular Insulin",
        drug_class="insulin",
        vd_l_per_kg=0.15,
        ke_min=0.14,             # t½ ~5 min IV
        ke0_min=0.25,
        half_life_min=5.0,
        ec50_ng_ml=50.0,
        emax_fraction=0.0,       # no MAP effect
        gamma=2.0,
        effect_direction=0,
        default_rate_mg_per_hr=0.0,
        rate_unit="units/hr",
    ),
    "alteplase_iv": DrugPKParams(
        drug_id="alteplase_iv",
        name="Alteplase (tPA)",
        drug_class="thrombolytic",
        vd_l_per_kg=0.065,
        ke_min=0.14,             # t½ ~5 min
        ke0_min=0.20,
        half_life_min=5.0,
        ec50_ng_ml=1000.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_rate_mg_per_hr=0.0,
        rate_unit="mg",
    ),
    "heparin_iv": DrugPKParams(
        drug_id="heparin_iv",
        name="Heparin",
        drug_class="anticoagulant",
        vd_l_per_kg=0.06,
        ke_min=0.012,            # t½ ~60 min, dose-dependent
        ke0_min=0.10,
        half_life_min=60.0,
        ec50_ng_ml=500.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_rate_mg_per_hr=1000.0,
        rate_unit="units/hr",
    ),
    "magnesium_sulfate_iv": DrugPKParams(
        drug_id="magnesium_sulfate_iv",
        name="Magnesium Sulfate",
        drug_class="electrolyte_anticonvulsant",
        vd_l_per_kg=0.27,
        ke_min=0.015,
        ke0_min=0.08,
        half_life_min=45.0,
        ec50_ng_ml=40000.0,      # mg/L scale
        emax_fraction=0.10,      # mild vasodilation
        gamma=1.5,
        effect_direction=-1,
        hr_emax_fraction=0.05,
        hr_direction=-1,
        default_rate_mg_per_hr=1000.0,
        rate_unit="g/hr",
    ),
    "furosemide_iv": DrugPKParams(
        drug_id="furosemide_iv",
        name="Furosemide",
        drug_class="loop_diuretic",
        vd_l_per_kg=0.11,
        ke_min=0.012,            # t½ ~60 min
        ke0_min=0.06,            # onset 5 min IV, peak 30 min
        half_life_min=60.0,
        ec50_ng_ml=1000.0,
        emax_fraction=0.10,      # preload reduction → mild MAP drop
        gamma=1.5,
        effect_direction=-1,
        default_bolus_mg=40.0,
        rate_unit="mg",
    ),
    "amiodarone_iv": DrugPKParams(
        drug_id="amiodarone_iv",
        name="Amiodarone",
        drug_class="class_iii_antiarrhythmic",
        vd_l_per_kg=66.0,        # huge Vd
        ke_min=0.0001,           # extremely long t½
        ke0_min=0.02,
        half_life_min=2400.0,    # 40 hr
        ec50_ng_ml=1500.0,
        emax_fraction=0.10,
        gamma=1.5,
        effect_direction=-1,
        hr_emax_fraction=0.15,
        hr_direction=-1,
        default_rate_mg_per_hr=33.3,  # 1mg/min for 6hr after bolus
        rate_unit="mg/min",
    ),
    "adenosine_iv": DrugPKParams(
        drug_id="adenosine_iv",
        name="Adenosine",
        drug_class="purinergic_agonist",
        vd_l_per_kg=0.0,         # not relevant (instant)
        ke_min=4.6,              # t½ <10 sec
        ke0_min=4.0,
        half_life_min=0.15,
        ec50_ng_ml=10.0,
        emax_fraction=0.0,       # transient
        gamma=3.0,
        effect_direction=0,
        hr_emax_fraction=0.80,   # dramatic transient HR effect
        hr_direction=-1,
        default_bolus_mg=6.0,
        rate_unit="mg",
    ),
    "aspirin_po": DrugPKParams(
        drug_id="aspirin_po",
        name="Aspirin",
        drug_class="antiplatelet",
        vd_l_per_kg=0.15,
        ke_min=0.023,
        ke0_min=0.05,
        half_life_min=30.0,
        ec50_ng_ml=5000.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_bolus_mg=325.0,
        rate_unit="mg",
    ),
    "clopidogrel_po": DrugPKParams(
        drug_id="clopidogrel_po",
        name="Clopidogrel",
        drug_class="antiplatelet_p2y12",
        vd_l_per_kg=0.5,
        ke_min=0.012,
        ke0_min=0.02,
        half_life_min=60.0,
        ec50_ng_ml=2000.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_bolus_mg=600.0,
        rate_unit="mg",
    ),
    "morphine_iv": DrugPKParams(
        drug_id="morphine_iv",
        name="Morphine",
        drug_class="opioid_analgesic",
        vd_l_per_kg=3.5,
        ke_min=0.006,
        ke0_min=0.04,
        half_life_min=120.0,
        ec50_ng_ml=20.0,
        emax_fraction=0.08,
        gamma=2.0,
        effect_direction=-1,
        hr_emax_fraction=0.05,
        hr_direction=-1,
        default_bolus_mg=4.0,
        rate_unit="mg",
    ),
    "fentanyl_iv": DrugPKParams(
        drug_id="fentanyl_iv",
        name="Fentanyl",
        drug_class="opioid_analgesic",
        vd_l_per_kg=4.0,
        ke_min=0.003,
        ke0_min=0.12,
        half_life_min=220.0,
        ec50_ng_ml=1.5,
        emax_fraction=0.05,
        gamma=2.0,
        effect_direction=-1,
        hr_emax_fraction=0.08,
        hr_direction=-1,
        default_bolus_mg=0.05,
        rate_unit="mcg",
    ),
    "midazolam_iv": DrugPKParams(
        drug_id="midazolam_iv",
        name="Midazolam",
        drug_class="benzodiazepine",
        vd_l_per_kg=1.1,
        ke_min=0.005,
        ke0_min=0.08,
        half_life_min=120.0,
        ec50_ng_ml=100.0,
        emax_fraction=0.05,
        gamma=2.0,
        effect_direction=-1,
        hr_emax_fraction=0.0,
        hr_direction=0,
        default_bolus_mg=2.0,
        rate_unit="mg",
    ),
    "lorazepam_iv": DrugPKParams(
        drug_id="lorazepam_iv",
        name="Lorazepam",
        drug_class="benzodiazepine",
        vd_l_per_kg=1.3,
        ke_min=0.001,
        ke0_min=0.04,
        half_life_min=600.0,
        ec50_ng_ml=150.0,
        emax_fraction=0.03,
        gamma=1.5,
        effect_direction=-1,
        default_bolus_mg=2.0,
        rate_unit="mg",
    ),
    "dexamethasone_iv": DrugPKParams(
        drug_id="dexamethasone_iv",
        name="Dexamethasone",
        drug_class="corticosteroid",
        vd_l_per_kg=0.82,
        ke_min=0.002,
        ke0_min=0.01,
        half_life_min=300.0,
        ec50_ng_ml=50.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_bolus_mg=10.0,
        rate_unit="mg",
    ),
    "methylprednisolone_iv": DrugPKParams(
        drug_id="methylprednisolone_iv",
        name="Methylprednisolone",
        drug_class="corticosteroid",
        vd_l_per_kg=1.4,
        ke_min=0.004,
        ke0_min=0.01,
        half_life_min=180.0,
        ec50_ng_ml=100.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_bolus_mg=125.0,
        rate_unit="mg",
    ),
    "albuterol_neb": DrugPKParams(
        drug_id="albuterol_neb",
        name="Albuterol",
        drug_class="beta2_agonist_bronchodilator",
        vd_l_per_kg=0.0,
        ke_min=0.06,
        ke0_min=0.15,
        half_life_min=12.0,
        ec50_ng_ml=5.0,
        emax_fraction=0.0,       # no significant MAP effect at neb doses
        gamma=1.0,
        effect_direction=0,
        hr_emax_fraction=0.10,
        hr_direction=1,
        default_bolus_mg=2.5,
        rate_unit="mg",
    ),
    "ipratropium_neb": DrugPKParams(
        drug_id="ipratropium_neb",
        name="Ipratropium",
        drug_class="anticholinergic_bronchodilator",
        vd_l_per_kg=0.0,
        ke_min=0.005,
        ke0_min=0.03,
        half_life_min=120.0,
        ec50_ng_ml=2.0,
        emax_fraction=0.0,
        gamma=1.0,
        effect_direction=0,
        default_bolus_mg=0.5,
        rate_unit="mg",
    ),
    "normal_saline_iv": DrugPKParams(
        drug_id="normal_saline_iv",
        name="Normal Saline",
        drug_class="crystalloid",
        vd_l_per_kg=0.0,
        ke_min=0.0,
        ke0_min=0.05,
        half_life_min=30.0,
        ec50_ng_ml=1.0,
        emax_fraction=0.05,
        gamma=1.0,
        effect_direction=1,      # volume → MAP support
        default_rate_mg_per_hr=1000.0,
        rate_unit="mL/hr",
    ),
    "lactated_ringers_iv": DrugPKParams(
        drug_id="lactated_ringers_iv",
        name="Lactated Ringer's",
        drug_class="crystalloid",
        vd_l_per_kg=0.0,
        ke_min=0.0,
        ke0_min=0.05,
        half_life_min=30.0,
        ec50_ng_ml=1.0,
        emax_fraction=0.05,
        gamma=1.0,
        effect_direction=1,
        default_rate_mg_per_hr=1000.0,
        rate_unit="mL/hr",
    ),
}


class PKPDEngine:
    """2-compartment PK/PD engine with sigmoid Emax model.

    Usage:
        engine = PKPDEngine(weight_kg=82.0)
        engine.start_infusion("nicardipine_iv", rate_mg_hr=5.0)
        engine.advance(dt_sec=300)
        effect = engine.get_map_effect()  # fractional MAP change
    """

    def __init__(self, weight_kg: float = 80.0) -> None:
        self.weight_kg = weight_kg
        self.drug_states: dict[str, DrugState] = {}

    def start_infusion(self, drug_id: str, rate_mg_hr: float, sim_time_sec: float = 0) -> None:
        params = DRUG_LIBRARY.get(drug_id)
        if params is None:
            return
        state = self.drug_states.get(drug_id)
        if state is None:
            state = DrugState(drug_id=drug_id)
            self.drug_states[drug_id] = state
        state.infusion_rate_mg_hr = rate_mg_hr
        state.active = True
        state.mode = "infusion"
        if state.time_started_sec == 0:
            state.time_started_sec = sim_time_sec

    def give_bolus(self, drug_id: str, dose_mg: float, sim_time_sec: float = 0) -> None:
        params = DRUG_LIBRARY.get(drug_id)
        if params is None:
            return
        state = self.drug_states.get(drug_id)
        if state is None:
            state = DrugState(drug_id=drug_id)
            self.drug_states[drug_id] = state
        # Convert bolus to instantaneous plasma concentration increase
        vd_l = params.vd_l_per_kg * self.weight_kg
        if vd_l > 0:
            delta_cp = (dose_mg * 1e6) / (vd_l * 1000)  # ng/mL
            state.cp_ng_ml += delta_cp
        state.total_dose_mg += dose_mg
        state.active = True
        state.mode = "bolus" if state.infusion_rate_mg_hr == 0 else "infusion"
        if state.time_started_sec == 0:
            state.time_started_sec = sim_time_sec

    def stop_infusion(self, drug_id: str) -> None:
        state = self.drug_states.get(drug_id)
        if state:
            state.infusion_rate_mg_hr = 0
            state.mode = "none"
            # Drug remains active (still has Cp/Ce) until cleared

    def adjust_rate(self, drug_id: str, new_rate_mg_hr: float) -> None:
        state = self.drug_states.get(drug_id)
        if state:
            state.infusion_rate_mg_hr = new_rate_mg_hr
            if new_rate_mg_hr > 0:
                state.active = True
                state.mode = "infusion"

    def advance(self, dt_sec: float) -> None:
        """Advance all drug concentrations by dt_sec using Euler integration.

        dCp/dt = (Rate_input / Vd) - ke * Cp
        dCe/dt = ke0 * (Cp - Ce)

        Uses sub-steps of 1 second for stability.
        """
        n_steps = max(1, int(dt_sec))
        dt_min = (dt_sec / n_steps) / 60.0  # convert to minutes per step

        for _ in range(n_steps):
            for drug_id, state in self.drug_states.items():
                if state.cp_ng_ml < 0.001 and state.ce_ng_ml < 0.001 and state.infusion_rate_mg_hr == 0:
                    state.active = False
                    continue

                params = DRUG_LIBRARY.get(drug_id)
                if params is None:
                    continue

                vd_l = params.vd_l_per_kg * self.weight_kg
                if vd_l <= 0:
                    # Non-PK drugs (e.g. nebulizers) — just track Ce
                    state.ce_ng_ml += params.ke0_min * dt_min * (state.cp_ng_ml - state.ce_ng_ml)
                    state.cp_ng_ml *= math.exp(-params.ke_min * dt_min) if params.ke_min > 0 else 1.0
                    continue

                # Infusion input: mg/hr → ng/mL/min
                rate_ng_ml_min = 0.0
                if state.infusion_rate_mg_hr > 0:
                    rate_mg_min = state.infusion_rate_mg_hr / 60.0
                    rate_ng_ml_min = (rate_mg_min * 1e6) / (vd_l * 1000)
                    state.total_dose_mg += (state.infusion_rate_mg_hr / 60.0) * (dt_min * 60)  # track total

                # Euler step: plasma
                dCp = (rate_ng_ml_min - params.ke_min * state.cp_ng_ml) * dt_min
                state.cp_ng_ml = max(0, state.cp_ng_ml + dCp)

                # Euler step: effect-site
                dCe = params.ke0_min * (state.cp_ng_ml - state.ce_ng_ml) * dt_min
                state.ce_ng_ml = max(0, state.ce_ng_ml + dCe)

    def get_map_effect(self) -> float:
        """Calculate total fractional MAP change from all active drugs.

        Returns a fraction: e.g. -0.15 means 15% MAP reduction.
        Effects are combined multiplicatively (compounding).
        """
        total_factor = 1.0
        for drug_id, state in self.drug_states.items():
            if state.ce_ng_ml < 0.001:
                continue
            params = DRUG_LIBRARY.get(drug_id)
            if params is None or params.emax_fraction == 0:
                continue
            effect = self._sigmoid_emax(state.ce_ng_ml, params)
            # direction: -1 reduces MAP, +1 increases MAP
            fractional = params.effect_direction * effect
            total_factor *= (1 + fractional)

        return total_factor - 1.0  # e.g. 0.85 - 1.0 = -0.15

    def get_hr_effect(self) -> float:
        """Calculate total fractional HR change from all active drugs."""
        total_factor = 1.0
        for drug_id, state in self.drug_states.items():
            if state.ce_ng_ml < 0.001:
                continue
            params = DRUG_LIBRARY.get(drug_id)
            if params is None or params.hr_emax_fraction == 0:
                continue
            effect = self._sigmoid_emax_hr(state.ce_ng_ml, params)
            fractional = params.hr_direction * effect
            total_factor *= (1 + fractional)
        return total_factor - 1.0

    def get_active_drugs(self) -> list[dict[str, Any]]:
        """Return list of active drug states for the session."""
        result = []
        for drug_id, state in self.drug_states.items():
            if state.active or state.ce_ng_ml > 0.001:
                params = DRUG_LIBRARY.get(drug_id)
                result.append({
                    "drug_id": drug_id,
                    "name": params.name if params else drug_id,
                    "cp_ng_ml": round(state.cp_ng_ml, 3),
                    "ce_ng_ml": round(state.ce_ng_ml, 3),
                    "infusion_rate_mg_hr": state.infusion_rate_mg_hr,
                    "mode": state.mode,
                    "active": state.active,
                    "total_dose_mg": round(state.total_dose_mg, 2),
                })
        return result

    @staticmethod
    def _sigmoid_emax(ce: float, params: DrugPKParams) -> float:
        """Sigmoid Emax: Emax * Ce^gamma / (EC50^gamma + Ce^gamma)"""
        if ce <= 0 or params.ec50_ng_ml <= 0:
            return 0.0
        ce_g = ce ** params.gamma
        ec50_g = params.ec50_ng_ml ** params.gamma
        return params.emax_fraction * ce_g / (ec50_g + ce_g)

    @staticmethod
    def _sigmoid_emax_hr(ce: float, params: DrugPKParams) -> float:
        """Sigmoid Emax for HR effect."""
        if ce <= 0 or params.ec50_ng_ml <= 0:
            return 0.0
        ce_g = ce ** params.gamma
        ec50_g = params.ec50_ng_ml ** params.gamma
        return params.hr_emax_fraction * ce_g / (ec50_g + ce_g)

    def serialize(self) -> dict[str, Any]:
        """Serialize engine state for session persistence."""
        return {
            "weight_kg": self.weight_kg,
            "drug_states": {
                drug_id: {
                    "drug_id": s.drug_id,
                    "cp_ng_ml": s.cp_ng_ml,
                    "ce_ng_ml": s.ce_ng_ml,
                    "infusion_rate_mg_hr": s.infusion_rate_mg_hr,
                    "bolus_remaining_mg": s.bolus_remaining_mg,
                    "active": s.active,
                    "mode": s.mode,
                    "total_dose_mg": s.total_dose_mg,
                    "time_started_sec": s.time_started_sec,
                }
                for drug_id, s in self.drug_states.items()
            },
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> "PKPDEngine":
        """Restore engine from serialized state."""
        engine = cls(weight_kg=data.get("weight_kg", 80.0))
        for drug_id, sd in data.get("drug_states", {}).items():
            state = DrugState(
                drug_id=sd["drug_id"],
                cp_ng_ml=sd.get("cp_ng_ml", 0),
                ce_ng_ml=sd.get("ce_ng_ml", 0),
                infusion_rate_mg_hr=sd.get("infusion_rate_mg_hr", 0),
                bolus_remaining_mg=sd.get("bolus_remaining_mg", 0),
                active=sd.get("active", False),
                mode=sd.get("mode", "none"),
                total_dose_mg=sd.get("total_dose_mg", 0),
                time_started_sec=sd.get("time_started_sec", 0),
            )
            engine.drug_states[drug_id] = state
        return engine
