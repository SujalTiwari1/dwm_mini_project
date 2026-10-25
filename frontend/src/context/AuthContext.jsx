import { createContext, useContext, useState } from 'react';

const KEY = 'medstock_role';
const AuthContext = createContext(null);

function readRole() {
  try { return sessionStorage.getItem(KEY); } catch { return null; }
}

/** Fake auth: the role is just remembered for the browser session. No credentials are checked. */
export function AuthProvider({ children }) {
  const [role, setRole] = useState(readRole);

  const login = (r) => {
    try { sessionStorage.setItem(KEY, r); } catch { /* ignore */ }
    setRole(r);
  };
  const logout = () => {
    try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
    setRole(null);
  };

  return (
    <AuthContext.Provider value={{ role, isAdmin: role === 'admin', login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
