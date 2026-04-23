export interface MixtureComponent {
  name: string;
  cas: string;
  concentration: number;
  ld50_oral?: number | null;
  ld50_dermal?: number | null;
  lc50_inhalation?: number | null;
  ghs_classifications?: string[];
  flash_point?: number | null;
  boiling_point?: number | null;
  is_unknown_toxicity?: boolean;
}

export interface MixtureCalculateRequest {
  components: MixtureComponent[];
}

export interface MixtureCalculateResponse {
  ate_oral: number | null;
  ate_dermal: number | null;
  ate_inhalation: number | null;
  classifications: ClassificationResult[];
  h_codes: string[];
  signal_word: string;
  flammability_class: string;
  unknown_percentage: number;
  calculation_log: string[];
}

export interface ClassificationResult {
  hazard: string;
  category?: number;
  h_code: string;
  signal: string;
  reason?: string;
  ate?: number;
  route?: string;
  flash_point_ref?: number;
}
