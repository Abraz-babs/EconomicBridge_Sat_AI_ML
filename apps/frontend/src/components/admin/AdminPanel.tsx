'use client';

import AccountActivityCard from './AccountActivityCard';
import AgencyAlertsCard from './AgencyAlertsCard';
import AidCoverageUploadCard from './AidCoverageUploadCard';
import CropPriceUploadCard from './CropPriceUploadCard';
import SchedulerPanel from './SchedulerPanel';
import SmsLanguagePreviewCard from './SmsLanguagePreviewCard';
import SubscriberBulkUploadCard from './SubscriberBulkUploadCard';
import TenantRegistryCard from './TenantRegistryCard';
import ScheduledReportsCard from './ScheduledReportsCard';


// The "Organisation Permission Manager" card that lived here listed four
// invented organisations (CARE International, the Federal Ministry, OCHA, MIT
// Poverty Action Lab) and "12 organisations registered". Removed 2026-09-29:
// the real organisations and their module access are in the Tenant Registry
// and Account Activity cards above.


export default function AdminPanel() {
  return (
    <div className="admin-stack">
      <TenantRegistryCard />
      <AccountActivityCard />
      <AgencyAlertsCard />
      <ScheduledReportsCard />
      <SchedulerPanel />
      <AidCoverageUploadCard />
      <CropPriceUploadCard />
      <SubscriberBulkUploadCard />
      <SmsLanguagePreviewCard />

    </div>
  );
}
