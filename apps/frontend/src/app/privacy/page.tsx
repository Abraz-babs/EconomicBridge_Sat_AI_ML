import type { Metadata } from 'next';

import LegalPage from '@/components/legal/LegalPage';
import { PRIVACY_HTML, PRIVACY_TITLE, PRIVACY_UPDATED } from '@/components/legal/content';

export const metadata: Metadata = {
  title: 'Privacy Notice — EconomicBridge',
  description:
    'What personal data EconomicBridge collects, the messages it sends, who it is shared with, how long it is kept, and your rights under the Nigeria Data Protection Act 2023.',
};

export default function PrivacyPage() {
  return <LegalPage title={PRIVACY_TITLE} updated={PRIVACY_UPDATED} html={PRIVACY_HTML} />;
}
