import { useState, useCallback, useEffect } from 'react';

const TOKEN_KEY = 'token';
const USER_KEY = 'userId';

export function useAuth() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [userId, setUserId] = useState(() => localStorage.getItem(USER_KEY));

  const saveAuth = useCallback((t: string, u: string) => {
    localStorage.setItem(TOKEN_KEY, t);
    localStorage.setItem(USER_KEY, u);
    setToken(t);
    setUserId(u);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUserId(null);
  }, []);

  const isLoggedIn = !!token;

  return { token, userId, isLoggedIn, saveAuth, logout };
}
