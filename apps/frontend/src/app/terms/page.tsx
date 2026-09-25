import type { Metadata } from 'next';

import LegalPage from '@/components/legal/LegalPage';
import { TERMS_HTML, TERMS_TITLE, TERMS_UPDATED } from '@/components/legal/content';

export const metadata: Metadata = {
  title: 'Terms of Use — EconomicBridge',
  description:
    'The terms for using economicbridge.org and the EconomicBridge platform, operated by Bizra Farms Integrated Nigeria Limited.',
};

export default function TermsPage() {
  return <LegalPage title={TERMS_TITLE} updated={TERMS_UPDATED} html={TERMS_HTML} />;
}
