import { useEffect, useState } from "react";

/**
 * `value`, once it has stopped changing for `delayMs`. A change restarts the wait, so two changes in quick
 * succession give one update, for the last; the timer is cleared on every change and on unmount.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
