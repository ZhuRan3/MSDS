import client from './client';
import type { PureMSDSRequest } from '../types/msds';

export const msdsApi = {
  generatePure: (data: PureMSDSRequest) =>
    client.post('/msds/generate-pure', data),

  generateMixture: (data: {
    product_name?: string;
    components: Array<{ name: string; cas: string; concentration: number }>;
    company_info?: Record<string, string>;
  }) =>
    client.post('/msds/generate-mixture', data),

  getTaskStatus: (taskId: string) =>
    client.get(`/msds/tasks/${taskId}`),

  listDocuments: (params?: { page?: number; page_size?: number }) =>
    client.get('/msds/documents', { params }),

  getDocument: (id: number) =>
    client.get(`/msds/documents/${id}`),

  getDocumentMarkdown: (id: number) =>
    client.get(`/msds/documents/${id}/markdown`, { responseType: 'text' }),

  exportPdf: (id: number) =>
    client.get(`/msds/documents/${id}/pdf`, { responseType: 'blob' }),

  exportWord: (id: number) =>
    client.get(`/msds/documents/${id}/word`, { responseType: 'blob' }),

  reviewDocument: (id: number) =>
    client.post(`/msds/documents/${id}/review`),

  deleteDocument: (id: number) =>
    client.delete(`/msds/documents/${id}`),
};
