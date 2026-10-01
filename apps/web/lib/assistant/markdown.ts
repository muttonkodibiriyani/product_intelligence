/**
 * The strict Markdown subset an answer may use: paragraphs, headings (shown as bold lines),
 * bullet and numbered lists, pipe tables, **bold**, and `[[product:<id>]]` tokens. Everything
 * else stays literal text. The output is data for React to render, never HTML, so nothing in an
 * answer can become a link, an image or markup (the server already strips those; design §7.5).
 */
import { unescapeMd } from './types';

export type Inline =
  | { readonly t: 'text'; readonly v: string }
  | { readonly t: 'strong'; readonly c: readonly Inline[] }
  | { readonly t: 'product'; readonly id: string };

export type Block =
  | { readonly t: 'p' | 'h'; readonly c: readonly Inline[] }
  | { readonly t: 'ul' | 'ol'; readonly items: readonly (readonly Inline[])[] }
  | {
      readonly t: 'table';
      readonly head: readonly (readonly Inline[])[];
      readonly rows: readonly (readonly (readonly Inline[])[])[];
    };

const TOKEN = /\\([\\`*_{}[\]()#+!|<>~&"])|\*\*(.+?)\*\*|\[\[product:([^\]\s]{1,200})\]\]/g;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const push = (v: string) => {
    if (v === '') return;
    const last = out.at(-1);
    if (last?.t === 'text') out[out.length - 1] = { t: 'text', v: last.v + v };
    else out.push({ t: 'text', v });
  };
  let at = 0;
  for (const m of text.matchAll(TOKEN)) {
    push(text.slice(at, m.index));
    if (m[1] !== undefined) push(m[1]);
    else if (m[2] !== undefined) out.push({ t: 'strong', c: parseInline(m[2]) });
    else if (m[3] !== undefined) out.push({ t: 'product', id: m[3] });
    at = m.index + m[0].length;
  }
  push(text.slice(at));
  return out;
}

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d{1,3}[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

const cells = (line: string): Inline[][] =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/(?<!\\)\|$/, '')
    .split(/(?<!\\)\|/)
    .map((cell) => parseInline(cell.trim()));

export function parseAnswer(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length > 0) blocks.push({ t: 'p', c: parseInline(para.join(' ')) });
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    if (line.trim() === '') {
      flush();
      continue;
    }
    if (TABLE_ROW.test(line) && TABLE_RULE.test(lines[i + 1] ?? '')) {
      flush();
      const head = cells(line);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(lines[i] ?? '')) rows.push(cells(lines[i++] ?? ''));
      i -= 1;
      blocks.push({ t: 'table', head, rows });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({ t: 'h', c: parseInline(heading[1] ?? '') });
      continue;
    }
    const list = BULLET.exec(line) ? 'ul' : NUMBERED.exec(line) ? 'ol' : null;
    if (list) {
      flush();
      const re = list === 'ul' ? BULLET : NUMBERED;
      const items: Inline[][] = [];
      while (i < lines.length && re.test(lines[i] ?? '')) {
        items.push(parseInline(re.exec(lines[i] ?? '')?.[1] ?? ''));
        i++;
      }
      i -= 1;
      blocks.push({ t: list, items });
      continue;
    }
    para.push(line.trim());
  }
  flush();
  return blocks;
}

/** Plain text of inlines (for tests and accessible names). */
export const inlineText = (c: readonly Inline[]): string =>
  c.map((x) => (x.t === 'text' ? x.v : x.t === 'strong' ? inlineText(x.c) : `[${x.id}]`)).join('');

export { unescapeMd };
