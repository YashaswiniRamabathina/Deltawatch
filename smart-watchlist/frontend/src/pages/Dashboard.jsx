import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import AddSymbolForm from '../components/AddSymbolForm';
import ChangeFeed from '../components/ChangeFeed';
import WatchlistTable from '../components/WatchlistTable';

const REFRESH_MS = 20_000;

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [items, setItems] = useState([]);
  const [digest, setDigest] = useState({ entries: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [watchlist, digestData] = await Promise.all([api.getWatchlist(), api.getDigest()]);
      setItems(watchlist);
      setDigest(digestData);
      setError(null);
    } catch (err) {
      setError(err.message || 'Could not reach the server');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(() => {
      if (!document.hidden) refresh();
    }, REFRESH_MS);
    function onVisibility() {
      if (!document.hidden) refresh();
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [refresh]);

  async function handleAdd(symbol) {
    await api.addSymbol(symbol);
    await refresh();
  }

  async function handleRemove(symbol) {
    try {
      await api.removeSymbol(symbol);
      setItems((prev) => prev.filter((i) => i.symbol !== symbol));
      setDigest((prev) => ({ ...prev, entries: prev.entries.filter((e) => e.symbol !== symbol) }));
      setError(null);
    } catch (err) {
      setError(err.message || `Could not remove ${symbol}`);
    }
  }

  async function handleToggleHeld(symbol, held) {
    await api.setHeld(symbol, held);
    await refresh();
  }

  async function handleAcknowledge(symbol) {
    await api.markSeen(symbol);
    setDigest((prev) => ({ ...prev, entries: prev.entries.filter((e) => e.symbol !== symbol) }));
    refresh();
  }

  async function handleAcknowledgeAll() {
    await api.markAllSeen();
    setDigest((prev) => ({ ...prev, entries: [] }));
    refresh();
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div style={styles.brand}>
          <span style={{ color: 'var(--amber)', fontSize: 12 }}>●</span>
          <span style={{ fontWeight: 600 }}>Watchlist</span>
        </div>
        <div style={styles.headerRight}>
          <span className="muted" style={{ fontSize: 13 }}>{user?.email}</span>
          <button onClick={logout} style={styles.logoutBtn}>Log out</button>
        </div>
      </header>

      <main style={styles.main}>
        {error && <div style={styles.errorBanner}>{error}</div>}

        <section style={styles.section}>
          <div style={styles.sectionHeading}>
            <div>
              <h1 style={styles.h1}>Since you left</h1>
              <p className="muted" style={styles.subtitle}>
                Unusual for this stock since you looked — not a 5% blast.
              </p>
            </div>
            <div style={styles.headingActions}>
              <span className="muted" style={{ fontSize: 13 }}>
                {digest.entries.length > 0
                  ? `${digest.entries.length} symbol${digest.entries.length === 1 ? '' : 's'} worth a look`
                  : ''}
              </span>
              {digest.entries.length > 0 && (
                <button type="button" onClick={handleAcknowledgeAll} style={styles.catchUpBtn}>
                  Catch up
                </button>
              )}
            </div>
          </div>
          <ChangeFeed entries={digest.entries} loading={loading} onAcknowledge={handleAcknowledge} />
        </section>

        <section style={styles.section}>
          <div style={styles.sectionHeading}>
            <h2 style={styles.h2}>Your watchlist</h2>
            <AddSymbolForm onAdd={handleAdd} />
          </div>
          <WatchlistTable items={items} onRemove={handleRemove} onToggleHeld={handleToggleHeld} />
        </section>
      </main>
    </div>
  );
}

const styles = {
  page: { minHeight: '100vh' },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '18px 32px',
    borderBottom: '1px solid var(--border)',
  },
  brand: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 16 },
  headerRight: { display: 'flex', alignItems: 'center', gap: 16 },
  logoutBtn: {
    background: 'none',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 6,
    padding: '6px 12px',
    fontSize: 13,
  },
  catchUpBtn: {
    background: 'none',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    borderRadius: 6,
    padding: '6px 12px',
    fontSize: 13,
  },
  main: {
    maxWidth: 980,
    margin: '0 auto',
    padding: '32px',
    display: 'flex',
    flexDirection: 'column',
    gap: 40,
  },
  section: {},
  sectionHeading: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
    marginBottom: 16,
  },
  h1: { fontSize: 22, margin: 0, fontWeight: 600 },
  subtitle: { fontSize: 13, margin: '4px 0 0' },
  headingActions: { display: 'flex', alignItems: 'center', gap: 12 },
  h2: { fontSize: 16, margin: 0, fontWeight: 600, color: 'var(--text-muted)' },
  errorBanner: {
    background: 'rgba(240, 85, 107, 0.1)',
    border: '1px solid rgba(240, 85, 107, 0.3)',
    color: 'var(--negative)',
    borderRadius: 8,
    padding: '10px 14px',
    fontSize: 13.5,
  },
};
