import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

// Unit tests for the pure helpers every panel leans on (provenance badges,
// coordinates, money, field-direction wording). Node environment: nothing here
// needs a browser, and nothing here touches the live site.
export default defineConfig({
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
