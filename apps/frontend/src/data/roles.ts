export type RoleId = 'ngo' | 'gov' | 'intl' | 'research' | 'admin';

export interface StatConfig {
  label: string;
  val: string;
  delta: string;
  dc: '' | 'ok' | 'warn' | 'neg';
}

export interface RoleConfig {
  label: string;
  access: string;
  dot: string;
  pillBg: string;
  banner: { text: string; bg: string; color: string };
  stats: StatConfig[];
  matrix: string[][];
  navLocked: string[];
}

export const matrixHeaders = ['Feature', 'View', 'Download', 'Export API', 'Report'];

export const roles: Record<RoleId, RoleConfig> = {
  ngo: {
    label: 'CARE International',
    access: 'NGO ACCESS',
    dot: '#52b788',
    pillBg: '#f0faf4',
    banner: {
      text: 'Viewing as NGO/Aid Organization — Operational data access. Government-sensitive data restricted. Exports limited to your region of operation.',
      bg: '#f0faf4',
      color: '#2d6a4f',
    },
    stats: [
      { label: 'Households in Op. Zone', val: '340K', delta: '↑ 12K this month', dc: 'ok' },
      { label: 'Active Disaster Events', val: '3', delta: '↑ 1 this week', dc: 'warn' },
      { label: 'Crop Alerts — Your Region', val: '7', delta: '2 critical', dc: 'neg' },
      { label: 'Aid Corridors Open', val: '12', delta: '↓ 2 closed today', dc: 'warn' },
    ],
    matrix: [
      ['Poverty Mapping (Economic Visibility)', '✓', '✓', '—', '✓'],
      ['Household PII', '✗', '✗', '✗', '✗'],
      ['Aid Coordination Bridge', '✓', '✓', '—', '✓'],
      ['Farmland Protection', '✓', '✓', '—', '✓'],
      ['Agriculture (CropGuard)', '✓', '✓', '—', '✓'],
      ['Disaster Relief (ShockGuard)', '✓', '✓', '✓', '✓'],
      ['Mobility Compass', '—', '—', '—', '—'],
      ['SkillsBridge', '—', '—', '—', '—'],
      ['Raw Satellite Export', '✗', '✗', '✗', '✗'],
    ],
    navLocked: ['navAdmin'],
  },
  gov: {
    label: 'Federal Ministry — Nigeria',
    access: 'GOV ACCESS',
    dot: '#74a7d5',
    pillBg: '#f0f5fc',
    banner: {
      text: 'Viewing as National Government — Full sovereign data access for your territory. Cross-border data requires bilateral agreement. All queries audit-logged.',
      bg: '#f0f5fc',
      color: '#1d3557',
    },
    stats: [
      { label: 'National Households Mapped', val: '2.4M', delta: '↑ 124K this month', dc: 'ok' },
      { label: 'Active Disaster Zones', val: '7', delta: '↑ 2 this week', dc: 'neg' },
      { label: 'Crops Monitored (ha)', val: '890K', delta: '↑ 12% coverage', dc: 'ok' },
      { label: 'Policy Reports Generated', val: '34', delta: 'This quarter', dc: '' },
    ],
    matrix: [
      ['Poverty Mapping (Economic Visibility)', '✓', '✓', '✓', '✓'],
      ['Household PII', '✓*', '✓*', '✗', '✓*'],
      ['Aid Coordination Bridge', '✓', '✓', '✓', '✓'],
      ['Farmland Protection', '✓', '✓', '✓', '✓'],
      ['Agriculture (CropGuard)', '✓', '✓', '✓', '✓'],
      ['Disaster Relief (ShockGuard)', '✓', '✓', '✓', '✓'],
      ['Mobility Compass', '✓', '✓', '✓', '✓'],
      ['SkillsBridge', '✓', '✓', '—', '✓'],
      ['Raw Satellite Export', '✓', '✓', '✗', '—'],
    ],
    navLocked: ['navAdmin'],
  },
  intl: {
    label: 'OCHA — UN Humanitarian',
    access: 'INTL ACCESS',
    dot: '#c18ab4',
    pillBg: '#faf0f8',
    banner: {
      text: 'Viewing as International Body — Cross-border data access enabled. Raw data export available. Multi-country analysis unlocked. Coordinate with national authorities before operational deployment.',
      bg: '#faf0f8',
      color: '#6b2d5e',
    },
    stats: [
      { label: 'Total Households Mapped', val: '8.1M', delta: 'Global coverage', dc: 'ok' },
      { label: 'Countries Monitored', val: '34', delta: '6 new this quarter', dc: 'ok' },
      { label: 'Active Crises Tracked', val: '12', delta: '↑ 3 from last month', dc: 'neg' },
      { label: 'Data Agreements Active', val: '28', delta: '3 pending renewal', dc: 'warn' },
    ],
    matrix: [
      ['Poverty Mapping (Economic Visibility)', '✓', '✓', '✓', '✓'],
      ['Household PII', '—', '—', '—', '—'],
      ['Aid Coordination Bridge', '✓', '✓', '✓', '✓'],
      ['Farmland Protection', '✓', '✓', '✓', '✓'],
      ['Agriculture (CropGuard)', '✓', '✓', '✓', '✓'],
      ['Disaster Relief (ShockGuard)', '✓', '✓', '✓', '✓'],
      ['Mobility Compass', '✓', '✓', '✓', '✓'],
      ['SkillsBridge', '✓', '✓', '✓', '✓'],
      ['Raw Satellite Export', '✓', '✓', '✓', '✓'],
    ],
    navLocked: ['navAdmin'],
  },
  research: {
    label: 'MIT Poverty Action Lab',
    access: 'RESEARCH ACCESS',
    dot: '#f4a832',
    pillBg: '#fdf8ee',
    banner: {
      text: 'Viewing as Research Institution — Anonymised datasets only. Historical archive access enabled. No PII without signed DPA. Model output available for validation studies.',
      bg: '#fdf8ee',
      color: '#7b4f00',
    },
    stats: [
      { label: 'Anonymised Records', val: '12.4M', delta: 'Historical archive', dc: 'ok' },
      { label: 'Model Accuracy (avg)', val: '91%', delta: 'Across 6 models', dc: 'ok' },
      { label: 'Active Data Requests', val: '4', delta: '2 pending approval', dc: 'warn' },
      { label: 'Published Datasets', val: '18', delta: 'This year', dc: 'ok' },
    ],
    matrix: [
      ['Poverty Mapping (Economic Visibility)', '✓', '✓', '—', '✓'],
      ['Household PII', '✗', '✗', '✗', '✗'],
      ['Aid Coordination Bridge', '—', '—', '—', '✓'],
      ['Farmland Protection', '✓', '—', '—', '✓'],
      ['Agriculture (CropGuard)', '✓', '✓', '✓', '✓'],
      ['Disaster Relief (ShockGuard)', '—', '—', '—', '✓'],
      ['Mobility Compass', '✓', '✓', '✓', '✓'],
      ['SkillsBridge', '✓', '✓', '—', '✓'],
      ['Raw Satellite Export', '—', '—', '—', '✓'],
    ],
    navLocked: ['navAdmin'],
  },
  admin: {
    label: 'Platform Administrator',
    access: 'SUPER ADMIN',
    dot: '#666',
    pillBg: '#f5f5f5',
    banner: {
      text: 'Platform Admin view — Full access to all data, permissions, audit logs, and organisation management. All actions logged. Data sovereignty rules cannot be overridden.',
      bg: '#f5f5f5',
      color: '#1a1714',
    },
    stats: [
      { label: 'Registered Organisations', val: '12', delta: '3 pending approval', dc: 'warn' },
      { label: 'Active User Sessions', val: '47', delta: '↑ 8 from yesterday', dc: 'ok' },
      { label: 'Data Requests (30d)', val: '1.2K', delta: '98.4% fulfilled', dc: 'ok' },
      { label: 'Permission Changes (30d)', val: '23', delta: 'All audit-logged', dc: '' },
    ],
    matrix: [
      ['Poverty Mapping (Economic Visibility)', '✓', '✓', '✓', '✓'],
      ['Household PII', '✓', '✓', '✓', '✓'],
      ['Aid Coordination Bridge', '✓', '✓', '✓', '✓'],
      ['Farmland Protection', '✓', '✓', '✓', '✓'],
      ['Agriculture (CropGuard)', '✓', '✓', '✓', '✓'],
      ['Disaster Relief (ShockGuard)', '✓', '✓', '✓', '✓'],
      ['Mobility Compass', '✓', '✓', '✓', '✓'],
      ['SkillsBridge', '✓', '✓', '✓', '✓'],
      ['Raw Satellite Export', '✓', '✓', '✓', '✓'],
    ],
    navLocked: [],
  },
};

export const roleColors: Record<RoleId, string> = {
  ngo: '#52b788',
  gov: '#74a7d5',
  intl: '#c18ab4',
  research: '#f4a832',
  admin: '#888',
};
