import { useState } from 'react';

export default function AddSymbolForm({ onAdd }) {
  const [symbol, setSymbol] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!symbol.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(symbol.trim().toUpperCase());
      setSymbol('');
    } catch (err) {
      setError(err.message || 'Could not add symbol');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={styles.form}>
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="AAPL or RELIANCE.NS"
        style={styles.input}
        aria-label="Add a ticker symbol"
      />
      <button type="submit" disabled={busy || !symbol.trim()} style={styles.button}>
        {busy ? 'Adding…' : 'Add'}
      </button>
      {error && <span style={styles.error}>{error}</span>}
      <span className="muted" style={styles.hint}>
        US names as-is. NSE/BSE need .NS or .BO.
      </span>
    </form>
  );
}

const styles = {
  form: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
  input: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '9px 12px',
    color: 'var(--text)',
    width: 240,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  hint: { fontSize: 12, width: '100%' },
  button: {
    background: 'var(--surface-raised)',
    border: '1px solid var(--border)',
    color: 'var(--text)',
    borderRadius: 8,
    padding: '9px 16px',
    fontWeight: 500,
  },
  error: { color: 'var(--negative)', fontSize: 13 },
};
