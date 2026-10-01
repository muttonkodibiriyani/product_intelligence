/**
 * Hands a downloaded Blob to the browser as a file. The object URL is same-origin and short-lived;
 * it is revoked a little after the click, so a slow browser can still read a large file from it.
 */
export const REVOKE_AFTER_MS = 10_000;

export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS);
}
