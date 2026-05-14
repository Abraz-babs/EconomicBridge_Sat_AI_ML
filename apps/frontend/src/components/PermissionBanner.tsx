'use client';

import { useRole } from '@/context/RoleContext';

export default function PermissionBanner() {
  const { roleConfig } = useRole();

  return (
    <div
      className="perm-banner"
      style={{
        background: roleConfig.banner.bg,
        color: roleConfig.banner.color,
      }}
    >
      {roleConfig.banner.text}
    </div>
  );
}
