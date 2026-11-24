import { useQuery } from "@tanstack/react-query";

/** A short commit hash, as `build.txt` names the bundle being served. Anything else (an HTML fallback, an error page) is not a tag. */
const SHORT_COMMIT = /^[0-9a-f]{7,12}$/;

async function readBuildTag(): Promise<string | null> {
  try {
    const response = await fetch("/build.txt");
    if (!response.ok) return null;
    const text = (await response.text()).trim();
    return SHORT_COMMIT.test(text) ? text : null;
  } catch {
    // Development has no `build.txt`, and a network error is no reason to say anything about the build.
    return null;
  }
}

/** The commit of the bundle being served, or `null` when `/build.txt` is absent or is not a short commit. Read once. */
export function useBuildTag(): string | null {
  const { data } = useQuery({
    queryKey: ["build-tag"],
    queryFn: readBuildTag,
    staleTime: Infinity,
    retry: false,
  });
  return data ?? null;
}
