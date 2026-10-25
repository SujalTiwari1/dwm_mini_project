import { NavLink } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const NAV = [
  { to: '/overview', icon: '⌂', label: 'Overview'        },
  { to: '/olap',     icon: '▦', label: 'Sales Explorer'  },
  { to: '/forecast', icon: '◬', label: 'Demand Forecast' },
  { to: '/mining',   icon: '⛏', label: 'Mining Insights', adminOnly: true },
  { to: '/models',   icon: '◈', label: 'Models', adminOnly: true },
  { to: '/upload',  icon: '⇪', label: 'Upload Data'     },
];

export default function Sidebar() {
  const { isAdmin } = useAuth();
  return (
    <aside className="app-sidebar">
      <span className="sidebar-section-label">Menu</span>
      {NAV.filter((n) => isAdmin || !n.adminOnly).map(({ to, icon, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) => 'sidebar-link' + (isActive ? ' active' : '')}
        >
          <span className="sidebar-icon">{icon}</span>
          {label}
        </NavLink>
      ))}
    </aside>
  );
}
