'use client';

import { useLocale, useTranslations } from 'next-intl';
import { Fragment } from 'react';
import { firstTable, toolKey, unavailableNote } from '@/lib/assistant/answer';
import { evidenceCards, evidenceShares } from './evidence-model';
import { type Block, type Inline, parseAnswer } from '@/lib/assistant/markdown';
import { useReveal } from '@/lib/assistant/reveal';
import type { ChatAnswer, UntrustedBilingual } from '@/lib/assistant/types';
import { plain } from '@/lib/assistant/types';
import { EvidenceCards, ShareTiles, SourcePills } from './evidence';
import { ProductRef } from './product-ref';

const TH = 'th text-start whitespace-nowrap';
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

/** The answer's blocks; the first paragraph is the conclusion and reads a size up. */
function BlockView({ b, conclusion = false }: { b: Block; conclusion?: boolean }) {
  switch (b.t) {
    case 'p':
      return (
        <p className={conclusion ? 'text-base leading-normal font-medium text-ink' : undefined}>
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

/**
 * One assistant answer: the conclusion first, the evidence the tools returned (product cards,
 * per-shop shares), the rest of the verified text, then "From" pills that open the page each
 * number came from. The text is revealed block by block; the evidence comes with the first.
 */
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
      <p role="alert" className="rounded-ctl bg-rose px-4 py-3 text-sm">
        {un(unavailableNote(answer.code))}
      </p>
    );
  }

  const conclusion = blocks[0]?.t === 'p';
  const evidence = answer.toolResults.map((r) => ({ cards: evidenceCards(r), shares: evidenceShares(r) }));
  const hasEvidence = evidence.some((e) => e.cards.length > 0 || e.shares.length > 0);

  return (
    <div className="space-y-3 text-sm">
      {answer.status === 'unverified' && <p className="pill bg-butter text-butter-ink">{t('unverified')}</p>}
      <div className="space-y-2" aria-busy={!revealed}>
        {blocks.slice(0, shown).map((b, i) => (
          <Fragment key={i}>
            <BlockView b={b} conclusion={i === 0 && conclusion} />
            {i === 0 && hasEvidence && (
              <div className="space-y-3 py-1">
                {evidence.map((e, j) => (
                  <Fragment key={j}>
                    <ShareTiles shares={e.shares} />
                    <EvidenceCards cards={e.cards} />
                  </Fragment>
                ))}
              </div>
            )}
          </Fragment>
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
                    {tool(toolKey(r.citation.tool))}
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
                <li key={i} className="rounded-ctl bg-surface-2 px-2 py-1 text-xs">
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

          <SourcePills citations={answer.citations} toolResults={answer.toolResults} />
        </>
      )}
    </div>
  );
}
