'use client';

/**
 * The storm room's two views: what fell (the storm day, measured by NASA IMERG)
 * and what is coming (the ECMWF forecast). Storm day stays the default; the
 * forecast is added beside it, never in its place.
 */

export type Room = 'storm' | 'forecast';

export default function RoomSwitch({ room, onRoom }: { room: Room; onRoom: (r: Room) => void }) {
  return (
    <div className="fc-mode" role="group" aria-label="Storm room view">
      <button type="button" aria-pressed={room === 'storm'} onClick={() => onRoom('storm')}>
        Storm day · what fell
      </button>
      <button type="button" aria-pressed={room === 'forecast'} onClick={() => onRoom('forecast')}>
        Next 15 days · forecast
      </button>
    </div>
  );
}
