'use client';

import { useRole } from '@/context/RoleContext';
import { RoleId } from '@/data/roles';

const ROLE_BUTTONS: { id: RoleId; label: string }[] = [
  { id: 'ngo', label: 'NGO / Aid Org' },
  { id: 'gov', label: 'National Government' },
  { id: 'intl', label: 'UN / World Bank' },
  { id: 'research', label: 'Research Institution' },
  { id: 'admin', label: '⚙ Platform Admin' },
];

export default function RoleSwitcher() {
  const { currentRole, switchRole } = useRole();

  return (
    <div className="role-bar">
      <span className="role-bar-label">View as:</span>
      {ROLE_BUTTONS.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          className={`role-btn ${currentRole === id ? 'active' : ''}${id === 'admin' ? ' role-btn--pin-right' : ''}`}
          data-role={id}
          onClick={() => switchRole(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
