export interface Chemical {
  id?: number;
  cas_number: string;
  chemical_name_cn: string;
  chemical_name_en: string;
  molecular_formula: string;
  molecular_weight: string;
  chemical_family: string;
  ghs_classifications: string[];
  pictograms: string[];
  signal_word: string;
  hazard_statements: string[];
  flash_point: string;
  boiling_point: string;
  melting_point: string;
  density: string;
  solubility: string;
  ld50_oral: string;
  ld50_dermal: string;
  lc50_inhalation: string;
  un_number: string;
  data_source: string;
  completeness: string;
  created_at?: string;
  updated_at?: string;
}

export interface ChemicalListItem {
  cas_number: string;
  chemical_name_cn: string;
  chemical_name_en: string;
  molecular_formula: string;
  chemical_family: string;
  signal_word: string;
  ghs_classifications: string[];
  pictograms: string[];
  data_source: string;
}

export interface ChemicalSearchParams {
  q?: string;
  search?: string;
  family?: string;
  page?: number;
  page_size?: number;
}
