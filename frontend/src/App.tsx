import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  GitCompareArrows,
  Loader2,
  Menu,
  Moon,
  Plus,
  Sun,
  Users,
} from 'lucide-react';
import {
  cancelRun,
  createPreset,
  createRun,
  deletePreset,
  deleteSession,
  fetchModels,
  fetchPresets,
  fetchSessionDetail,
  fetchSessions,
} from './api';
import type {
  AttachmentPayload,
  ModeType,
  ModelCatalogItem,
  PresetRecord,
  SessionDetail,
  SessionSummary,
} from './types';
import { Sidebar } from './components/Sidebar';
import { Composer } from './components/Composer';
import { Mode1Workspace } from './components/Mode1Workspace';
import { Mode2Workspace } from './components/Mode2Workspace';

// Preferred diverse default models when present in LiteLLM (avoids 0-quota claude-opus-5-5 by default)
const PREFERRED_COUNCIL_DEFAULTS = [
  'gemini-4-carbon',
  'gemini-4-hydrogen',
  'deepseek-v4.1-flash',
  'gpt-oss-120b',
  'gemini-3.8-flash',
];

const PREFERRED_CONVERSATION_DEFAULTS = [
  'gemini-4-carbon',
  'deepseek-v4.1-flash',
  'gpt-oss-120b',
];

function pickDefaultModels(catalog: ModelCatalogItem[], mode: ModeType): string[] {
  const available = new Set(catalog.map((m) => m.id));
  const prefs =
    mode === 'council' ? PREFERRED_COUNCIL_DEFAULTS : PREFERRED_CONVERSATION_DEFAULTS;
  const maxCount = mode === 'council' ? 5 : 3;

  const chosen = prefs.filter((id) => available.has(id)).slice(0, maxCount);
  if (chosen.length >= 2) return chosen;

  for (const item of catalog) {
    if (!chosen.includes(item.id) && !item.id.includes('opus')) {
      chosen.push(item.id);
    }
    if (chosen.length >= maxCount) break;
  }
  return chosen;
}

export const App: React.FC = () => {
  const [isDark, setIsDark] = useState<boolean>(() => {
    const saved = localStorage.getItem('council-theme');
    return saved ? saved === 'dark' : true;
  });

  const [catalog, setCatalog] = useState<ModelCatalogItem[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);

  const [mode, setMode] = useState<ModeType>('council');
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [chairmanModel, setChairmanModel] = useState<string>('auto');
  const [sharedConstraints, setSharedConstraints] = useState<string>('');
  const [presets, setPresets] = useState<PresetRecord[]>([]);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    localStorage.setItem('council-theme', isDark ? 'dark' : 'light');
  }, [isDark]);

  const loadModels = useCallback(async (currentMode: ModeType, preserveSelection = false) => {
    setLoadingModels(true);
    try {
      const list = await fetchModels();
      setCatalog(list);
      if (!preserveSelection) {
        setSelectedModels(pickDefaultModels(list, currentMode));
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingModels(false);
    }
  }, []);

  const refreshSessionList = useCallback(async (q = searchQuery) => {
    try {
      const list = await fetchSessions(q);
      setSessions(list);
    } catch (err) {
      console.error(err);
    }
  }, [searchQuery]);

  useEffect(() => {
    loadModels('council', false);
    fetchPresets().then(setPresets).catch(console.error);
  }, [loadModels]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      refreshSessionList(searchQuery);
    }, 180);
    return () => window.clearTimeout(t);
  }, [searchQuery, refreshSessionList]);

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    try {
      const detail = await fetchSessionDetail(sessionId);
      setActiveSession(detail);
      setMode(detail.mode);
      setSharedConstraints(detail.shared_constraints || '');
      const lastRun = detail.runs[detail.runs.length - 1];
      if (lastRun) {
        setSelectedModels(lastRun.models);
        if (lastRun.chairman_spec) setChairmanModel(lastRun.chairman_spec);
      }
    } catch (err) {
      console.error(err);
    }
  }, []);

  const handleModeChange = (nextMode: ModeType) => {
    setMode(nextMode);
    setSelectedModels(pickDefaultModels(catalog, nextMode));
  };

  const handleNewSession = () => {
    setActiveSessionId(null);
    setActiveSession(null);
    setSharedConstraints('');
    setSelectedModels(pickDefaultModels(catalog, mode));
  };

  const handleDeleteSession = async (id: string) => {
    await deleteSession(id);
    if (activeSessionId === id) {
      handleNewSession();
    }
    await refreshSessionList();
  };

  // Subscribe to SSE for any active running run in the open session
  const activeRunningRunId = useMemo(() => {
    if (!activeSession) return null;
    const running = activeSession.runs.find((r) => r.status === 'running');
    return running ? running.id : null;
  }, [activeSession]);

  useEffect(() => {
    if (!activeRunningRunId || !activeSessionId) return;

    const es = new EventSource(`/api/runs/${activeRunningRunId}/stream`);

    es.addEventListener('stage', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) =>
            r.id === activeRunningRunId
              ? {
                  ...r,
                  stage: data.stage || r.stage,
                  resolved_chairman: data.resolved_chairman || r.resolved_chairman,
                  responses: data.scores
                    ? r.responses.map((resp) => {
                        const sc = data.scores.find((x: any) => x.model_id === resp.model_id);
                        return sc ? { ...resp, ...sc } : resp;
                      })
                    : r.responses,
                }
              : r
          ),
        };
      });
    });

    es.addEventListener('mode2_init', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) =>
            r.id === activeRunningRunId
              ? { ...r, slot_mapping: data.slot_mapping || r.slot_mapping }
              : r
          ),
        };
      });
    });

    es.addEventListener('turn_start', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) => {
            if (r.id !== activeRunningRunId) return r;
            if (r.turns.some((t) => t.turn_number === data.turn_number)) return r;
            return {
              ...r,
              turns: [
                ...r.turns,
                {
                  id: data.id,
                  turn_number: data.turn_number,
                  round_number: data.round_number,
                  slot_number: data.slot_number,
                  is_tie_break: Boolean(data.is_tie_break),
                  agreed: false,
                  plan_version: 1,
                  revision_notes: '',
                  plan_markdown: '',
                  prompt_tokens: 0,
                  completion_tokens: 0,
                  cost_usd: 0,
                  latency_ms: 0,
                  status: 'streaming',
                },
              ],
            };
          }),
        };
      });
    });

    es.addEventListener('token', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) => {
            if (r.id !== activeRunningRunId) return r;

            if (data.target === 'stage1') {
              return {
                ...r,
                responses: r.responses.map((resp) =>
                  resp.slot_index === data.slot_index
                    ? { ...resp, content: resp.content + data.delta }
                    : resp
                ),
              };
            }

            if (data.target === 'chairman') {
              return {
                ...r,
                final_markdown: r.final_markdown + data.delta,
              };
            }

            if (data.target === 'mode2_notes') {
              return {
                ...r,
                turns: r.turns.map((t) =>
                  t.turn_number === data.turn_number
                    ? { ...t, revision_notes: t.revision_notes + data.delta }
                    : t
                ),
              };
            }

            if (data.target === 'mode2_plan') {
              return {
                ...r,
                turns: r.turns.map((t) =>
                  t.turn_number === data.turn_number
                    ? { ...t, plan_markdown: t.plan_markdown + data.delta }
                    : t
                ),
              };
            }

            return r;
          }),
        };
      });
    });

    es.addEventListener('opinion_done', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) =>
            r.id === activeRunningRunId
              ? {
                  ...r,
                  responses: r.responses.map((resp) =>
                    resp.slot_index === data.slot_index ? { ...resp, ...data } : resp
                  ),
                }
              : r
          ),
        };
      });
    });

    es.addEventListener('reviewer_done', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) => {
            if (r.id !== activeRunningRunId) return r;
            const existingIds = new Set(r.ratings.map((x) => x.id));
            const incoming = (data.ratings || []).filter((x: any) => !existingIds.has(x.id));
            return { ...r, ratings: [...r.ratings, ...incoming] };
          }),
        };
      });
    });

    es.addEventListener('turn_done', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setActiveSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          runs: prev.runs.map((r) =>
            r.id === activeRunningRunId
              ? {
                  ...r,
                  turns: r.turns.map((t) =>
                    t.turn_number === data.turn_number ? { ...t, ...data } : t
                  ),
                }
              : r
          ),
        };
      });
    });

    es.addEventListener('done', () => {
      es.close();
      fetchSessionDetail(activeSessionId)
        .then((detail) => setActiveSession(detail))
        .catch(console.error);
      refreshSessionList();
    });

    es.onerror = () => {
      es.close();
      fetchSessionDetail(activeSessionId)
        .then((detail) => setActiveSession(detail))
        .catch(console.error);
    };

    return () => {
      es.close();
    };
  }, [activeRunningRunId, activeSessionId, refreshSessionList]);

  const handleLaunchRun = async (prompt: string, attachments: AttachmentPayload[]) => {
    const effectiveMode = activeSession ? activeSession.mode : mode;
    const result = await createRun({
      session_id: activeSessionId,
      mode: effectiveMode,
      prompt,
      models: selectedModels,
      chairman_model: effectiveMode === 'council' ? chairmanModel : undefined,
      shared_constraints: sharedConstraints.trim() || undefined,
      attachments,
    });
    const detail = await fetchSessionDetail(result.session_id);
    setActiveSessionId(result.session_id);
    setActiveSession(detail);
    await refreshSessionList();
  };

  const handleCancelRun = async (runId: string) => {
    await cancelRun(runId);
    if (activeSessionId) {
      const detail = await fetchSessionDetail(activeSessionId);
      setActiveSession(detail);
    }
    await refreshSessionList();
  };

  const handleSavePreset = async (name: string) => {
    const effectiveMode = activeSession ? activeSession.mode : mode;
    const created = await createPreset({
      name,
      mode: effectiveMode,
      models: selectedModels,
      chairman_model: chairmanModel,
      shared_constraints: sharedConstraints.trim() || undefined,
    });
    setPresets((prev) => [created, ...prev]);
  };

  const handleDeletePreset = async (id: string) => {
    await deletePreset(id);
    setPresets((prev) => prev.filter((p) => p.id !== id));
  };

  const handleApplyPreset = (p: PresetRecord) => {
    if (!activeSession) {
      setMode(p.mode);
    }
    setSelectedModels(p.models);
    if (p.chairman_model) setChairmanModel(p.chairman_model);
    if (p.shared_constraints != null) setSharedConstraints(p.shared_constraints);
  };

  // Single-row persistent right-side header widgets passed directly into sub-view top flex row
  const headerRightWidgets = (
    <div className="flex items-center gap-2 shrink-0">
      {activeRunningRunId && (
        <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold md3-chip-primary">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Deliberating…
        </span>
      )}
      {activeSession && (
        <button
          type="button"
          onClick={handleNewSession}
          className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold md3-btn-tonal cursor-pointer"
        >
          <Plus className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">New</span>
        </button>
      )}
      <button
        type="button"
        onClick={() => setIsDark((d) => !d)}
        className="p-2 rounded-full md3-card-high hover:brightness-105 cursor-pointer"
        title="Toggle Dark / Light Material 3 Theme"
        aria-label="Toggle theme"
      >
        {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>
    </div>
  );

  return (
    <div className="min-h-screen flex md3-surface">
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onSelectSession={selectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        mobileOpen={mobileDrawerOpen}
        onCloseMobile={() => setMobileDrawerOpen(false)}
      />

      <main className="flex-1 min-w-0 flex flex-col">
        <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 sm:py-6 flex-1 flex flex-col gap-6">
          {/* Single-Row Top Bar (Title + Mode on Left, Status + Theme on Right) */}
          <div className="flex flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <button
                type="button"
                onClick={() => setMobileDrawerOpen(true)}
                className="lg:hidden p-2 rounded-full md3-card-high cursor-pointer shrink-0"
                aria-label="Open menu"
              >
                <Menu className="w-4 h-4" />
              </button>

              {activeSession ? (
                <div className="flex items-center gap-2.5 min-w-0">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold shrink-0 ${
                      activeSession.mode === 'council'
                        ? 'md3-chip-primary'
                        : 'md3-chip-tertiary'
                    }`}
                  >
                    {activeSession.mode === 'council' ? (
                      <>
                        <Users className="w-3.5 h-3.5" /> Council
                      </>
                    ) : (
                      <>
                        <GitCompareArrows className="w-3.5 h-3.5" /> Consensus Plan
                      </>
                    )}
                  </span>
                  <h1 className="font-display font-bold text-base sm:text-xl truncate m-0">
                    {activeSession.title}
                  </h1>
                </div>
              ) : (
                <h1 className="font-display font-bold text-lg sm:text-2xl m-0 truncate">
                  {mode === 'council'
                    ? 'Independent LLM Council'
                    : 'Blind Consensus Plan Deliberation'}
                </h1>
              )}
            </div>

            {headerRightWidgets}
          </div>

          {/* Empty State / New Deliberation Landing */}
          {!activeSession ? (
            <div className="max-w-4xl w-full mx-auto my-auto py-4 space-y-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <div
                  onClick={() => handleModeChange('council')}
                  className={`rounded-3xl p-4 cursor-pointer transition-all border ${
                    mode === 'council'
                      ? 'md3-card-high border-[var(--md-primary)]'
                      : 'md3-card-low opacity-80 hover:opacity-100'
                  }`}
                >
                  <div className="flex items-center gap-2 font-display font-bold text-sm mb-1.5">
                    <Users className="w-4 h-4 text-[var(--md-primary)]" />
                    Mode 1 · Independent LLM Council
                  </div>
                  <p className="text-xs text-[var(--md-on-surface-variant)] leading-relaxed m-0">
                    Simultaneously queries up to <strong>5 LLMs</strong> without shared context, runs self-excluded anonymized peer scoring on <strong>Accuracy &amp; Insight</strong>, and synthesizes the definitive answer via a <strong>Chairman LLM</strong>.
                  </p>
                </div>

                <div
                  onClick={() => handleModeChange('conversation')}
                  className={`rounded-3xl p-4 cursor-pointer transition-all border ${
                    mode === 'conversation'
                      ? 'md3-card-high border-[var(--md-tertiary)]'
                      : 'md3-card-low opacity-80 hover:opacity-100'
                  }`}
                >
                  <div className="flex items-center gap-2 font-display font-bold text-sm mb-1.5">
                    <GitCompareArrows className="w-4 h-4 text-[var(--md-tertiary)]" />
                    Mode 2 · Blind Consensus Plan Mode
                  </div>
                  <p className="text-xs text-[var(--md-on-surface-variant)] leading-relaxed m-0">
                    Randomizes up to <strong>3 LLMs</strong> completely unaware of each other. Participant 1 drafts a Markdown plan; Participants 2 &amp; 3 critique and revise across up to <strong>3 rolling rounds</strong> until unanimous agreement.
                  </p>
                </div>
              </div>

              <Composer
                isFollowUp={false}
                mode={mode}
                onModeChange={handleModeChange}
                catalog={catalog}
                loadingModels={loadingModels}
                onRefreshModels={() => loadModels(mode, true)}
                selectedModels={selectedModels}
                onChangeSelectedModels={setSelectedModels}
                chairmanModel={chairmanModel}
                onChangeChairmanModel={setChairmanModel}
                sharedConstraints={sharedConstraints}
                onChangeSharedConstraints={setSharedConstraints}
                presets={presets}
                onApplyPreset={handleApplyPreset}
                onSavePreset={handleSavePreset}
                onDeletePreset={handleDeletePreset}
                onSubmit={handleLaunchRun}
              />
            </div>
          ) : (
            /* Active Session Thread + Follow-up Composer */
            <div className="space-y-8 pb-6">
              {activeSession.runs.map((run) =>
                activeSession.mode === 'council' ? (
                  <Mode1Workspace
                    key={run.id}
                    run={run}
                    isDark={isDark}
                    onCancel={handleCancelRun}
                  />
                ) : (
                  <Mode2Workspace
                    key={run.id}
                    run={run}
                    isDark={isDark}
                    onCancel={handleCancelRun}
                  />
                )
              )}

              <Composer
                isFollowUp={true}
                lockedMode={activeSession.mode}
                mode={activeSession.mode}
                onModeChange={() => {}}
                catalog={catalog}
                loadingModels={loadingModels}
                onRefreshModels={() => loadModels(activeSession.mode, true)}
                selectedModels={selectedModels}
                onChangeSelectedModels={setSelectedModels}
                chairmanModel={chairmanModel}
                onChangeChairmanModel={setChairmanModel}
                sharedConstraints={sharedConstraints}
                onChangeSharedConstraints={setSharedConstraints}
                presets={presets}
                onApplyPreset={handleApplyPreset}
                onSavePreset={handleSavePreset}
                onDeletePreset={handleDeletePreset}
                onSubmit={handleLaunchRun}
                disabled={Boolean(activeRunningRunId)}
              />
            </div>
          )}
        </div>
      </main>
    </div>
  );
};
export default App;
