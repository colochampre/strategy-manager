import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { exchangeName } from "@/shared/exchanges/exchange-name";
import { cn } from "@/shared/lib/cn";

interface ExchangeWordmarkProps {
  exchange: string;
  /** Sets the height; the width follows the logotype's own proportions. */
  className?: string | undefined;
}

interface Wordmark {
  viewBox: string;
  letters: ReactNode;
}

/**
 * The letters of each exchange's logotype, copied by the owner from the header of the exchange's own site on
 * 2026-10-18 (owner decision 77). Only the letters are kept: Binance's and Pionex's brand figure is left out.
 * Bybit's letters are drawn in the panel's text colour, because its own `#15192a` cannot be seen on the dark
 * panel; its `I` keeps Bybit's orange, as Bybit's own dark mode draws it. Colours are the palette's tokens.
 */
const WORDMARKS: Readonly<Record<string, Wordmark>> = {
  binance: {
    viewBox: "148.4 29.7 484.6 69.8",
    letters: (
      <g className="fill-brand-binance" transform="translate(.55)">
        <path d="m148.37 30.68h31.12q11.58 0 17.52 6a15.5 15.5 0 0 1 4.59 11.32v.19a16.67 16.67 0 0 1 -.71 5.08 15.6 15.6 0 0 1 -1.910 4 14.77 14.77 0 0 1 -2.76 3.12 17.92 17.92 0 0 1 -3.39 2.3 22.66 22.66 0 0 1 9.17 6q3.34 3.8 3.34 10.5v.19a17.44 17.44 0 0 1 -1.77 8.06 15.72 15.72 0 0 1 -5.07 5.76 24.05 24.05 0 0 1 -7.95 3.45 42.7 42.7 0 0 1 -10.29 1.15h-31.89zm28 27.14a15.39 15.39 0 0 0 7.77-1.68 5.8 5.8 0 0 0 2.86-5.42v-.19a5.93 5.93 0 0 0 -2.49-5.13q-2.49-1.77-7.19-1.77h-14.56v14.19zm3.93 27.05a14.2 14.2 0 0 0 7.7-1.77 6.08 6.08 0 0 0 2.78-5.52v-.19a6.31 6.31 0 0 0 -2.59-5.32q-2.58-2-8.34-2h-17.09v14.8z" />
        <path d="m223.88 30.68h14.77v67.14h-14.77z" />
        <path d="m261 30.68h13.62l31.48 41.32v-41.32h14.58v67.14h-12.57l-32.51-42.68v42.68h-14.6z" />
        <path d="m365.4 30.2h13.6l28.77 67.62h-15.42l-6.14-15.06h-28.39l-6.14 15.06h-15.06zm15.54 39.52-8.94-21.78-8.9 21.78z" />
        <path d="m423.74 30.68h13.62l31.46 41.32v-41.32h14.58v67.14h-12.57l-32.51-42.68v42.68h-14.58z" />
        <path d="m536.56 99a34.93 34.93 0 0 1 -13.72-2.68 33.17 33.17 0 0 1 -18.13-18.32 35.54 35.54 0 0 1 -2.59-13.53v-.19a34.84 34.84 0 0 1 9.79-24.51 33.23 33.23 0 0 1 11-7.48 35.9 35.9 0 0 1 14.19-2.73 44.49 44.49 0 0 1 8.58.77 35.66 35.66 0 0 1 7.06 2.11 30.5 30.5 0 0 1 5.85 3.26 39.52 39.52 0 0 1 5 4.22l-9.39 10.84a35.71 35.71 0 0 0 -8-5.57 20.47 20.47 0 0 0 -9.16-2 18.58 18.58 0 0 0 -14 6.14 21.09 21.09 0 0 0 -4.04 6.67 22.87 22.87 0 0 0 -1.43 8.11v.19a23.21 23.21 0 0 0 1.43 8.1 21.32 21.32 0 0 0 4 6.71 18.46 18.46 0 0 0 14 6.24 20.52 20.52 0 0 0 9.73-2.11 37.62 37.62 0 0 0 7.91-5.76l9.4 9.5a47.93 47.93 0 0 1 -5.37 5 32 32 0 0 1 -6.09 3.79 31.56 31.56 0 0 1 -7.24 2.39 43.11 43.11 0 0 1 -8.78.84z" />
        <path d="m581.47 30.68h50.53v13.14h-36v13.62h31.7v13.14h-31.65v14.1h36.45v13.14h-51z" />
      </g>
    ),
  },
  bybit: {
    viewBox: "0 3 87 29",
    letters: (
      <>
        <path className="fill-brand-bybit" d="M62.008 25.357V3h4.494v22.357z" />
        <path
          className="fill-ink"
          d="M9.634 31.998H0V9.641h9.247c4.494 0 7.112 2.45 7.112 6.28 0 2.48-1.682 4.083-2.846 4.617 1.39.627 3.168 2.04 3.168 5.024 0 4.175-2.94 6.436-7.047 6.436zm-.743-18.463H4.494v5.15H8.89c1.907 0 2.974-1.036 2.974-2.576 0-1.537-1.067-2.574-2.974-2.574zm.29 9.075H4.495v5.496h4.688c2.037 0 3.005-1.256 3.005-2.764 0-1.507-.97-2.732-3.005-2.732zM30.388 22.83v9.168h-4.462V22.83L19.007 9.641h4.882l4.3 9.012 4.235-9.012h4.881zM50.046 31.998h-9.634V9.641h9.246c4.494 0 7.113 2.45 7.113 6.28 0 2.48-1.682 4.083-2.846 4.617 1.39.627 3.168 2.04 3.168 5.024 0 4.175-2.94 6.436-7.047 6.436zm-.743-18.463h-4.397v5.15h4.397c1.907 0 2.974-1.036 2.974-2.576 0-1.537-1.067-2.574-2.974-2.574zm.29 9.075h-4.688v5.496h4.688c2.038 0 3.006-1.256 3.006-2.764 0-1.507-.968-2.732-3.006-2.732zM80.986 13.536V32h-4.494V13.535H70.48V9.641h16.52v3.894z"
        />
      </>
    ),
  },
  pionex: {
    viewBox: "255.1 211.5 523.9 118",
    letters: (
      <g className="fill-brand-pionex">
        <path d="M301.7,226.5h-46.6v101.7h28.9v-26.6h17.8c27.8,0,45.3-14.4,45.3-37.5S329.6,226.5,301.7,226.5z M300,279h-16v-29.8h16c12,0,17.9,5.5,17.9,15S311.9,279,300,279z" />
        <path d="M374.4,240.8c10.2,0,16.9-6.4,16.9-15.1c0-8.3-6.7-14.2-16.9-14.2s-16.9,6.4-16.9,14.7S364.2,240.8,374.4,240.8z M360.5,328.2h27.7v-78.7h-27.7V328.2z" />
        <path d="M445.8,329.5c26.1,0,44.6-17,44.6-40.8s-18.5-40.5-44.6-40.5c-25.8,0-44.6,16.8-44.6,40.5S420,329.5,445.8,329.5z M445.8,307.6c-9.3,0-16.6-6.8-16.6-18.9s7.3-18.6,16.6-18.6s16.6,6.7,16.6,18.6S455.3,307.6,445.8,307.6z" />
        <path d="M554.7,248.2c-9.9,0-18.8,3.3-25.1,9.9v-8.6h-26.4v78.7H531v-38.1c0-13.1,6.8-18.6,15.7-18.6c8,0,13,4.8,13,16.1v40.5h27.7v-45C587.3,258.8,573.2,248.2,554.7,248.2z" />
        <path d="M686.6,289c0-26-18.9-40.8-42.3-40.8c-24.9,0-43.4,16.8-43.4,40.5s18.2,40.8,46.3,40.8c15,0,26.1-4.4,33.7-12.8l-14.6-15.1c-5.4,4.6-10.5,6.8-18.2,6.8c-10.2,0-17-4.6-19.4-12.6h57.4C686.3,293.6,686.6,291,686.6,289z M644.5,267.8c8.6,0,14.7,5.2,16.2,13.5h-32.3C629.9,273,635.9,267.8,644.5,267.8L644.5,267.8z" />
        <path d="M779,328.2l-30.2-40.4l29.2-38.4h-29.3l-14.6,19.9l-14-19.9h-31.2l29.1,39.4l-30,39.4h30l15.2-20.6l14.1,20.6H779z" />
      </g>
    ),
  },
};

/**
 * An exchange's name drawn as its own logotype, one image whose accessible name is the display name. An exchange
 * with no logotype here is written as its display name instead (owner decision 77, Q2).
 */
export function ExchangeWordmark({ exchange, className }: ExchangeWordmarkProps) {
  const { t, i18n } = useTranslation();
  const name = exchangeName(t, i18n, exchange);
  const wordmark = WORDMARKS[exchange];
  if (wordmark === undefined) return <span className={className}>{name}</span>;
  return (
    <svg
      role="img"
      aria-label={name}
      viewBox={wordmark.viewBox}
      xmlns="http://www.w3.org/2000/svg"
      className={cn("w-auto", className)}
    >
      {wordmark.letters}
    </svg>
  );
}
