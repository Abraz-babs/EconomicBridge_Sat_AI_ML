'use client';

import { useEffect, useState } from 'react';

/**
 * Returns a rotating slice of `items` so an overview widget cycles through its
 * pool over time instead of showing the same rows on every visit. Advances the
 * window start by `size` every `intervalMs`, wrapping around. Stable when the
 * pool fits in one window (no needless re-renders).
 */
export function useRotatingWindow<T>(
  items: T[],
  size: number,
  intervalMs = 9000,
): T[] {
  const [start, setStart] = useState(0);

  useEffect(() => {
    if (items.length <= size) return; // nothing to rotate
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        setStart((s) => (s + size) % items.length);
      }
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [items.length, size, intervalMs]);

  if (items.length <= size) return items;
  const safeStart = start % items.length;
  // Wrap-around slice so the window is always full.
  return Array.from({ length: size }, (_, i) => items[(safeStart + i) % items.length]);
}
