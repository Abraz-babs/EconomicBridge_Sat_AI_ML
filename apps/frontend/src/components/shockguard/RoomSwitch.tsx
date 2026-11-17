'use client';

/**
 * The storm room's three views: what fell (the storm day, measured by NASA
 * IMERG), what is coming (the ECMWF forecast), and how the forecast did (the
 * two set side by side, day by day). Storm day stays the default; each new
 * view was added beside it, never in its place.
 *
 * On a phone the second half of each label is dropped (".fc-mode-more"), so the
 * three fit on the one line the two used to.
 */

export type Room = 'storm' | 'forecast' | 'check';

export default function RoomSwitch({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  return (
    <div className="fc-mode fc-mode--rooms" role="group" aria-label="Storm room view">
      <button type="button" aria-pressed={room === 'storm'} onClick={() => onRoom('storm')}>
        Storm day<span className="fc-mode-more"> · what fell</span>
      </button>
      <button type="button" aria-pressed={room === 'forecast'} onClick={() => onRoom('forecast')}>
        Next 15 days<span className="fc-mode-more"> · forecast</span>
      </button>
      <button type="button" aria-pressed={room === 'check'} onClick={() => onRoom('check')}>
        Forecast check
      </button>
    </div>
  );
}
