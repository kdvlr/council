import React, { useState } from 'react';
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  Clock,
  Coins,
  Crown,
  Loader2,
  Square,
  Users,
} from 'lucide-react';
import type { RunDetail } from '../types';
import { CopyMarkdownButton, MarkdownViewer } from './MarkdownViewer';

interface Mode1WorkspaceProps {
  run: RunDetail;
  isDark: boolean;
  onCancel: (runId: string) => void;
}

export const Mode1Workspace: React.FC<Mode1WorkspaceProps> = ({
  run,
  isDark,
  onCancel,
}) => {
  const [activeTab, setActiveTab] = useState<'responses' | 'matrix'>('responses');
  const [focusedSlot, setFocusedSlot] = useState<number | 'all'>('all');

  const stageOrder = ['stage1_opinions', 'stage2_ratings', 'stage3_chairman', 'done'];
  const currentStageIdx = Math.max(0, stageOrder.indexOf(run.stage));

  const totalTokens =
    (run.metrics?.total_prompt_tokens || 0) + (run.metrics?.total_completion_tokens || 0);
  const costUsd = run.metrics?.total_cost_usd || 0;
  const durationSec = run.metrics?.duration_ms
    ? (run.metrics.duration_ms / 1000).toFixed(1)
    : null;

  const visibleResponses =
    focusedSlot === 'all'
      ? run.responses
      : run.responses.filter((r) => r.slot_index === focusedSlot);

  return (
    <div className="space-y-5">
      {/* User Prompt Card */}
      <div className="rounded-3xl p-4 sm:p-5 md3-card-low">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--md-primary)]">
            Prompt · Run #{run.run_index}
          </span>
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
        {run.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3 pt-2.5 border-t border-[var(--md-outline-variant)]">
            {run.attachments.map((a, idx) => (
              <span
                key={idx}
                className="text-[11px] px-2.5 py-0.5 rounded-full md3-card-high font-mono-code"
              >
                📎 {a.filename}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 3-Stage Deliberation Stepper */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {[
          { label: '1. Independent Opinions', idx: 0, desc: `${run.models.length} parallel LLMs` },
          { label: '2. Blind Peer Review', idx: 1, desc: 'Self-excluded Accuracy & Insight' },
          {
            label: '3. Chairman Synthesis',
            idx: 2,
            desc: run.resolved_chairman || (run.chairman_spec === 'auto' ? 'Auto Top-Scored' : run.chairman_spec || 'Pending'),
          },
        ].map((step) => {
          const isCompleted = currentStageIdx > step.idx || run.status === 'completed';
          const isActive = run.status === 'running' && currentStageIdx === step.idx;
          return (
            <div
              key={step.label}
              className={`rounded-2xl px-3.5 py-2.5 flex items-center justify-between border transition-all ${
                isActive
                  ? 'md3-chip-primary border-transparent shadow-xs'
                  : isCompleted
                  ? 'md3-card border-[var(--md-outline-variant)]'
                  : 'md3-card-lowest opacity-60'
              }`}
            >
              <div className="min-w-0">
                <div className="text-xs font-semibold truncate">{step.label}</div>
                <div className="text-[11px] opacity-75 truncate font-mono-code">{step.desc}</div>
              </div>
              {isActive ? (
                <Loader2 className="w-4 h-4 animate-spin shrink-0" />
              ) : isCompleted ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : null}
            </div>
          );
        })}
      </div>

      {run.status === 'failed' && run.error_message && (
        <div className="rounded-2xl p-4 md3-chip-error flex items-start gap-2.5 text-xs sm:text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>{run.error_message}</div>
        </div>
      )}

      {/* HERO CHAIRMAN SYNTHESIS CARD */}
      {(run.final_markdown || run.stage === 'stage3_chairman') && (
        <div className="rounded-3xl overflow-hidden border-2 border-[var(--md-primary)]/45 bg-[var(--md-surface-container-low)] shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5 bg-[var(--md-surface-container)] border-b border-[var(--md-outline-variant)]">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl md3-chip-amber flex items-center justify-center">
                <Crown className="w-4 h-4" />
              </div>
              <div>
                <div className="text-sm font-display font-bold flex items-center gap-2">
                  Chairman Final Synthesis
                  {run.status === 'running' && run.stage === 'stage3_chairman' && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--md-primary)]" />
                  )}
                </div>
                <div className="text-[11px] text-[var(--md-on-surface-variant)] font-mono-code">
                  Chair: {run.resolved_chairman || 'Resolving…'}{' '}
                  {run.chairman_spec === 'auto' ? '(Auto: Highest Peer Score)' : '(Pinned)'}
                </div>
              </div>
            </div>

            <CopyMarkdownButton
              markdown={run.final_markdown}
              filename={`council-synthesis-run-${run.run_index}.md`}
            />
          </div>

          <div className="p-5 sm:p-6">
            {run.final_markdown ? (
              <MarkdownViewer content={run.final_markdown} isDark={isDark} />
            ) : (
              <div className="flex items-center gap-2 text-xs text-[var(--md-on-surface-variant)] py-4">
                <Loader2 className="w-4 h-4 animate-spin" />
                Synthesizing peer-reviewed responses into definitive answer…
              </div>
            )}
          </div>
        </div>
      )}

      {/* TABBED STAGE 1 & STAGE 2 INSPECTOR */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex rounded-full p-1 md3-card-lowest">
            <button
              type="button"
              onClick={() => setActiveTab('responses')}
              className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold cursor-pointer ${
                activeTab === 'responses'
                  ? 'md3-chip-primary'
                  : 'text-[var(--md-on-surface-variant)]'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              Individual LLM Responses ({run.responses.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('matrix')}
              className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold cursor-pointer ${
                activeTab === 'matrix'
                  ? 'md3-chip-primary'
                  : 'text-[var(--md-on-surface-variant)]'
              }`}
            >
              <Award className="w-3.5 h-3.5" />
              Blind Peer Ratings ({run.ratings.length})
            </button>
          </div>

          {activeTab === 'responses' && run.responses.length > 1 && (
            <div className="flex flex-wrap items-center gap-1">
              <button
                type="button"
                onClick={() => setFocusedSlot('all')}
                className={`rounded-full px-2.5 py-1 text-[11px] font-medium cursor-pointer ${
                  focusedSlot === 'all' ? 'md3-btn-tonal' : 'md3-card-lowest opacity-75'
                }`}
              >
                Grid View
              </button>
              {run.responses.map((r) => (
                <button
                  key={r.slot_index}
                  type="button"
                  onClick={() => setFocusedSlot(r.slot_index)}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-mono-code cursor-pointer ${
                    focusedSlot === r.slot_index
                      ? 'md3-btn-tonal font-semibold'
                      : 'md3-card-lowest opacity-75'
                  }`}
                >
                  {r.model_id}
                </button>
              ))}
            </div>
          )}
        </div>

        {activeTab === 'responses' ? (
          <div
            className={`grid gap-4 ${
              focusedSlot === 'all' ? 'grid-cols-1 xl:grid-cols-2' : 'grid-cols-1'
            }`}
          >
            {visibleResponses.map((resp) => {
              const isWinner =
                run.resolved_chairman === resp.model_id && run.chairman_spec === 'auto';
              return (
                <div
                  key={resp.slot_index}
                  className="rounded-3xl md3-card flex flex-col overflow-hidden"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 bg-[var(--md-surface-container-high)]/60 border-b border-[var(--md-outline-variant)]">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="w-6 h-6 rounded-full md3-chip-primary text-xs font-bold inline-flex items-center justify-center shrink-0">
                        {resp.slot_index + 1}
                      </span>
                      <span className="font-mono-code text-xs font-semibold truncate">
                        {resp.model_id}
                      </span>
                      {isWinner && (
                        <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold md3-chip-amber">
                          <Crown className="w-2.5 h-2.5" /> Top Rated
                        </span>
                      )}
                      {resp.status === 'streaming' && (
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--md-primary)]" />
                      )}
                    </div>

                    <div className="flex items-center gap-1.5">
                      {resp.avg_total != null && (
                        <span
                          className="rounded-full px-2.5 py-0.5 text-[11px] font-mono-code font-semibold md3-chip-tertiary"
                          title={`Accuracy ${resp.avg_accuracy}/10 · Insight ${resp.avg_insight}/10`}
                        >
                          ★ {resp.avg_total.toFixed(1)}/20 (Acc {resp.avg_accuracy} · Ins{' '}
                          {resp.avg_insight})
                        </span>
                      )}
                      {resp.content && (
                        <CopyMarkdownButton
                          markdown={resp.content}
                          label="Copy"
                          showDownload={false}
                        />
                      )}
                    </div>
                  </div>

                  <div className="p-4 sm:p-5 flex-1 max-h-[540px] overflow-y-auto">
                    {resp.status === 'failed' ? (
                      <div className="rounded-2xl p-3.5 md3-chip-error text-xs">
                        <strong>Model unavailable:</strong> {resp.error_message || 'Request failed'}
                      </div>
                    ) : resp.content ? (
                      <MarkdownViewer content={resp.content} isDark={isDark} />
                    ) : (
                      <div className="text-xs text-[var(--md-on-surface-variant)] flex items-center gap-2 py-4">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Generating independent response…
                      </div>
                    )}
                  </div>

                  {resp.status === 'completed' && (
                    <div className="px-4 py-2 border-t border-[var(--md-outline-variant)] text-[11px] font-mono-code text-[var(--md-on-surface-variant)] flex items-center justify-between">
                      <span>{(resp.latency_ms / 1000).toFixed(1)}s</span>
                      <span>
                        {(resp.prompt_tokens + resp.completion_tokens).toLocaleString()} tok
                        {resp.cost_usd > 0 ? ` · $${resp.cost_usd.toFixed(4)}` : ''}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          /* Stage 2 Blind Peer Review Matrix */
          <div className="rounded-3xl md3-card p-4 sm:p-5 space-y-4">
            {run.ratings.length === 0 ? (
              <div className="text-xs text-[var(--md-on-surface-variant)] py-6 text-center">
                {run.status === 'running'
                  ? 'Waiting for Stage 1 responses to finish before launching blind self-excluded peer review…'
                  : 'No peer ratings recorded for this run.'}
              </div>
            ) : (
              <div className="space-y-3">
                <div className="text-xs text-[var(--md-on-surface-variant)]">
                  Each LLM reviewed only the <strong>other</strong> <em>N</em> − 1 responses under freshly shuffled anonymous labels (<code>Response A</code>, <code>Response B</code>, …) to eliminate brand and self-recognition bias.
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {run.ratings.map((rt) => (
                    <div
                      key={rt.id}
                      className="rounded-2xl p-3.5 md3-card-low space-y-2 border border-[var(--md-outline-variant)]"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-1.5 text-xs">
                        <div className="font-mono-code text-[11px]">
                          <span className="text-[var(--md-on-surface-variant)]">Judge:</span>{' '}
                          <strong>{rt.reviewer_model_id}</strong>{' '}
                          <span className="opacity-60">→</span>{' '}
                          <span className="px-1.5 py-0.5 rounded-md md3-card-high">
                            {rt.anon_label}
                          </span>{' '}
                          <span className="opacity-75">({rt.target_model_id})</span>
                        </div>
                        <div className="flex items-center gap-1.5 font-mono-code text-[11px]">
                          <span className="px-2 py-0.5 rounded-full md3-chip-primary">
                            Acc {rt.accuracy}/10
                          </span>
                          <span className="px-2 py-0.5 rounded-full md3-chip-tertiary">
                            Ins {rt.insight}/10
                          </span>
                        </div>
                      </div>
                      <p className="text-xs text-[var(--md-on-surface-variant)] leading-relaxed m-0">
                        {rt.critique}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
