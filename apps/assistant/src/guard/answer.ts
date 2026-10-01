/**
 * Server-side cleaning of the model's answer before it is stored or shown (design §7.5). The
 * UI also renders a strict Markdown subset; this is the second layer, so an injected link or
 * image never reaches a client even if the renderer regresses.
 * - Raw HTML, comments, images, links (inline and reference style), bare URLs (any of the
 *   schemes below) and email addresses are removed; a link keeps its text. A renderer with
 *   autolinking would otherwise turn them into links. The model is told not to write any of them, so nothing legitimate
 *   is lost: the UI links products from server data.
 * - `[[product:<id>]]` tokens survive only for ids that a tool returned; the rest become
 *   "a product". Surviving ids are returned in first-appearance order for thumbnails.
 */

const PRODUCT_TOKEN = /\[\[product:([^\]\s]{1,200})\]\]/g;
const HTML_COMMENT = /<!--[^]*?(?:-->|$)/g;
const HTML_TAG = /<\/?[A-Za-z][^>]*>?/g;
const IMAGE = /!\[[^\]]*\]\([^)]*\)?/g;
const INLINE_LINK = /\[([^\]]*)\]\([^)]*\)?/g;
const REFERENCE_DEF = /^[ \t]{0,3}\[[^\]]+\]:[ \t]*\S.*$/gm;
const BARE_URL = /\b(?:https?|ftp|file|data|javascript|vbscript|mailto|tel|sms):[^\s)]*/gi;
const EMAIL = /[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g;
const WWW = /\bwww\.[^\s)]+/gi;

export interface CleanAnswer {
  readonly markdown: string;
  readonly productIds: readonly string[];
  /** How many links, images, tags, URLs or unknown product tokens were removed. */
  readonly removed: number;
}

export function cleanAnswer(markdown: string, knownProductIds: ReadonlySet<string>): CleanAnswer {
  let removed = 0;
  const productIds: string[] = [];
  const count =
    (replacement: string | ((...groups: string[]) => string)) =>
    (...groups: string[]): string => {
      removed += 1;
      return typeof replacement === "string" ? replacement : replacement(...groups);
    };

  // Product tokens first, swapped for placeholders so the link patterns cannot touch them.
  const kept: string[] = [];
  let text = markdown.replace(/\uE000/g, "").replace(PRODUCT_TOKEN, (_whole, id: string) => {
    if (!knownProductIds.has(id)) {
      removed += 1;
      return "a product";
    }
    if (!productIds.includes(id)) productIds.push(id);
    kept.push(id);
    return `\uE000${String(kept.length - 1)}\uE000`;
  });

  text = text
    .replace(HTML_COMMENT, count(""))
    .replace(IMAGE, count(""))
    .replace(
      INLINE_LINK,
      count((_whole, label) => label),
    )
    .replace(REFERENCE_DEF, count(""))
    .replace(HTML_TAG, count(""))
    .replace(BARE_URL, count("[link removed]"))
    .replace(WWW, count("[link removed]"))
    .replace(EMAIL, count("[email removed]"));

  // Placeholders use a private-use character; any the model wrote itself is dropped first.
  text = text.replace(/\uE000(\d+)\uE000/g, (_whole, index: string) => {
    const id = kept[Number(index)];
    return id === undefined ? "" : `[[product:${id}]]`;
  });

  return { markdown: text.trim(), productIds, removed };
}
