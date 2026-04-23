export interface MSDSDocument {
  id: number;
  title: string;
  cas_number: string;
  doc_type: 'pure' | 'mixture';
  status: 'generating' | 'completed' | 'failed';
  data: MSDSData | null;
  review_result: ReviewResult | null;
  company_info: CompanyInfo | null;
  created_at: string;
  updated_at?: string;
}

export interface MSDSData {
  document_info: DocumentInfo;
  part1_identification: Part1Identification;
  part2_hazard: Part2Hazard;
  part3_composition: Part3Composition;
  part4_first_aid: Part4FirstAid;
  part5_firefighting: Part5Firefighting;
  part6_spill: Part6Spill;
  part7_handling: Part7Handling;
  part8_exposure: Part8Exposure;
  part9_physical: Part9Physical;
  part10_stability: Part10Stability;
  part11_toxicology: Part11Toxicology;
  part12_ecology: Part12Ecology;
  part13_disposal: Part13Disposal;
  part14_transport: Part14Transport;
  part15_regulatory: Part15Regulatory;
  part16_other: Part16Other;
  [key: string]: any;
}

export interface DocumentInfo {
  sds_number: string;
  version: string;
  revision_date: string;
  data_source: string;
  completeness: string;
}

export interface Part1Identification {
  product_name_cn: string;
  product_name_en: string;
  cas_number: string;
  molecular_formula: string;
  molecular_weight: string;
  iupac_name: string;
  un_number: string;
  company_name: string;
  company_address: string;
  company_emergency: string;
  recommended_use: string;
  restricted_use: string;
}

export interface Part2Hazard {
  emergency_overview: string;
  ghs_classifications: string[];
  pictograms: string[];
  signal_word: string;
  hazard_codes: string[];
  hazard_codes_full: string[];
  precautionary_statements: {
    prevention: string[];
    response: string[];
    storage: string[];
    disposal: string[];
  };
  physical_hazards: string;
  health_hazards: {
    inhalation: string;
    skin_contact: string;
    eye_contact: string;
    ingestion: string;
  };
  environmental_hazards: string;
}

export interface Part3Composition {
  substance_type: string;
  components: Array<{
    name: string;
    cas: string;
    purity: string;
    chemical_family: string;
    concentration?: string;
  }>;
}

export interface Part4FirstAid {
  inhalation: string;
  skin_contact: string;
  eye_contact: string;
  ingestion: string;
  protection_for_rescuers?: string;
  notes_to_physician?: string;
}

export interface Part5Firefighting {
  hazard_characteristics: string;
  extinguishing_media: string;
  extinguishing_prohibited: string;
  firefighting_advice: string;
}

export interface Part6Spill {
  personal_precautions: string;
  emergency_response: string;
  environmental_precautions: string;
  containment_methods: string;
  cleaning_methods: string;
  ppe_for_cleanup: string;
}

export interface Part7Handling {
  operation_notes?: string;
  handling_precautions?: string;
  storage_conditions: string;
  incompatible_materials: string;
}

export interface Part8Exposure {
  occupational_limits: {
    china_pc_twa: string;
    china_pc_stel: string;
    acgih_tlv_twa: string;
  };
  monitoring_method: string;
  engineering_controls: string;
  respiratory_protection: string;
  eye_protection: string;
  skin_protection: string;
  hygiene_measures: string;
}

export interface Part9Physical {
  appearance: string;
  color?: string;
  odor?: string;
  melting_point: string;
  boiling_point: string;
  flash_point: string;
  autoignition_temp: string;
  explosion_limits: string;
  vapor_pressure: string;
  relative_density: string;
  solubility: string;
  viscosity?: string;
}

export interface Part10Stability {
  stability: string;
  conditions_to_avoid: string;
  incompatible_materials: string;
  hazardous_decomposition: string;
  polymerization_hazard: string;
}

export interface Part11Toxicology {
  acute_toxicity: {
    oral_ld50: string;
    dermal_ld50: string;
    inhalation_lc50: string;
  };
  skin_corrosion_irritation: string;
  serious_eye_damage_irritation: string;
  respiratory_skin_sensitization: string;
  carcinogenicity: string;
  reproductive_toxicity: string;
  stot_single_exposure: string;
  stot_repeated_exposure: string;
}

export interface Part12Ecology {
  ecotoxicity: {
    fish_lc50: string;
    invertebrate_ec50: string;
    algae_ec50: string;
  };
  persistence_degradability: string;
  bioaccumulation_potential?: string;
  bioaccumulation?: string;
  soil_mobility?: string;
  other_adverse_effects: string;
}

export interface Part13Disposal {
  disposal_methods: string;
  container_handling: string;
  notes?: string;
  disposal_precautions?: string;
}

export interface Part14Transport {
  un_number: string;
  proper_shipping_name: string;
  transport_hazard_class: string;
  class_name: string;
  packing_group: string;
  marine_pollutant: string;
}

export interface Part15Regulatory {
  china_regulations: string[];
  international_regulations: string[];
}

export interface Part16Other {
  preparation_info: {
    sds_number: string;
    version: string;
    revision_date: string;
    prepared_by: string;
  };
  training_requirements: string;
  references: string[];
  disclaimer: string;
}

export interface CompanyInfo {
  name: string;
  address: string;
  phone: string;
  emergency: string;
}

export interface ReviewResult {
  status: 'PASS' | 'FAIL' | 'WARN';
  completeness: CheckResult;
  ghs_consistency: CheckResult;
  data_consistency: CheckResult;
  format_compliance: CheckResult;
  professional_check: CheckResult;
  issues: string[];
  warnings: string[];
  failed_checks?: string[];
}

export interface CheckResult {
  status: 'PASS' | 'FAIL' | 'WARN';
  message?: string;
  issues?: string[];
  warnings?: string[];
}

export interface MSDSDocumentListItem {
  id: number;
  title: string;
  cas_number: string;
  doc_type: 'pure' | 'mixture';
  status: 'generating' | 'completed' | 'failed';
  created_at: string;
}

export interface MSDSTask {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  result?: MSDSDocument;
  error?: string;
}

export interface PureMSDSRequest {
  cas_or_name: string;
  company_name?: string;
  company_address?: string;
  company_phone?: string;
  emergency_phone?: string;
}

export interface MixtureMSDSRequest {
  product_name?: string;
  components: MixtureComponentInput[];
  company_info?: Record<string, string>;
}

export interface MixtureComponentInput {
  name: string;
  cas: string;
  concentration: number;
}
