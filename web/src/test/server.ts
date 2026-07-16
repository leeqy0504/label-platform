import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

export const server = setupServer(
  http.get('/api/auth/me', () => HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 })),
  http.post('/api/auth/login', () => HttpResponse.json({
    id: 'user-1',
    email: 'engineer@example.test',
    name: 'Dataset Engineer',
    role: 'data_engineer',
    is_active: true,
  })),
  http.get('/api/datasets', () => HttpResponse.json({
    data: [],
    meta: { page: 1, page_size: 20, total: 0 },
  })),
);
