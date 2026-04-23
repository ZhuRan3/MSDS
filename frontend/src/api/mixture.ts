import client from './client';
import type { MixtureCalculateRequest } from '../types/mixture';

export const mixtureApi = {
  calculate: (data: MixtureCalculateRequest) =>
    client.post('/mixture/calculate', data),

  preview: (data: MixtureCalculateRequest) =>
    client.post('/mixture/preview', data),
};
