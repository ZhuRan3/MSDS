// Common API types
export interface ApiResponse<T = any> {
  code: number;
  message: string;
  data: T;
}

export interface PageParams {
  page: number;
  page_size: number;
}

export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface SystemStatus {
  status: string;
  llm_provider: string;
  llm_connected: boolean;
  knowledge_base_count: number;
  document_count: number;
  version: string;
}
