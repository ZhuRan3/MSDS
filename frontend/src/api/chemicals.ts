import client from './client';
import type { ChemicalSearchParams } from '../types/chemical';

export const chemicalsApi = {
  list: (params?: ChemicalSearchParams) =>
    client.get('/chemicals', { params }),

  get: (cas: string) =>
    client.get(`/chemicals/${cas}`),

  search: (q: string) =>
    client.get('/chemicals/search', { params: { q } }),

  add: (cas: string, name?: string) =>
    client.post('/chemicals', { cas_or_name: cas, name_cn: name }),

  update: (cas: string) =>
    client.put(`/chemicals/${cas}`),

  delete: (cas: string) =>
    client.delete(`/chemicals/${cas}`),

  fetchPubChem: (casOrName: string) =>
    client.post('/chemicals/fetch-pubchem', { cas_or_name: casOrName }),
};
