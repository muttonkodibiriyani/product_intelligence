'use client';

import { useQuery } from '@tanstack/react-query';
import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';
import type { QueryOf, Schemas } from '@/lib/api/types';
import { formatCount, formatDate } from '@/lib/format';
import { useAuth } from '../auth-provider';
import { ErrorNotice } from '../error-notice';
import { Skeleton } from '../ui/skeleton';

const PATH = '/api/v1/products/{product_id}/attributes' as const;
const PAGE_SIZE = 25;
const EVIDENCE_LIMIT = 3;
const ALTERNATIVE_LIMIT = 3;

type AttributeState = Schemas['AttributeState'];
type AttributeTargetLevel = Schemas['AttributeTargetLevel'];
type AttributeValue = NonNullable<Schemas['AttributeSlot']['value']>;
type AttributeSlot = Schemas['AttributeSlot'];
type AttributeTarget = Schemas['AttributeTarget'];

const STATES: readonly Exclude<AttributeState, 'not_applicable'>[] = [
  'observed',
  'not_published',
  'not_observed',
  'unknown',
  'conflict',
  'invalid',
];

const STATE_STYLE: Record<AttributeState, string> = {
  observed: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  not_published: 'border-sky-300 bg-sky-50 text-sky-800',
  not_observed: 'border-slate-300 bg-slate-50 text-slate-700',
  unknown: 'border-amber-300 bg-amber-50 text-amber-900',
  conflict: 'border-violet-300 bg-violet-50 text-violet-900',
  invalid: 'border-rose-300 bg-rose-50 text-rose-900',
  not_applicable: 'border-line bg-surface-2 text-ink-2',
};

const CONTROL =
  'min-h-10 rounded-ctl border border-line-2 bg-surface px-3 py-2 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-accent';

function bounded(text: string): string {
  return text.length > 240 ? `${text.slice(0, 237)}…` : text;
}

/** Exact wire value formatting: no unit or currency conversion and no inferred label. */
export function attributeValueText(value: AttributeValue, locale: string): string {
  switch (value.kind) {
    case 'text':
      return value.text;
    case 'enum':
      return value.code;
    case 'integer':
      return String(value.value);
    case 'decimal':
      return value.unit ? `${value.amount} ${value.unit}` : value.amount;
    case 'money':
      return `${value.currency} ${value.amount}`;
    case 'boolean':
      return value.value ? (locale === 'ar' ? 'نعم' : 'Yes') : locale === 'ar' ? 'لا' : 'No';
    case 'list':
      return value.items.join(locale === 'ar' ? '، ' : ', ');
    case 'object':
      return bounded(JSON.stringify(value.fields));
  }
}

function localized(label: Schemas['AttributeLabel'] | null | undefined, locale: string): string {
  return (locale === 'ar' ? label?.ar : undefined) ?? label?.en ?? '';
}

function targetLabel(target: AttributeTarget, t: ReturnType<typeof useTranslations>) {
  const context = target.context ? ` · ${target.context}` : '';
  return `${t(`levels.${target.level}`)} · ${target.label}${context}`;
}

function slotEvidence(slot: AttributeSlot): Schemas['AttributeFieldEvidence'][] {
  return slot.state === 'conflict'
    ? slot.alternatives.flatMap((alternative) => alternative.evidence)
    : slot.evidence;
}

function ValueCell({ slot }: { slot: AttributeSlot }) {
  const t = useTranslations('product.attributes');
  const locale = useLocale();
  if (slot.state === 'observed' && slot.value)
    return <bdi dir="auto">{attributeValueText(slot.value, locale)}</bdi>;
  if (slot.state === 'conflict')
    return (
      <div>
        <p className="font-medium text-violet-900">{t('conflict')}</p>
        <ol className="mt-1 list-decimal space-y-1 ps-5">
          {slot.alternatives.slice(0, ALTERNATIVE_LIMIT).map((alternative, index) => (
            <li key={`${alternative.value.kind}-${index}`}>
              <bdi dir="auto">{attributeValueText(alternative.value, locale)}</bdi>
            </li>
          ))}
        </ol>
      </div>
    );
  if (slot.state === 'invalid')
    return (
      <span>
        <span className="block font-medium text-rose-900">{t('invalid')}</span>
        <bdi dir="auto" className="font-mono text-xs break-all">
          {slot.rawValue}
        </bdi>
      </span>
    );
  return <span className="text-ink-2">{localized(slot.reason, locale)}</span>;
}

function EvidenceCell({ slot }: { slot: AttributeSlot }) {
  const t = useTranslations('product.attributes');
  const locale = useLocale();
  const evidence = slotEvidence(slot);
  if (evidence.length === 0) return <span className="text-ink-2">{t('noEvidence')}</span>;
  return (
    <ul className="space-y-2">
      {evidence.slice(0, EVIDENCE_LIMIT).map((item, index) => (
        <li key={`${item.source}-${item.field}-${index}`}>
          <span className="block text-xs font-medium">
            <bdi>{item.source}</bdi>
            {' · '}
            <bdi dir="ltr" className="font-mono break-all">
              {item.field}
            </bdi>
          </span>
          {item.excerpt && (
            <q dir="auto" className="mt-0.5 block text-xs text-ink-2">
              {item.excerpt}
            </q>
          )}
          {item.capturedAt && (
            <time dateTime={item.capturedAt} className="block text-xs text-ink-2">
              {t('observedAt', { date: formatDate(item.capturedAt, locale, true) })}
            </time>
          )}
        </li>
      ))}
      {evidence.length > EVIDENCE_LIMIT && (
        <li className="text-xs text-ink-2">
          {t('moreEvidence', {
            count: evidence.length - EVIDENCE_LIMIT,
            n: formatCount(evidence.length - EVIDENCE_LIMIT, locale),
          })}
        </li>
      )}
    </ul>
  );
}

export function AttributeMatrix({ id }: { id: string }) {
  const t = useTranslations('product.attributes');
  const locale = useLocale();
  const { api } = useAuth();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const focusResult = useRef(false);
  const [target, setTarget] = useState(`${id}:product`);
  const [level, setLevel] = useState<AttributeTargetLevel>('product');
  const [state, setState] = useState<Exclude<AttributeState, 'not_applicable'> | ''>('');
  const [search, setSearch] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);

  const resetPage = () => {
    setCursor(null);
    setPrevious([]);
  };
  const query: QueryOf<typeof PATH> = {
    target,
    level,
    state: state || undefined,
    q: search.trim() || undefined,
    limit: PAGE_SIZE,
    cursor: cursor || undefined,
  };
  const result = useQuery({
    queryKey: ['product-attributes', id, query],
    queryFn: ({ signal }) => api!.page(PATH, { params: { product_id: id }, query, signal }),
    enabled: !!api,
  });
  const envelope = result.data?.body;
  const page = envelope?.data;

  useEffect(() => {
    if (focusResult.current && page && !result.isFetching) {
      statusRef.current?.focus();
      focusResult.current = false;
    }
  }, [page, result.isFetching]);

  const move = (next: string | null, history: (string | null)[]) => {
    focusResult.current = true;
    setCursor(next);
    setPrevious(history);
  };

  if (result.isError) return <ErrorNotice error={result.error} onRetry={() => void result.refetch()} />;
  if (!page)
    return (
      <div className="px-5 pb-3" aria-busy>
        <Skeleton kind="table" />
        <p role="status" className="mt-3 text-sm text-ink-2">
          {t('loading')}
        </p>
      </div>
    );

  const targets = page.targets;
  const selectedSummary = targets.find((summary) => summary.target.id === target);
  const visible = page.items.slice(0, PAGE_SIZE);
  const effectivePrevious = result.data?.restarted ? [] : previous;
  const effectiveCursor = result.data?.restarted ? null : cursor;
  const pageNumber = effectivePrevious.length + 1;
  const pageCount = Math.max(1, Math.ceil(page.total / PAGE_SIZE));

  return (
    <div data-attribute-matrix dir={locale === 'ar' ? 'rtl' : 'ltr'}>
      <fieldset className="grid gap-3 border-b border-line px-5 pb-4 sm:grid-cols-3">
        <legend className="sr-only">{t('filters')}</legend>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('target')}</span>
          <select
            className={CONTROL}
            value={target}
            onChange={(event) => {
              const chosen = targets.find((item) => item.target.id === event.target.value)?.target;
              if (!chosen) return;
              setTarget(chosen.id);
              setLevel(chosen.level);
              resetPage();
            }}
          >
            {targets.map((summary) => (
              <option key={summary.target.id} value={summary.target.id}>
                {targetLabel(summary.target, t)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('state')}</span>
          <select
            className={CONTROL}
            value={state}
            onChange={(event) => {
              setState(event.target.value as typeof state);
              resetPage();
            }}
          >
            <option value="">{t('allStates')}</option>
            {STATES.map((item) => (
              <option key={item} value={item}>
                {t(`states.${item}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">{t('search')}</span>
          <input
            className={CONTROL}
            type="search"
            value={search}
            placeholder={t('searchPlaceholder')}
            onChange={(event) => {
              setSearch(event.target.value);
              resetPage();
            }}
          />
        </label>
      </fieldset>

      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
        <p ref={statusRef} tabIndex={-1} role="status" aria-live="polite" className="text-sm text-ink-2">
          {t('result', {
            visible: formatCount(visible.length, locale),
            total: formatCount(page.total, locale),
            definitions: formatCount(page.definitionCount, locale),
          })}
        </p>
        <p className="text-xs text-ink-2">
          {t('coverage', {
            slots: formatCount(selectedSummary?.slotCount ?? page.definitionCount, locale),
          })}
        </p>
      </div>

      <div className="relative overflow-x-auto px-2">
        <table className="w-full min-w-[760px] table-fixed text-sm">
          <caption className="sr-only">{t('caption')}</caption>
          <colgroup>
            <col className="w-[24%]" />
            <col className="w-[15%]" />
            <col className="w-[24%]" />
            <col className="w-[14%]" />
            <col className="w-[23%]" />
          </colgroup>
          <thead className="border-y border-line">
            <tr>
              {(['field', 'type', 'value', 'state', 'evidence'] as const).map((heading) => (
                <th key={heading} scope="col" className="px-3 py-2 text-start font-medium text-ink-2">
                  {t(heading)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((slot) => (
              <tr key={`${slot.targetId}-${slot.definition.key}`} className="border-b border-line-2">
                <th scope="row" className="px-3 py-3 text-start align-top font-medium">
                  <span dir="auto" className="block">
                    {localized(slot.definition.label, locale) || slot.definition.key}
                  </span>
                  <bdi dir="ltr" className="mt-0.5 block font-mono text-xs text-ink-2 break-all">
                    {slot.definition.key}
                  </bdi>
                </th>
                <td className="px-3 py-3 align-top text-xs text-ink-2">
                  {t(`levels.${slot.definition.level}`)} · {t(`kinds.${slot.definition.kind}`)}
                  <span className="mt-1 block">{slot.definition.group}</span>
                </td>
                <td className="px-3 py-3 align-top break-words">
                  <ValueCell slot={slot} />
                </td>
                <td className="px-3 py-3 align-top">
                  <span
                    className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${STATE_STYLE[slot.state]}`}
                  >
                    {t(`states.${slot.state}`)}
                  </span>
                </td>
                <td className="px-3 py-3 align-top break-words">
                  <EvidenceCell slot={slot} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {visible.length === 0 && <p className="px-5 py-6 text-sm text-ink-2">{t('empty')}</p>}
      <nav aria-label={t('pagination')} className="flex items-center justify-end gap-3 px-5 py-3">
        <button
          type="button"
          className={CONTROL}
          disabled={effectivePrevious.length === 0 || result.isFetching}
          onClick={() => move(effectivePrevious.at(-1) ?? null, effectivePrevious.slice(0, -1))}
        >
          {t('previous')}
        </button>
        <span className="text-sm text-ink-2 tabular-nums">
          {t('page', {
            page: formatCount(pageNumber, locale),
            pages: formatCount(pageCount, locale),
          })}
        </span>
        <button
          type="button"
          className={CONTROL}
          disabled={!page.nextCursor || result.isFetching}
          onClick={() => page.nextCursor && move(page.nextCursor, [...effectivePrevious, effectiveCursor])}
        >
          {t('next')}
        </button>
      </nav>
    </div>
  );
}
