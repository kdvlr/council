import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Code2,
  Coins,
  Eye,
  EyeOff,
  FileCheck2,
  GitCompareArrows,
  Loader2,
  Scale,
  Square,
} from 'lucide-react';
import type { RunDetail } from '../types';
import { CopyMarkdownButton, MarkdownViewer } from './MarkdownViewer';
import { DiffViewer } from './DiffViewer';

interface Mode2WorkspaceProps {
  run: RunDetail;
  isDark: boolean;
  onCancel: (runId: string) => void;
}

export const Mode2Workspace: React.FC<Mode2WorkspaceProps> = ({
  run,
  isDark,
  onCancel,
}) => {
  const [revealIdentities, setRevealIdentities] = useState(false);
  const [selectedTurnNo, setSelectedTurnNo] = useState<number | null>(null);
  const [planViewMode, setPlanViewMode] = useState<'rendered' | 'diff' | 'raw'>('rendered');
  const [mobilePane, setMobilePane] = useState<'timeline' | 'plan'>('plan');

  const slotCount = Object.keys(run.slot_mapping || {}).length || run.models.length;

  const participantLabel = (slotNo: number) => {
    const modelName = run.slot_mapping?.[String(slotNo)];
    if (revealIdentities && modelName) {
      return `Participant ${slotNo} (${modelName})`;
    }
    return `Participant ${slotNo}`;
  };

  // Active turn for right-hand Plan/Diff canvas: either user-clicked turn or latest turn with plan text
  const inspectedTurn = useMemo(() => {
    if (selectedTurnNo !== null) {
      const found = run.turns.find((t) => t.turn_number === selectedTurnNo);
      if (found) return found;
    }
    for (let i = run.turns.length - 1; i >= 0; i--) {
      if (run.turns[i].plan_markdown) return run.turns[i];
    }
    return run.turns[run.turns.length - 1] || null;
  }, [run.turns, selectedTurnNo]);

  // Previous turn with a distinct/earlier plan for Diff comparison
  const previousTurn = useMemo(() => {
    if (!inspectedTurn) return null;
    for (let i = run.turns.length - 1; i >= 0; i--) {
      const t = run.turns[i];
      if (t.turn_number < inspectedTurn.turn_number && t.plan_markdown) {
        return t;
      }
    }
    return null;
  }, [run.turns, inspectedTurn]);

  const activePlanMarkdown =
    selectedTurnNo === null && run.final_markdown
      ? run.final_markdown
      : inspectedTurn?.plan_markdown || run.final_markdown || '';

  const latestCompletedTurn = [...run.turns]
    .reverse()
    .find((t) => t.status === 'completed');

  const totalTokens =
    (run.metrics?.total_prompt_tokens || 0) + (run.metrics?.total_completion_tokens || 0);
  const costUsd = run.metrics?.total_cost_usd || 0;
  const durationSec = run.metrics?.duration_ms
    ? (run.metrics.duration_ms / 1000).toFixed(1)
    : null;

  return (
    <div className="space-y-4">
      {/* Top Prompt & Blind Control Card */}
      <div className="rounded-3xl p-4 sm:p-5 md3-card-low space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--md-tertiary)]">
              Blind Consensus Plan · Run #{run.run_index}
            </span>

            {/* Blind Identity Spoiler Toggle */}
            <button
              type="button"
              onClick={() => setRevealIdentities((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all cursor-pointer ${
                revealIdentities ? 'md3-chip-amber' : 'md3-card-high'
              }`}
              title="Toggle randomized model identity reveal"
            >
              {revealIdentities ? (
                <>
                  <Eye className="w-3.5 h-3.5" /> Identities Revealed
                </>
              ) : (
                <>
                  <EyeOff className="w-3.5 h-3.5" /> Blind Mode ({slotCount} Randomized LLMs)
                </>
              )}
            </button>

            {run.consensus_status === 'unanimous' && (
              <span className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold md3-chip-tertiary">
                <CheckCircle2 className="w-3.5 h-3.5" /> Unanimous Agreement
              </span>
            )}
            {run.consensus_status === 'tie_break' && (
              <span className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold md3-chip-amber">
                <Scale className="w-3.5 h-3.5" /> Round-3 Consolidated Plan
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono-code text-[var(--md-on-surface-variant)]">
            {durationSec && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full md3-card-high">
                <Clock className="w-3 h-3" /> {durationSec}s
              </span>
            )}
            {totalTokens > 0 && (
              <span className="px-2.5 py-0.5 rounded-full md3-card-high">
                {totalTokens.toLocaleString()} tok
              </span>
            )}
            {costUsd > 0 && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full md3-card-high">
                <Coins className="w-3 h-3" /> ${costUsd.toFixed(4)}
              </span>
            )}
            {run.status === 'running' && (
              <button
                type="button"
                onClick={() => onCancel(run.id)}
                className="inline-flex items-center gap-1 px-3 py-0.5 rounded-full md3-chip-error font-sans font-semibold cursor-pointer"
              >
                <Square className="w-3 h-3 fill-current" /> Stop
              </button>
            )}
          </div>
        </div>

        <div className="text-sm sm:text-base whitespace-pre-wrap leading-relaxed">
          {run.prompt}
        </div>

        {/* Spoiler Roster Legend when revealed */}
        {revealIdentities && Object.keys(run.slot_mapping || {}).length > 0 && (
          <div className="flex flex-wrap gap-2 pt-2 border-t border-[var(--md-outline-variant)]">
            {Object.entries(run.slot_mapping).map(([slot, mid]) => (
              <span
                key={slot}
                className="rounded-full px-3 py-1 text-xs font-mono-code md3-card-high"
              >
                Participant {slot} = <strong>{mid}</strong>
              </span>
            ))}
          </div>
        )}
      </div>

      {run.status === 'failed' && run.error_message && (
        <div className="rounded-2xl p-4 md3-chip-error flex items-start gap-2.5 text-xs sm:text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>{run.error_message}</div>
        </div>
      )}

      {/* Mobile Tab Switcher (`Deliberation` vs `Canonical Plan`) */}
      <div className="flex lg:hidden rounded-full p-1 md3-card-lowest">
        <button
          type="button"
          onClick={() => setMobilePane('timeline')}
          className={`flex-1 rounded-full py-1.5 text-xs font-semibold cursor-pointer ${
            mobilePane === 'timeline'
              ? 'md3-chip-tertiary'
              : 'text-[var(--md-on-surface-variant)]'
          }`}
        >
          Deliberation Feed ({run.turns.length})
        </button>
        <button
          type="button"
          onClick={() => setMobilePane('plan')}
          className={`flex-1 rounded-full py-1.5 text-xs font-semibold cursor-pointer ${
            mobilePane === 'plan'
              ? 'md3-chip-tertiary'
              : 'text-[var(--md-on-surface-variant)]'
          }`}
        >
          Canonical Plan
        </button>
      </div>

      {/* SPLIT-PANE DELIBERATION + LIVE PLAN CANVAS */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
        {/* LEFT PANE: Turn-by-Turn Deliberation Feed */}
        <div
          className={`lg:col-span-5 space-y-3 ${
            mobilePane === 'timeline' ? 'block' : 'hidden lg:block'
          }`}
        >
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--md-on-surface-variant)]">
              Rolling Broadcast Rounds (Max 3 / LLM)
            </span>
            {latestCompletedTurn?.endorsed_slots && (
              <span className="text-[11px] font-mono-code px-2.5 py-0.5 rounded-full md3-card-high">
                Endorsed v{latestCompletedTurn.plan_version}:{' '}
                {latestCompletedTurn.endorsed_slots.map((s) => `P${s}`).join(', ')} / {slotCount}
              </span>
            )}
          </div>

          {run.turns.map((turn) => {
            const isSelected =
              (selectedTurnNo === null && inspectedTurn?.turn_number === turn.turn_number) ||
              selectedTurnNo === turn.turn_number;

            return (
              <div
                key={turn.id || turn.turn_number}
                onClick={() => {
                  setSelectedTurnNo(turn.turn_number);
                  setMobilePane('plan');
                }}
                className={`rounded-3xl p-4 cursor-pointer transition-all border ${
                  isSelected
                    ? 'bg-[var(--md-surface-container-high)] border-[var(--md-primary)] shadow-xs'
                    : 'md3-card hover:brightness-105'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full px-2.5 py-0.5 text-[11px] font-mono-code md3-card-lowest">
                      {turn.is_tie_break ? 'Tie-Break' : `R${turn.round_number} · T${turn.turn_number}`}
                    </span>
                    <span className="text-xs font-semibold">
                      {participantLabel(turn.slot_number)}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {turn.status === 'streaming' ? (
                      <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] md3-chip-primary">
                        <Loader2 className="w-3 h-3 animate-spin" /> Drafting…
                      </span>
                    ) : turn.status === 'failed' ? (
                      <span className="rounded-full px-2.5 py-0.5 text-[11px] md3-chip-error">
                        Failed
                      </span>
                    ) : turn.is_tie_break ? (
                      <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold md3-chip-amber">
                        Consolidated v{turn.plan_version}
                      </span>
                    ) : turn.agreed ? (
                      <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold md3-chip-tertiary">
                        <CheckCircle2 className="w-3 h-3" /> Agreed (v{turn.plan_version})
                      </span>
                    ) : (
                      <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold md3-chip-primary">
                        {turn.turn_number === 1
                          ? `Initial Plan v${turn.plan_version}`
                          : `Revised → v${turn.plan_version}`}
                      </span>
                    )}
                  </div>
                </div>

                {turn.status === 'failed' ? (
                  <div className="text-xs text-[var(--md-error)]">{turn.error_message}</div>
                ) : turn.revision_notes ? (
                  <div className="text-xs text-[var(--md-on-surface-variant)]">
                    <MarkdownViewer content={turn.revision_notes} isDark={isDark} />
                  </div>
                ) : (
                  <div className="text-xs text-[var(--md-on-surface-variant)] flex items-center gap-1.5 py-1">
                    <Loader2 className="w-3 h-3 animate-spin" /> Reviewing current draft…
                  </div>
                )}

                {turn.status === 'completed' && (
                  <div className="mt-2.5 pt-2 border-t border-[var(--md-outline-variant)] flex items-center justify-between text-[10px] font-mono-code text-[var(--md-on-surface-variant)]">
                    <span>{(turn.latency_ms / 1000).toFixed(1)}s</span>
                    <span>
                      {(turn.prompt_tokens + turn.completion_tokens).toLocaleString()} tok
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* RIGHT PANE: Canonical Markdown Plan & Turn-to-Turn Diff Viewer */}
        <div
          className={`lg:col-span-7 lg:sticky lg:top-4 rounded-3xl overflow-hidden border-2 border-[var(--md-tertiary)]/40 bg-[var(--md-surface-container-low)] shadow-sm ${
            mobilePane === 'plan' ? 'block' : 'hidden lg:block'
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 sm:px-5 py-3 bg-[var(--md-surface-container)] border-b border-[var(--md-outline-variant)]">
            <div className="flex items-center gap-2 min-w-0">
              <FileCheck2 className="w-4 h-4 text-[var(--md-tertiary)] shrink-0" />
              <div className="min-w-0">
                <div className="text-xs sm:text-sm font-display font-bold truncate flex items-center gap-2">
                  {selectedTurnNo !== null && inspectedTurn ? (
                    <>
                      Inspecting Turn #{inspectedTurn.turn_number} (Plan v
                      {inspectedTurn.plan_version})
                      <button
                        type="button"
                        onClick={() => setSelectedTurnNo(null)}
                        className="text-[11px] font-sans font-normal underline text-[var(--md-primary)] cursor-pointer"
                      >
                        Jump to Latest
                      </button>
                    </>
                  ) : run.status === 'completed' ? (
                    'Agreed Canonical Markdown Plan'
                  ) : (
                    `Live Working Plan${
                      inspectedTurn ? ` (v${inspectedTurn.plan_version})` : ''
                    }`
                  )}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {/* Rendered | Diff | Raw Switcher */}
              <div className="inline-flex rounded-full p-0.5 md3-card-lowest text-[11px]">
                <button
                  type="button"
                  onClick={() => setPlanViewMode('rendered')}
                  className={`rounded-full px-2.5 py-1 font-medium cursor-pointer ${
                    planViewMode === 'rendered' ? 'md3-chip-tertiary' : 'opacity-75'
                  }`}
                >
                  Rendered
                </button>
                <button
                  type="button"
                  onClick={() => setPlanViewMode('diff')}
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium cursor-pointer ${
                    planViewMode === 'diff' ? 'md3-chip-tertiary' : 'opacity-75'
                  }`}
                >
                  <GitCompareArrows className="w-3 h-3" /> Diff
                </button>
                <button
                  type="button"
                  onClick={() => setPlanViewMode('raw')}
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium cursor-pointer ${
                    planViewMode === 'raw' ? 'md3-chip-tertiary' : 'opacity-75'
                  }`}
                >
                  <Code2 className="w-3 h-3" /> Raw
                </button>
              </div>

              <CopyMarkdownButton
                markdown={activePlanMarkdown}
                filename={`agreed-plan-run-${run.run_index}.md`}
              />
            </div>
          </div>

          <div className="p-5 sm:p-6 max-h-[76vh] overflow-y-auto">
            {!activePlanMarkdown ? (
              <div className="flex items-center gap-2 text-xs text-[var(--md-on-surface-variant)] py-10 justify-center">
                <Loader2 className="w-4 h-4 animate-spin" />
                Waiting for Participant 1 to stream the initial Markdown plan…
              </div>
            ) : planViewMode === 'diff' ? (
              <DiffViewer
                previousText={previousTurn?.plan_markdown || ''}
                currentText={inspectedTurn?.plan_markdown || activePlanMarkdown}
                previousLabel={
                  previousTurn
                    ? `Turn #${previousTurn.turn_number} (v${previousTurn.plan_version})`
                    : 'None'
                }
                currentLabel={
                  inspectedTurn
                    ? `Turn #${inspectedTurn.turn_number} (v${inspectedTurn.plan_version})`
                    : 'Final Plan'
                }
              />
            ) : planViewMode === 'raw' ? (
              <pre className="rounded-2xl p-4 text-xs font-mono-code whitespace-pre-wrap md3-card-lowest text-[var(--md-on-surface)]">
                {activePlanMarkdown}
              </pre>
            ) : (
              <MarkdownViewer content={activePlanMarkdown} isDark={isDark} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
