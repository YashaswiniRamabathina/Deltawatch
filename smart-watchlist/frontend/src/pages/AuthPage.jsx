import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === 'login') await login(email, password);
      else await register(email, password);
    } catch (err) {
      setError(err.message || 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.brand}>
          <span style={styles.brandMark}>●</span>
          <span>Watchlist</span>
        </div>
        <p style={styles.tagline}>
          Track what deserves your attention, not just what moved.
        </p>

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Email
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={styles.input}
              autoComplete="email"
            />
          </label>
          <label style={styles.label}>
            Password
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={styles.input}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>

          {error && <div style={styles.error}>{error}</div>}

          <button type="submit" disabled={busy} style={styles.submit}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}
          </button>
        </form>

        <button
          type="button"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          style={styles.switchMode}
        >
          {mode === 'login' ? "Don't have an account? Create one" : 'Already have an account? Log in'}
        </button>
      </div>
    </div>
  );
}

const styles = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    width: '100%',
    maxWidth: 380,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 14,
    padding: '32px 28px',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontWeight: 600,
    fontSize: 18,
    marginBottom: 6,
  },
  brandMark: { color: 'var(--amber)', fontSize: 12 },
  tagline: {
    color: 'var(--text-muted)',
    fontSize: 14,
    margin: '0 0 28px',
    lineHeight: 1.5,
  },
  form: { display: 'flex', flexDirection: 'column', gap: 16 },
  label: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontSize: 13,
    color: 'var(--text-muted)',
  },
  input: {
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '10px 12px',
    color: 'var(--text)',
  },
  error: {
    fontSize: 13,
    color: 'var(--negative)',
    background: 'rgba(240, 85, 107, 0.1)',
    border: '1px solid rgba(240, 85, 107, 0.3)',
    borderRadius: 8,
    padding: '8px 12px',
  },
  submit: {
    marginTop: 4,
    background: 'var(--amber)',
    color: '#1a1305',
    fontWeight: 600,
    border: 'none',
    borderRadius: 8,
    padding: '11px 16px',
  },
  switchMode: {
    marginTop: 18,
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    fontSize: 13,
    padding: 0,
    textDecoration: 'underline',
    textUnderlineOffset: 3,
  },
};
