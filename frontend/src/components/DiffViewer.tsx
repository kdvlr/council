import React, { useMemo } from 'react';
import { diffLines } from 'diff';

interface DiffViewerProps {
  previousText: string;
  currentText: string;
  previousLabel?: string;
  currentLabel?: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({
  previousText,
  currentText,
  previousLabel = 'Previous Draft',
  currentLabel = 'Current Draft',
}) => {
  const { rows, addedCount, removedCount } = useMemo(() => {
    const parts = diffLines(previousText || '', currentText || '');
    const parsedRows: Array<{
      type: 'added' | 'removed' | 'unchanged';
      line: string;
      oldNo: number | null;
      newNo: number | null;
    }> = [];

    let oldLine = 1;
    let newLine = 1;
    let added = 0;
    let removed = 0;

    for (const part of parts) {
      const rawLines = part.value.replace(/\n$/, '').split('\n');
      if (part.value === '') continue;

      for (const line of rawLines) {
        if (part.added) {
          added += 1;
          parsedRows.push({ type: 'added', line, oldNo: null, newNo: newLine++ });
        } else if (part.removed) {
          removed += 1;
          parsedRows.push({ type: 'removed', line, oldNo: oldLine++, newNo: null });
        } else {
          parsedRows.push({ type: 'unchanged', line, oldNo: oldLine++, newNo: newLine++ });
        }
      }
    }

    return { rows: parsedRows, addedCount: added, removedCount: removed };
  }, [previousText, currentText]);

  if (!previousText) {
    return (
      <div className="rounded-2xl p-6 text-center text-sm text-[var(--md-on-surface-variant)] md3-card-lowest">
        This is the initial seed plan (Plan v1) — select a subsequent revision turn to inspect line-by-line changes.
      </div>
    );
  }

  return (
    <div className="rounded-2xl overflow-hidden md3-card-lowest">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-[var(--md-outline-variant)] bg-[var(--md-surface-container-low)] text-xs">
        <span className="text-[var(--md-on-surface-variant)] font-medium">
          Comparing <strong className="text-[var(--md-on-surface)]">{previousLabel}</strong> →{' '}
          <strong className="text-[var(--md-on-surface)]">{currentLabel}</strong>
        </span>
        <div className="flex items-center gap-2 font-mono-code">
          <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400">
            +{addedCount} lines
          </span>
          <span className="px-2 py-0.5 rounded-full bg-rose-500/15 text-rose-400">
            -{removedCount} lines
          </span>
        </div>
      </div>

      {addedCount === 0 && removedCount === 0 ? (
        <div className="p-6 text-center text-sm text-[var(--md-on-surface-variant)]">
          No substantive text changes in this turn (participant endorsed the canonical plan verbatim).
        </div>
      ) : (
        <div className="overflow-x-auto max-h-[68vh] font-mono-code text-xs leading-relaxed">
          {rows.map((r, idx) => {
            const rowBg =
              r.type === 'added'
                ? 'bg-emerald-500/12 text-emerald-200'
                : r.type === 'removed'
                ? 'bg-rose-500/12 text-rose-200 line-through opacity-85'
                : 'text-[var(--md-on-surface-variant)]';
            const prefix = r.type === 'added' ? '+' : r.type === 'removed' ? '-' : ' ';
            return (
              <div key={idx} className={`flex px-3 py-0.5 ${rowBg}`}>
                <span className="w-9 shrink-0 select-none opacity-45 text-right pr-2">
                  {r.oldNo ?? ''}
                </span>
                <span className="w-9 shrink-0 select-none opacity-45 text-right pr-3">
                  {r.newNo ?? ''}
                </span>
                <span className="w-4 shrink-0 select-none font-bold">{prefix}</span>
                <span className="whitespace-pre-wrap break-all">{r.line || ' '}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
