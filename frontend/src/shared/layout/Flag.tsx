import { useId } from "react";

/** The two languages the panel speaks, each drawn as its country's flag: English as the United States, Spanish as Argentina. */
export type FlagCountry = "us" | "ar";

const SIZE = 20;
const US_STRIPE = SIZE / 13;
const US_CANTON_WIDTH = 9;
const US_CANTON_HEIGHT = US_STRIPE * 7;
const AR_BAND = SIZE / 3;

/**
 * A round flag, 18 px, clipped to a circle. Decorative: the button around it carries the name.
 * The colours are the theme's flag tokens, never literals.
 */
export function Flag({ country }: { country: FlagCountry }) {
  const clipId = useId();
  return (
    <svg
      data-flag={country}
      aria-hidden="true"
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="size-4.5 shrink-0 rounded-full"
    >
      <clipPath id={clipId}>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={SIZE / 2} />
      </clipPath>
      <g clipPath={`url(#${clipId})`}>{country === "us" ? <UnitedStates /> : <Argentina />}</g>
    </svg>
  );
}

function UnitedStates() {
  return (
    <>
      <rect width={SIZE} height={SIZE} className="fill-flag-white" />
      {Array.from({ length: 7 }, (_, index) => (
        <rect key={index} y={index * 2 * US_STRIPE} width={SIZE} height={US_STRIPE} className="fill-flag-us-red" />
      ))}
      <rect width={US_CANTON_WIDTH} height={US_CANTON_HEIGHT} className="fill-flag-us-blue" />
      {[2.5, 6.5].flatMap((cx) =>
        [2.5, 5.5, 8.5].map((cy) => <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={0.6} className="fill-flag-white" />),
      )}
    </>
  );
}

function Argentina() {
  return (
    <>
      <rect width={SIZE} height={SIZE} className="fill-flag-ar-blue" />
      <rect y={AR_BAND} width={SIZE} height={AR_BAND} className="fill-flag-white" />
      <circle cx={SIZE / 2} cy={SIZE / 2} r={1.9} className="fill-flag-ar-sun" />
    </>
  );
}
