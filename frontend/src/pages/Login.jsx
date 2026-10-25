import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

const ROLES = [
  { role: 'employee', label: 'Login as Employee', hint: 'Overview, sales explorer, forecast and uploads' },
  { role: 'admin',    label: 'Login as Admin',    hint: 'Everything, including the Models section' },
];

const inputStyle = {
  width: '100%', boxSizing: 'border-box', padding: '0.6rem 0.75rem', font: 'inherit', fontSize: '0.85rem',
  border: '1px solid var(--color-border)', borderRadius: 'var(--radius)',
  background: 'var(--color-surface)', color: 'var(--color-text)',
};
const labelStyle = { display: 'block', fontSize: '0.75rem', fontWeight: 600, marginBottom: '0.3rem' };

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [notice, setNotice] = useState('');

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--color-bg)', padding: '1rem',
    }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          // Fake auth: an email containing "admin" gets the admin role, anything else is an employee.
          login(email.toLowerCase().includes('admin') ? 'admin' : 'employee');
        }}
        style={{
          width: '100%', maxWidth: '380px', background: 'var(--color-surface)',
          border: '1px solid var(--color-border)', borderRadius: 'var(--radius)',
          boxShadow: 'var(--shadow-md)', padding: '2rem',
        }}
      >
        <img
          src="/MedStock%20Pharmacy%20Analytics%20Logo.png"
          alt="MedStock — Pharmacy sales & demand analytics"
          style={{ width: '100%', height: 'auto', display: 'block', marginBottom: '1rem' }}
        />

        <div style={{ marginBottom: '0.9rem' }}>
          <label htmlFor="login-email" style={labelStyle}>Email</label>
          <input
            id="login-email" type="email" autoComplete="email" placeholder="you@example.com"
            value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle}
          />
        </div>
        <div style={{ marginBottom: '0.5rem' }}>
          <label htmlFor="login-password" style={labelStyle}>Password</label>
          <input
            id="login-password" type="password" autoComplete="current-password" placeholder="••••••••"
            value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle}
          />
        </div>
        <div style={{ textAlign: 'right', marginBottom: '1.25rem' }}>
          <a
            href="#forgot"
            onClick={(e) => { e.preventDefault(); setNotice('Password reset is not available in this demo.'); }}
            style={{ fontSize: '0.75rem', color: 'var(--color-accent-light)' }}
          >
            Forgot password?
          </a>
        </div>
        {notice && (
          <p style={{ fontSize: '0.75rem', color: 'var(--color-muted)', margin: '0 0 1rem' }}>{notice}</p>
        )}

        <button
          type="submit"
          style={{
            width: '100%', cursor: 'pointer', padding: '0.7rem 1rem', font: 'inherit', fontWeight: 600,
            fontSize: '0.9rem', borderRadius: 'var(--radius)', border: 'none',
            background: 'var(--color-text)', color: '#fff', marginBottom: '1.1rem',
          }}
        >
          Login
        </button>
        <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'var(--color-muted)', marginBottom: '0.9rem' }}>
          or continue as
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {ROLES.map(({ role, label, hint }) => (
            <button
              key={role}
              type="button"
              onClick={() => login(role)}
              style={{
                textAlign: 'left', cursor: 'pointer', padding: '0.85rem 1rem',
                borderRadius: 'var(--radius)', font: 'inherit',
                border: '1px solid ' + (role === 'admin' ? 'var(--color-accent)' : 'var(--color-border)'),
                background: role === 'admin' ? 'var(--color-accent)' : 'var(--color-surface)',
                color: role === 'admin' ? '#fff' : 'var(--color-text)',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{label}</div>
              <div style={{ fontSize: '0.72rem', opacity: 0.75, marginTop: '0.15rem' }}>{hint}</div>
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
