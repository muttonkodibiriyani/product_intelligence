import { retailerTone } from '../home/model';

/** The colour swatch in front of a retailer's name, so its bars and rows read as one. Decorative. */
export function RetailerDot({ id, side }: { id: string; side: 0 | 1 }) {
  return (
    <span
      aria-hidden
      className="inline-block size-2.5 shrink-0 rounded-full align-middle"
      style={{ background: retailerTone(id, side) }}
    />
  );
}
