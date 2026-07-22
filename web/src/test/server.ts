import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

export const server = setupServer(
  http.get('/api/datasets', () => HttpResponse.json({
    data: [],
    meta: { page: 1, page_size: 20, total: 0 },
  })),
);
