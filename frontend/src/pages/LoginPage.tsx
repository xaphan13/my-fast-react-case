// Страница входа: форма (email, password), POST /api/blog/login.
// При успехе — обновление пользователя в AuthContext + редирект на /.
// При 401 — toast danger с сообщением бэкенда.

import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { login } from '../api/auth';
import { ApiError } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../components/Toast';
import { FormField } from './RegisterPage';
import type { ToastCategory } from '../components/Toast';
import type { User } from '../types';

export default function LoginPage() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const { showToast } = useToast();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      showToast('Заполните email и пароль', 'warning');
      return;
    }
    setSubmitting(true);
    try {
      // fastapi-users /auth/jwt/login -> 204, затем /users/me.
      const user: User = await login({ email, password });
      setUser(user);
      showToast('Вход выполнен', 'success');
      navigate('/');
    } catch (err) {
      // fastapi-users /auth/jwt/login: 400 при неверных email/пароле,
      // 401 для анонима. 400 — неверный логин/пароль.
      let message = 'Не удалось войти';
      let category: ToastCategory = 'danger';
      if (err instanceof ApiError) {
        if (err.status === 400) {
          message = 'Неверный email или пароль';
        } else {
          const data = err.data as
            | { message?: string; category?: string; detail?: string }
            | null;
          if (data?.message) message = data.message;
          else if (data?.detail) message = data.detail;
          if (data?.category) category = data.category as ToastCategory;
        }
      }
      showToast(message, category);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <h1>Вход</h1>
      <form onSubmit={handleSubmit} noValidate>
        <FormField
          label="Email"
          name="email"
          type="email"
          value={email}
          onChange={(v) => setEmail(v)}
        />
        <FormField
          label="Пароль"
          name="password"
          type="password"
          value={password}
          onChange={(v) => setPassword(v)}
        />
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Вход...' : 'Войти'}
        </button>
      </form>
      <p className="text-muted">
        Нет аккаунта? <Link to="/register">Зарегистрироваться</Link>
      </p>
    </div>
  );
}