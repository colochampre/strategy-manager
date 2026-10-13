const DASH = "—";

/**
 * A figure that is absent (null) is an em dash with its reason for a screen
 * reader; one that is present but cannot be read says so. Neither is a zero.
 */
export function Absent({ reason }: { reason: string }) {
  return (
    <>
      <span aria-hidden="true">{DASH}</span>
      <span className="sr-only">{reason}</span>
    </>
  );
}
