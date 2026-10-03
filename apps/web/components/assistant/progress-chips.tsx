'use client';

import { useTranslations } from 'next-intl';
import { progressKey, toolErrorKey, toolKey } from '@/lib/assistant/answer';
import type { ChatProgress } from '@/lib/assistant/types';

/** Live steps while a question runs: stages and the tools used (no model text, no numbers). */
export function ProgressChips({ steps, done }: { steps: readonly ChatProgress[]; done: boolean }) {
  const t = useTranslations('assistant.progress');
  const tool = useTranslations('assistant.tools');
  if (steps.length === 0) return null;
  return (
    <ol aria-label={t('label')} className="flex flex-wrap gap-1.5">
      {steps.map((step, i) => {
        const last = i === steps.length - 1 && !done;
        const text =
          step.type === 'status'
            ? t(step.stage)
            : t(
                step.status === 'ok'
                  ? 'tool'
                  : step.status === 'error'
                    ? `toolErrors.${toolErrorKey(step.code)}`
                    : 'toolEmpty',
                { tool: tool(toolKey(step.name)) },
              );
        return (
          <li
            key={progressKey(step, i)}
            aria-current={last ? 'step' : undefined}
            className={`pill border border-line-2 font-normal ${
              last ? 'bg-surface-2 text-ink motion-safe:animate-pulse' : 'text-ink-2'
            }`}
          >
            {text}
          </li>
        );
      })}
    </ol>
  );
}
