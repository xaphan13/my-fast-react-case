// Страница регистрации: форма (username, email, password, confirm_password)
// с клиентской валидацией. POST /api/blog/register; при 422 показываем
// errors по полям; при успехе — toast + редирект на /login.

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { register, extractErrors } from '../api/auth';
import { useToast } from '../components/Toast';

interface FormState {
  username: string;
  email: string;
  password: string;
  confirm_password: string;
}

// Клиентская валидация: зеркалирует серверную в api_blog.py
// (те же правила длины и email).
export function validate(form: FormState): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  if (!form.username.trim()) {
    errors.username = ['This field is required.'];
  } else if (form.username.trim().length > 100) {
    errors.username = ['Field must be 100 characters or less.'];
  }
  if (!form.email.trim()) {
    errors.email = ['This field is required.'];
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
    errors.email = ['Invalid email address.'];
  }
  if (!form.password) {
    errors.password = ['This field is required.'];
  } else if (form.password.length < 8) {
    errors.password = ['Field must be at least 8 characters long.'];
  }
  if (!form.confirm_password) {
    errors.confirm_password = ['This field is required.'];
  } else if (form.password !== form.confirm_password) {
    errors.confirm_password = ['Passwords must match.'];
  }
  return errors;
}

export default function RegisterPage() {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [form, setForm] = useState<FormState>({
    username: '',
    email: '',
    password: '',
    confirm_password: '',
  });
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [submitting, setSubmitting] = useState(false);

  const setField = (field: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    // Первая правка поля снимает его ошибку.
    setErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const clientErrors = validate(form);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    setSubmitting(true);
    try {
      // fastapi-users /auth/register: только email + password, возвращает User (201).
      // Поля username/confirm_password из формы в новом контракте не используются.
      await register({ email: form.email, password: form.password });
      showToast('Регистрация выполнена', 'success');
      navigate('/login');
    } catch (err) {
      const serverErrors = extractErrors(err);
      if (Object.keys(serverErrors).length > 0) {
        setErrors(serverErrors);
      } else {
        // Прочие ошибки (400 уже авторизован, сеть) — тостом.
        const detail =
          err instanceof Error ? err.message : 'Не удалось зарегистрироваться';
        showToast(detail, 'danger');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <h1>Регистрация</h1>
      <form onSubmit={handleSubmit} noValidate>
        <FormField
          label="Имя пользователя"
          name="username"
          type="text"
          value={form.username}
          errors={errors.username}
          onChange={(v) => setField('username', v)}
        />
        <FormField
          label="Email"
          name="email"
          type="email"
          value={form.email}
          errors={errors.email}
          onChange={(v) => setField('email', v)}
        />
        <FormField
          label="Пароль"
          name="password"
          type="password"
          value={form.password}
          errors={errors.password}
          onChange={(v) => setField('password', v)}
        />
        <FormField
          label="Подтверждение пароля"
          name="confirm_password"
          type="password"
          value={form.confirm_password}
          errors={errors.confirm_password}
          onChange={(v) => setField('confirm_password', v)}
        />
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Регистрация...' : 'Зарегистрироваться'}
        </button>
      </form>
      <p className="text-muted">
        Уже есть аккаунт? <Link to="/login">Войти</Link>
      </p>
    </div>
  );
}

// Общая строка формы с блоком ошибок 422 (serverErrors отобразятся
// под полем). Используется и на LoginPage, и на AccountPage.
export function FormField({
  label,
  name,
  type,
  value,
  errors,
  onChange,
}: {
  label: string;
  name: string;
  type: string;
  value: string;
  errors?: string[];
  onChange: (value: string) => void;
}) {
  const hasError = errors && errors.length > 0;
  return (
    <div className={`form-field${hasError ? ' form-field-invalid' : ''}`}>
      <label htmlFor={name}>{label}</label>
      <input
        id={name}
        name={name}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {hasError && (
        <div className="form-errors">
          {errors.map((text) => (
            <div key={text} className="form-error-text">
              {text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}