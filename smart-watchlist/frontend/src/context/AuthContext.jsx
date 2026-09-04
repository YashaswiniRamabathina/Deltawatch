import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, getToken, setToken } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    async function bootstrap() {
      if (getToken()) {
        try {
          const me = await api.me();
          setUser(me);
        } catch {
          setToken(null);
        }
      }
      setChecking(false);
    }
    bootstrap();
  }, []);

  useEffect(() => {
    function onUnauthorized() {
      setToken(null);
      setUser(null);
    }
    window.addEventListener('watchlist:unauthorized', onUnauthorized);
    return () => window.removeEventListener('watchlist:unauthorized', onUnauthorized);
  }, []);

  const login = useCallback(async (email, password) => {
    const { access_token } = await api.login(email, password);
    setToken(access_token);
    const me = await api.me();
    setUser(me);
  }, []);

  const register = useCallback(async (email, password) => {
    const { access_token } = await api.register(email, password);
    setToken(access_token);
    const me = await api.me();
    setUser(me);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, checking, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
