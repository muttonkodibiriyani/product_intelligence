'use client';

import { useLocale, useTranslations } from 'next-intl';
import { Fragment } from 'react';
import { firstTable, isToolName, unavailableNote } from '@/lib/assistant/answer';
import { type Block, type Inline, parseAnswer } from '@/lib/assistant/markdown';
import { useReveal } from '@/lib/assistant/reveal';
import type { ChatAnswer, Citation, UntrustedBilingual } from '@/lib/assistant/types';
import { plain } from '@/lib/assistant/types';
import { ProductRef } from './product-ref';

const TH = 'px-2 py-1 text-start font-medium text-ink-2 whitespace-nowrap';
const TD = 'px-2 py-1 align-top';

function Inlines({ c }: { c: readonly Inline[] }) {
  return (
    <>
      {c.map((x, i) =>
        x.t === 'text' ? (
          <Fragment key={i}>{x.v}</Fragment>
        ) : x.t === 'strong' ? (
          <strong key={i}>
            <Inlines c={x.c} />
          </strong>
        ) : (
          <ProductRef key={i} id={x.id} />
        ),
      )}
    </>
  );
}

function BlockView({ b }: { b: Block }) {
  switch (b.t) {
    case 'p':
      return (
        <p>
          <Inlines c={b.c} />
        </p>
      );
    case 'h':
      return (
        <p className="font-semibold">
          <Inlines c={b.c} />
        </p>
      );
    case 'ul':
    case 'ol': {
      const List = b.t;
      return (
        <List className={`ps-5 ${b.t === 'ul' ? 'list-disc' : 'list-decimal'} space-y-0.5`}>
          {b.items.map((item, i) => (
            <li key={i}>
              <Inlines c={item} />
            </li>
          ))}
        </List>
      );
    }
    case 'table':
      return (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead className="border-b border-line">
              <tr>
                {b.head.map((h, i) => (
                  <th key={i} className={TH}>
                    <Inlines c={h} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {b.rows.map((row, r) => (
                <tr key={r} className="border-b border-line last:border-0">
                  {row.map((c, i) => (
                    <td key={i} className={`${TD} tabular-nums`}>
                      <Inlines c={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
}

function useBilingual() {
  const locale = useLocale();
  return (text: UntrustedBilingual) => plain(locale === 'ar' ? text.ar : text.en);
}

function CitationChip({ c, n }: { c: Citation; n: number }) {
  const t = useTranslations('assistant.answer');
  const tool = useTranslations('assistant.tools');
  const filters = Object.entries(c.filters).filter(
    ([, v]) => v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0),
  );
  return (
    <li>
      <details className="rounded-ctl border border-line-2 bg-surface px-2 py-1 text-xs">
        <summary className="cursor-pointer list-none">
          <span className="me-1 rounded bg-surface-2 px-1 font-medium tabular-nums">{n}</span>
          {isToolName(c.tool) ? tool(c.tool) : tool('other')} · {t('cutoff')}{' '}
          <bdi className="tabular-nums">{c.cutoff}</bdi>
          {c.cohort && (
            <>
              {' '}
              · <bdi>{plain(c.cohort.description)}</bdi> ({t('n', { n: c.cohort.n })})
            </>
          )}
        </summary>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-ink-2">
          <dt>{t('source')}</dt>
          <dd>
            <bdi dir="ltr">
              {c.tool} · API {c.apiVersion} · {t('dataset')} {c.datasetGeneration}
            </bdi>
          </dd>
          <dt>{t('market')}</dt>
          <dd>
            {c.market} · {c.currency}
          </dd>
          {filters.length > 0 && (
            <>
              <dt>{t('filters')}</dt>
              <dd>
                <bdi dir="ltr">
                  {filters
                    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
                    .join(' · ')}
                </bdi>
              </dd>
            </>
          )}
        </dl>
      </details>
    </li>
  );
}

/** One assistant answer: verified text revealed section by section, then its evidence. */
export function AnswerView({ answer, id }: { answer: ChatAnswer; id: string }) {
  const t = useTranslations('assistant.answer');
  const un = useTranslations('assistant.unavailable');
  const tool = useTranslations('assistant.tools');
  const bilingual = useBilingual();
  const blocks = answer.status === 'unavailable' ? [] : parseAnswer(answer.answerMd);
  const { shown, skip } = useReveal(blocks.length, id);
  const revealed = shown >= blocks.length;

  if (answer.status === 'unavailable') {
    return (
      <p role="alert" className="text-sm">
        {un(unavailableNote(answer.code))}
      </p>
    );
  }

  return (
    <div className="space-y-3 text-sm">
      {answer.status === 'unverified' && <p className="pill bg-butter text-butter-ink">{t('unverified')}</p>}
      <div className="space-y-2" aria-busy={!revealed}>
        {blocks.slice(0, shown).map((b, i) => (
          <BlockView key={i} b={b} />
        ))}
      </div>
      {!revealed && (
        <button
          type="button"
          onClick={skip}
          className="text-xs text-accent underline-offset-2 hover:underline focus-visible:outline-2"
        >
          {t('skip')}
        </button>
      )}

      {revealed && (
        <>
          {answer.status === 'unverified' &&
            answer.toolResults.map((r, i) => {
              const table = firstTable(r.data);
              if (!table) return null;
              return (
                <figure key={i} className="space-y-1">
                  <figcaption className="text-xs font-medium text-ink-2">
                    {isToolName(r.citation.tool) ? tool(r.citation.tool) : tool('other')}
                    {table.total > table.rows.length &&
                      ` · ${t('shown', { shown: table.rows.length, total: table.total })}`}
                  </figcaption>
                  <div className="overflow-x-auto">
                    <table className="min-w-full border-collapse text-xs">
                      <thead className="border-b border-line">
                        <tr>
                          {table.columns.map((c) => (
                            <th key={c} className={TH}>
                              <bdi dir="ltr">{c}</bdi>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {table.rows.map((row, r) => (
                          <tr key={r} className="border-b border-line last:border-0">
                            {row.map((v, c) => (
                              <td key={c} className={`${TD} tabular-nums`}>
                                <bdi>{v}</bdi>
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </figure>
              );
            })}

          {answer.notEnoughData.length > 0 && (
            <ul className="space-y-1">
              {answer.notEnoughData.map((n, i) => (
                <li key={i} className="rounded-ctl bg-sky px-2 py-1 text-xs text-sky-ink">
                  <span className="font-medium">{t('notEnough')}</span> · <bdi>{bilingual(n.detail)}</bdi>
                </li>
              ))}
            </ul>
          )}

          {answer.caveats.length > 0 && (
            <div className="text-xs text-ink-2">
              <p className="font-medium">{t('caveats')}</p>
              <ul className="list-disc ps-5">
                {answer.caveats.map((c, i) => (
                  <li key={i}>
                    <bdi>{bilingual(c)}</bdi>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {answer.citations.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-ink-2">{t('sources')}</p>
              <ol className="flex flex-wrap gap-1.5">
                {answer.citations.map((c, i) => (
                  <CitationChip key={i} c={c} n={i + 1} />
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}
