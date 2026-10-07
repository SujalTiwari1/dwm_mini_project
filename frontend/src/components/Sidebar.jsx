import { NavLink } from 'react-router-dom';

const NAV = [
  { to: '/dashboard',  icon: '⬡', label: 'Dashboard'         },
  { to: '/sales',      icon: '↗', label: 'Sales'              },
  { to: '/inventory',  icon: '▦', label: 'Inventory'          },
  { to: '/forecast',   icon: '◬', label: 'Demand & Forecast'  },
  { to: '/risk',       icon: '⚠', label: 'Risk & Expiry'      },
  { to: '/insights',   icon: '◉', label: 'Insights'           },
  { to: '/decisions',  icon: '✦', label: 'Decisions'          },
];

export default function Sidebar() {
  return (
    <aside className="app-sidebar">
      <span className="sidebar-section-label">Navigation</span>
      {NAV.map(({ to, icon, label }) => (
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
