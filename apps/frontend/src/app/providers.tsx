'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactNode, useState } from 'react';

import { AuthProvider } from '@/context/AuthContext';
import { TenantProvider } from '@/context/TenantContext';

/**
 * Wraps the entire app in client-side data + tenant context.
 *
 * QueryClient is instantiated once per browser session via useState — the
 * component re-renders, the client survives. Defaults:
 *   - staleTime: 30s (alerts feel fresh without thrashing the API)
 *   - retry: 1 (avoid silent retries on slow networks; failures bubble to UI)
 *   - refetchOnWindowFocus: false (we have an explicit refetch in the UI)
 */
export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TenantProvider>{children}</TenantProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
