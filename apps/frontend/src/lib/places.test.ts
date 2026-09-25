import { describe, expect, it } from 'vitest';

import { describePlace, type NearestPlace } from './places';

const place = (over: Partial<NearestPlace> = {}): NearestPlace => ({
  name: 'Kurmin Kaya', ward: 'Libata', lga: 'Kagarko', distance_km: 1.04,
  direction: 'SE', location: { lon: 7.7, lat: 9.4 }, ...over,
});

describe('describePlace — the field-directions wording on every alert', () => {
  it('gives distance and direction from the named village, with its ward', () => {
    expect(describePlace(place())).toBe('1.0 km SE of Kurmin Kaya, Libata ward');
  });

  it('says "at" when the point is at the village', () => {
    expect(describePlace(place({ direction: null }))).toBe('at Kurmin Kaya, Libata ward');
  });

  it('does not repeat a ward that has the village\'s own name', () => {
    expect(describePlace(place({ ward: 'Kurmin Kaya' }))).toBe('1.0 km SE of Kurmin Kaya');
    expect(describePlace(place({ ward: null }))).toBe('1.0 km SE of Kurmin Kaya');
  });

  it('returns null when there is no exact point to describe', () => {
    expect(describePlace(null)).toBeNull();
    expect(describePlace(undefined)).toBeNull();
  });
});
