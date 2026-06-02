'use client';

import AidCoverageUploadCard from './AidCoverageUploadCard';
import CropPriceUploadCard from './CropPriceUploadCard';
import SchedulerPanel from './SchedulerPanel';
import SmsLanguagePreviewCard from './SmsLanguagePreviewCard';
import SubscriberBulkUploadCard from './SubscriberBulkUploadCard';


const orgs = [
  {
    name: 'CARE International',
    type: 'NGO / Aid Organization',
    perms: [
      { label: 'Poverty View', cls: 'aperm--ngo' },
      { label: 'Disaster Ops', cls: 'aperm--ngo' },
      { label: 'Agri Feed', cls: 'aperm--ngo' },
      { label: 'Reports — Limited', cls: 'aperm--limited' },
    ],
  },
  {
    name: 'Federal Ministry — Nigeria',
    type: 'National Government',
    perms: [
      { label: 'Sovereign Data', cls: 'aperm--gov' },
      { label: 'Poverty Full', cls: 'aperm--gov' },
      { label: 'Disaster Full', cls: 'aperm--gov' },
      { label: 'Agri Full', cls: 'aperm--gov' },
      { label: 'Policy Reports', cls: 'aperm--gov' },
    ],
  },
  {
    name: 'OCHA / UN Humanitarian',
    type: 'International Body',
    perms: [
      { label: 'Cross-Border', cls: 'aperm--un' },
      { label: 'All Regions', cls: 'aperm--un' },
      { label: 'Raw Data Export', cls: 'aperm--un' },
      { label: 'API Access', cls: 'aperm--un' },
    ],
  },
  {
    name: 'MIT Poverty Lab',
    type: 'Research Institution',
    perms: [
      { label: 'Anonymised Data', cls: 'aperm--research' },
      { label: 'Historical Archive', cls: 'aperm--research' },
      { label: 'Model Access', cls: 'aperm--research' },
      { label: 'No PII', cls: 'aperm--restricted' },
    ],
  },
];


export default function AdminPanel() {
  return (
    <div className="admin-stack">
      <SchedulerPanel />
      <AidCoverageUploadCard />
      <CropPriceUploadCard />
      <SubscriberBulkUploadCard />
      <SmsLanguagePreviewCard />

      <div className="panel anim a1">
        <div className="panel-header">
          <span className="panel-title">Organisation Permission Manager</span>
          <span className="panel-meta">
            Admin-controlled access · 12 organisations registered
          </span>
        </div>
        <div className="admin-grid">
          {orgs.map((org) => (
            <div key={org.name} className="admin-org-card">
              <div className="aorg-name">{org.name}</div>
              <div className="aorg-type">{org.type}</div>
              <div className="aorg-perms">
                {org.perms.map((p) => (
                  <span key={p.label} className={`aperm ${p.cls}`}>
                    {p.label}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="admin-footer">
          All permission changes are audit-logged. Data sovereignty rules
          enforced per region. PII access requires DPA agreement on file.
        </div>
      </div>
    </div>
  );
}
