import { request } from './http';

export type UserRole = 'admin' | 'data_engineer' | 'reviewer';

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  is_active: boolean;
}

export function getCurrentUser(): Promise<SessionUser> {
  return request<SessionUser>('/api/auth/me');
}

export function login(email: string, password: string): Promise<SessionUser> {
  return request<SessionUser>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return request<void>('/api/auth/logout', { method: 'POST' });
}
