export type ConflictRisk = 'low' | 'medium' | 'high' | 'critical';
export type TenantType = 'ng_state' | 'ng_fct' | 'ecowas_country';
export type DeploymentPhase = 1 | 2 | 3;

export interface Tenant {
  id: string;
  name: string;
  type: TenantType;
  country: string;
  capital: string;
  conflict_risk: ConflictRisk;
  active: boolean;
  priority: number;
  deployment_phase: DeploymentPhase;
  /** [longitude, latitude] — centroid of the satellite_roi bounding box from tenants.yaml */
  centroid: [number, number];
}

function centroid(roi: [number, number, number, number]): [number, number] {
  const [minLon, minLat, maxLon, maxLat] = roi;
  return [(minLon + maxLon) / 2, (minLat + maxLat) / 2];
}

export const TENANTS: Tenant[] = [
  // Phase 1 pilot — Nigerian states (active=true)
  { id: 'kebbi',     name: 'Kebbi State',     type: 'ng_state', country: 'nigeria', capital: 'Birnin Kebbi', conflict_risk: 'critical', active: true,  priority: 1, deployment_phase: 1, centroid: centroid([3.60, 10.80, 5.50, 13.20]) },
  { id: 'benue',     name: 'Benue State',     type: 'ng_state', country: 'nigeria', capital: 'Makurdi',      conflict_risk: 'critical', active: true,  priority: 2, deployment_phase: 1, centroid: centroid([7.70, 6.30, 10.00, 8.10]) },
  { id: 'plateau',   name: 'Plateau State',   type: 'ng_state', country: 'nigeria', capital: 'Jos',          conflict_risk: 'critical', active: true,  priority: 3, deployment_phase: 1, centroid: centroid([8.30, 8.40, 10.20, 10.50]) },
  { id: 'kaduna',    name: 'Kaduna State',    type: 'ng_state', country: 'nigeria', capital: 'Kaduna',       conflict_risk: 'high',     active: true,  priority: 4, deployment_phase: 1, centroid: centroid([6.90, 9.20, 9.40, 11.60]) },
  { id: 'niger',     name: 'Niger State',     type: 'ng_state', country: 'nigeria', capital: 'Minna',        conflict_risk: 'high',     active: true,  priority: 5, deployment_phase: 1, centroid: centroid([3.50, 8.40, 7.50, 12.20]) },
  { id: 'zamfara',   name: 'Zamfara State',   type: 'ng_state', country: 'nigeria', capital: 'Gusau',        conflict_risk: 'critical', active: true,  priority: 6, deployment_phase: 1, centroid: centroid([5.50, 11.00, 7.70, 13.40]) },

  // Phase 2 — Nigerian states
  { id: 'kano',      name: 'Kano State',      type: 'ng_state', country: 'nigeria', capital: 'Kano',     conflict_risk: 'high',   active: false, priority: 7,  deployment_phase: 2, centroid: centroid([8.10, 11.20, 9.80, 12.80]) },
  { id: 'katsina',   name: 'Katsina State',   type: 'ng_state', country: 'nigeria', capital: 'Katsina',  conflict_risk: 'high',   active: false, priority: 8,  deployment_phase: 2, centroid: centroid([6.50, 11.40, 9.10, 13.80]) },
  { id: 'sokoto',    name: 'Sokoto State',    type: 'ng_state', country: 'nigeria', capital: 'Sokoto',   conflict_risk: 'high',   active: false, priority: 9,  deployment_phase: 2, centroid: centroid([4.10, 12.20, 6.50, 13.90]) },
  { id: 'nasarawa',  name: 'Nasarawa State',  type: 'ng_state', country: 'nigeria', capital: 'Lafia',    conflict_risk: 'critical', active: true,  priority: 7,  deployment_phase: 1, centroid: centroid([7.70, 7.70, 9.60, 9.30]) },
  { id: 'kogi',      name: 'Kogi State',      type: 'ng_state', country: 'nigeria', capital: 'Lokoja',   conflict_risk: 'medium', active: false, priority: 11, deployment_phase: 2, centroid: centroid([5.70, 6.40, 8.00, 8.70]) },
  { id: 'kwara',     name: 'Kwara State',     type: 'ng_state', country: 'nigeria', capital: 'Ilorin',   conflict_risk: 'medium', active: false, priority: 12, deployment_phase: 2, centroid: centroid([3.60, 7.70, 6.70, 10.00]) },

  // Phase 3 — Nigerian states
  { id: 'taraba',      name: 'Taraba State',         type: 'ng_state', country: 'nigeria', capital: 'Jalingo',       conflict_risk: 'high',     active: false, priority: 13, deployment_phase: 3, centroid: centroid([10.00, 6.60, 12.70, 10.60]) },
  { id: 'adamawa',     name: 'Adamawa State',        type: 'ng_state', country: 'nigeria', capital: 'Yola',          conflict_risk: 'high',     active: false, priority: 14, deployment_phase: 3, centroid: centroid([11.50, 7.90, 13.80, 11.30]) },
  { id: 'gombe',       name: 'Gombe State',          type: 'ng_state', country: 'nigeria', capital: 'Gombe',         conflict_risk: 'medium',   active: false, priority: 15, deployment_phase: 3, centroid: centroid([10.20, 9.30, 12.10, 11.10]) },
  { id: 'bauchi',      name: 'Bauchi State',         type: 'ng_state', country: 'nigeria', capital: 'Bauchi',        conflict_risk: 'high',     active: false, priority: 16, deployment_phase: 3, centroid: centroid([9.00, 9.50, 11.50, 12.50]) },
  { id: 'yobe',        name: 'Yobe State',           type: 'ng_state', country: 'nigeria', capital: 'Damaturu',      conflict_risk: 'high',     active: false, priority: 17, deployment_phase: 3, centroid: centroid([10.30, 11.00, 14.70, 14.20]) },
  { id: 'borno',       name: 'Borno State',          type: 'ng_state', country: 'nigeria', capital: 'Maiduguri',     conflict_risk: 'critical', active: false, priority: 18, deployment_phase: 3, centroid: centroid([11.50, 10.00, 15.00, 14.50]) },
  { id: 'jigawa',      name: 'Jigawa State',         type: 'ng_state', country: 'nigeria', capital: 'Dutse',         conflict_risk: 'medium',   active: false, priority: 19, deployment_phase: 3, centroid: centroid([8.50, 11.50, 10.80, 13.60]) },
  { id: 'oyo',         name: 'Oyo State',            type: 'ng_state', country: 'nigeria', capital: 'Ibadan',        conflict_risk: 'medium',   active: false, priority: 20, deployment_phase: 3, centroid: centroid([2.70, 6.70, 5.20, 9.20]) },
  { id: 'ogun',        name: 'Ogun State',           type: 'ng_state', country: 'nigeria', capital: 'Abeokuta',      conflict_risk: 'low',      active: false, priority: 21, deployment_phase: 3, centroid: centroid([2.70, 6.40, 4.70, 7.70]) },
  { id: 'ondo',        name: 'Ondo State',           type: 'ng_state', country: 'nigeria', capital: 'Akure',         conflict_risk: 'medium',   active: false, priority: 22, deployment_phase: 3, centroid: centroid([4.10, 5.70, 6.10, 8.00]) },
  { id: 'osun',        name: 'Osun State',           type: 'ng_state', country: 'nigeria', capital: 'Osogbo',        conflict_risk: 'low',      active: false, priority: 23, deployment_phase: 3, centroid: centroid([4.10, 7.10, 5.20, 8.00]) },
  { id: 'ekiti',       name: 'Ekiti State',          type: 'ng_state', country: 'nigeria', capital: 'Ado Ekiti',     conflict_risk: 'low',      active: false, priority: 24, deployment_phase: 3, centroid: centroid([4.90, 7.40, 5.90, 8.20]) },
  { id: 'lagos',       name: 'Lagos State',          type: 'ng_state', country: 'nigeria', capital: 'Ikeja',         conflict_risk: 'low',      active: false, priority: 25, deployment_phase: 3, centroid: centroid([2.70, 6.30, 4.10, 6.80]) },
  { id: 'rivers',      name: 'Rivers State',         type: 'ng_state', country: 'nigeria', capital: 'Port Harcourt', conflict_risk: 'medium',   active: false, priority: 26, deployment_phase: 3, centroid: centroid([6.40, 4.30, 8.00, 5.70]) },
  { id: 'bayelsa',     name: 'Bayelsa State',        type: 'ng_state', country: 'nigeria', capital: 'Yenagoa',       conflict_risk: 'medium',   active: false, priority: 27, deployment_phase: 3, centroid: centroid([5.70, 4.30, 7.00, 5.10]) },
  { id: 'delta',       name: 'Delta State',          type: 'ng_state', country: 'nigeria', capital: 'Asaba',         conflict_risk: 'medium',   active: false, priority: 28, deployment_phase: 3, centroid: centroid([5.40, 5.00, 7.30, 6.60]) },
  { id: 'edo',         name: 'Edo State',            type: 'ng_state', country: 'nigeria', capital: 'Benin City',    conflict_risk: 'low',      active: false, priority: 29, deployment_phase: 3, centroid: centroid([5.00, 5.70, 6.90, 7.40]) },
  { id: 'anambra',     name: 'Anambra State',        type: 'ng_state', country: 'nigeria', capital: 'Awka',          conflict_risk: 'medium',   active: false, priority: 30, deployment_phase: 3, centroid: centroid([6.60, 5.80, 7.50, 6.80]) },
  { id: 'enugu',       name: 'Enugu State',          type: 'ng_state', country: 'nigeria', capital: 'Enugu',         conflict_risk: 'medium',   active: false, priority: 31, deployment_phase: 3, centroid: centroid([7.00, 6.00, 8.20, 7.30]) },
  { id: 'imo',         name: 'Imo State',            type: 'ng_state', country: 'nigeria', capital: 'Owerri',        conflict_risk: 'medium',   active: false, priority: 32, deployment_phase: 3, centroid: centroid([6.80, 5.00, 7.70, 6.10]) },
  { id: 'abia',        name: 'Abia State',           type: 'ng_state', country: 'nigeria', capital: 'Umuahia',       conflict_risk: 'low',      active: false, priority: 33, deployment_phase: 3, centroid: centroid([7.10, 4.80, 8.10, 5.90]) },
  { id: 'ebonyi',      name: 'Ebonyi State',         type: 'ng_state', country: 'nigeria', capital: 'Abakaliki',     conflict_risk: 'medium',   active: false, priority: 34, deployment_phase: 3, centroid: centroid([7.80, 5.70, 8.80, 6.80]) },
  { id: 'cross_river', name: 'Cross River State',    type: 'ng_state', country: 'nigeria', capital: 'Calabar',       conflict_risk: 'medium',   active: false, priority: 35, deployment_phase: 3, centroid: centroid([7.80, 4.90, 9.60, 7.00]) },
  { id: 'akwa_ibom',   name: 'Akwa Ibom State',      type: 'ng_state', country: 'nigeria', capital: 'Uyo',           conflict_risk: 'low',      active: false, priority: 36, deployment_phase: 3, centroid: centroid([7.30, 4.30, 8.50, 5.60]) },
  { id: 'fct',         name: 'Federal Capital Territory', type: 'ng_fct', country: 'nigeria', capital: 'Abuja',      conflict_risk: 'low',      active: false, priority: 37, deployment_phase: 3, centroid: centroid([6.70, 8.30, 8.10, 9.30]) },

  // ECOWAS member countries
  { id: 'ghana',         name: 'Ghana',            type: 'ecowas_country', country: 'ghana',         capital: 'Accra',         conflict_risk: 'low',      active: false, priority: 1,  deployment_phase: 2, centroid: centroid([-3.50, 4.70, 1.20, 11.20]) },
  { id: 'senegal',       name: 'Senegal',          type: 'ecowas_country', country: 'senegal',       capital: 'Dakar',         conflict_risk: 'low',      active: false, priority: 2,  deployment_phase: 2, centroid: centroid([-17.50, 12.30, -11.30, 15.70]) },
  { id: 'cote_divoire',  name: "Côte d'Ivoire",    type: 'ecowas_country', country: 'cote_divoire',  capital: 'Yamoussoukro',  conflict_risk: 'medium',   active: false, priority: 3,  deployment_phase: 3, centroid: centroid([-8.70, 4.30, -2.50, 10.80]) },
  { id: 'mali',          name: 'Mali',             type: 'ecowas_country', country: 'mali',          capital: 'Bamako',        conflict_risk: 'critical', active: false, priority: 4,  deployment_phase: 3, centroid: centroid([-4.30, 10.10, 4.30, 25.00]) },
  { id: 'burkina_faso',  name: 'Burkina Faso',     type: 'ecowas_country', country: 'burkina_faso',  capital: 'Ouagadougou',   conflict_risk: 'critical', active: false, priority: 5,  deployment_phase: 3, centroid: centroid([-5.50, 9.40, 2.40, 15.10]) },
  { id: 'niger_country', name: 'Niger Republic',   type: 'ecowas_country', country: 'niger',         capital: 'Niamey',        conflict_risk: 'critical', active: false, priority: 6,  deployment_phase: 3, centroid: centroid([0.20, 11.70, 15.90, 23.50]) },
  { id: 'guinea',        name: 'Guinea',           type: 'ecowas_country', country: 'guinea',        capital: 'Conakry',       conflict_risk: 'medium',   active: false, priority: 7,  deployment_phase: 3, centroid: centroid([-15.10, 7.20, -7.60, 12.70]) },
  { id: 'sierra_leone',  name: 'Sierra Leone',     type: 'ecowas_country', country: 'sierra_leone',  capital: 'Freetown',      conflict_risk: 'low',      active: false, priority: 8,  deployment_phase: 3, centroid: centroid([-13.30, 6.90, -10.30, 10.00]) },
  { id: 'liberia',       name: 'Liberia',          type: 'ecowas_country', country: 'liberia',       capital: 'Monrovia',      conflict_risk: 'low',      active: false, priority: 9,  deployment_phase: 3, centroid: centroid([-11.50, 4.40, -7.40, 8.60]) },
  { id: 'gambia',        name: 'The Gambia',       type: 'ecowas_country', country: 'gambia',        capital: 'Banjul',        conflict_risk: 'low',      active: false, priority: 10, deployment_phase: 3, centroid: centroid([-16.90, 13.00, -13.80, 13.90]) },
  { id: 'guinea_bissau', name: 'Guinea-Bissau',    type: 'ecowas_country', country: 'guinea_bissau', capital: 'Bissau',        conflict_risk: 'medium',   active: false, priority: 11, deployment_phase: 3, centroid: centroid([-16.70, 10.90, -13.70, 12.70]) },
  { id: 'cabo_verde',    name: 'Cabo Verde',       type: 'ecowas_country', country: 'cabo_verde',    capital: 'Praia',         conflict_risk: 'low',      active: false, priority: 12, deployment_phase: 3, centroid: centroid([-25.40, 14.80, -22.70, 17.20]) },
  { id: 'togo',          name: 'Togo',             type: 'ecowas_country', country: 'togo',          capital: 'Lomé',          conflict_risk: 'medium',   active: false, priority: 13, deployment_phase: 3, centroid: centroid([-0.20, 6.10, 1.80, 11.10]) },
  { id: 'benin_country', name: 'Benin Republic',   type: 'ecowas_country', country: 'benin',         capital: 'Porto-Novo',    conflict_risk: 'medium',   active: false, priority: 14, deployment_phase: 3, centroid: centroid([0.80, 6.20, 3.90, 12.40]) },
  { id: 'mauritania',    name: 'Mauritania',       type: 'ecowas_country', country: 'mauritania',    capital: 'Nouakchott',    conflict_risk: 'medium',   active: false, priority: 15, deployment_phase: 3, centroid: centroid([-17.10, 14.70, -4.80, 27.30]) },
];

export const RISK_RGB: Record<ConflictRisk, [number, number, number]> = {
  critical: [193, 68, 14],
  high:     [201, 125, 0],
  medium:   [240, 175, 60],
  low:      [82, 183, 136],
};

export const RISK_HEX: Record<ConflictRisk, string> = {
  critical: '#c1440e',
  high:     '#c97d00',
  medium:   '#f0af3c',
  low:      '#52b788',
};

export const KEBBI_CENTER: [number, number] = centroid([3.60, 10.80, 5.50, 13.20]);
