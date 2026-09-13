// Функции API авторизации и аккаунта: register, login, logout,
// getAccount, updateAccount (multipart). Backend — fastapi-users:
// /auth/jwt/login (form, 204), /auth/jwt/logout (form, 204),
// /auth/register (JSON, 201), /auth/account (multipart),
// /users/me (JSON, 401 для анонима).

import { ApiError, getJson, postForm, postJson, postMultipart } from './client';
import type { User } from '../types';

export interface MessageResp {
  message: string;
  category: string;
}

// /auth/jwt/login отвечает 204 — фронт после успешного логина делает
// refresh через /users/me (возвращает UserRead).
export function login(body: { email: string; password: string }): Promise<User> {
  const form = new URLSearchParams({
    username: body.email,
    password: body.password,
  });
  return postForm<unknown>('/auth/jwt/login', form).then(() => getJson<User>('/users/me'));
}

// /auth/jwt/logout отвечает 204 — фронт НЕ падает, если logout вернул ошибку.
export function logout(): Promise<MessageResp> {
  return postForm<MessageResp>('/auth/jwt/logout', new URLSearchParams())
    .catch(() => ({ message: 'Logged out', category: 'info' }));
}

export function register(body: { email: string; password: string }): Promise<User> {
  return postJson<User>('/auth/register', body);
}

export async function getAccount(): Promise<{ user: User }> {
  const user = await getJson<User>('/users/me');
  return { user };
}

export function updateAccount(body: {
  username: string;
  email: string;
  picture?: File | null;
}): Promise<MessageResp & { user: User }> {
  const formData = new FormData();
  formData.set('username', body.username);
  formData.set('email', body.email);
  if (body.picture) formData.set('picture', body.picture);
  return postMultipart<MessageResp & { user: User }>('/auth/account', formData);
}

// getCurrentUser: для AuthContext.refresh() — возвращает User или null
// (если 401 — пользователь не залогинен).
export function getCurrentUser(): Promise<User | null> {
  return getJson<User>('/users/me').catch((err) => {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  });
}

// Хелпер для RegisterPage — маппит ошибки fastapi-users в формат полей.
export function extractErrors(err: unknown): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  if (err instanceof ApiError) {
    const data = err.data as
      | { errors?: Record<string, string[]>; detail?: string | Array<{ loc?: unknown[]; msg?: string }> }
      | null;
    if (data?.errors) return data.errors;
    if (typeof data?.detail === 'string') {
      if (data.detail.startsWith('REGISTER_INVALID_PASSWORD')) {
        out.password = [data.detail];
      } else if (data.detail.startsWith('REGISTER_USER_ALREADY_EXISTS')) {
        out.email = [data.detail];
      }
    }
  }
  return out;
}
