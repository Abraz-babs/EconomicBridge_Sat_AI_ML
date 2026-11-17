'use client';

/**
 * The storm room's three views: what fell (the storm day, measured by NASA
 * IMERG), what is coming (the ECMWF forecast), and how the forecast did (the
 * two set side by side, day by day). Storm day stays the default; each new
 * view was added beside it, never in its place.
 */

export type Room = 'storm' | 'forecast' | 'check';

export default function RoomSwitch({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  return (
    <div className="fc-mode fc-mode--rooms" role="group" aria-label="Storm room view">
      <button type="button" aria-pressed={room === 'storm'} onClick={() => onRoom('storm')}>
        Storm day · what fell
      </button>
      <button type="button" aria-pressed={room === 'forecast'} onClick={() => onRoom('forecast')}>
        Next 15 days · forecast
      </button>
      <button type="button" aria-pressed={room === 'check'} onClick={() => onRoom('check')}>
        Forecast check
      </button>
    </div>
  );
}
