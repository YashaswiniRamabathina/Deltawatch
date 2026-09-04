const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function getToken() {
  return localStorage.getItem('watchlist_token');
}

async function request(path, { method = 'GET', body, auth = true, form = false } = {}) {
  const headers = {};
  if (!form) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: form ? body : body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    // no body
  }

  if (!res.ok) {
    if (res.status === 401 && auth) {
      setToken(null);
      window.dispatchEvent(new Event('watchlist:unauthorized'));
    }
    const message = data?.detail || `Request failed (${res.status})`;
    throw new ApiError(typeof message === 'string' ? message : JSON.stringify(message), res.status);
  }
  return data;
}

export const api = {
  register: (email, password) =>
    request('/auth/register', { method: 'POST', body: { email, password }, auth: false }),

  login: (email, password) => {
    const form = new URLSearchParams();
    form.set('username', email);
    form.set('password', password);
    return request('/auth/login', { method: 'POST', body: form, auth: false, form: true });
  },

  me: () => request('/auth/me'),

  getWatchlist: () => request('/watchlist'),

  addSymbol: (symbol) => request('/watchlist', { method: 'POST', body: { symbol } }),

  removeSymbol: (symbol) => request(`/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' }),

  markSeen: (symbol) => request(`/watchlist/${encodeURIComponent(symbol)}/seen`, { method: 'POST' }),

  markAllSeen: () => request('/watchlist/seen-all', { method: 'POST' }),

  setHeld: (symbol, held) =>
    request(`/watchlist/${encodeURIComponent(symbol)}/held`, { method: 'POST', body: { held } }),

  getDigest: () => request('/digest'),
};

export { ApiError, getToken };

export function setToken(token) {
  if (token) localStorage.setItem('watchlist_token', token);
  else localStorage.removeItem('watchlist_token');
}
