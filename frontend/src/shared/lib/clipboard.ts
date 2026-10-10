/**
 * Writes `text` to the clipboard and answers whether it worked. It answers false when the clipboard API
 * or `writeText` does not exist (the API is only there on HTTPS and on localhost) and when the write is
 * refused, and it never throws and never logs: the text may be the webhook secret. There is no fallback
 * to `document.execCommand("copy")`, which would put the text into a second place in the document.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    const clipboard = navigator.clipboard as Clipboard | undefined;
    if (clipboard === undefined || typeof clipboard.writeText !== "function") return false;
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
