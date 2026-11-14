import React, { useRef, useState } from 'react';
import {
  BookmarkPlus,
  Crown,
  FileText,
  GitCompareArrows,
  Loader2,
  Paperclip,
  RefreshCw,
  Send,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import type {
  AttachmentPayload,
  ModeType,
  ModelCatalogItem,
  PresetRecord,
} from '../types';
import { uploadAttachment } from '../api';

interface ComposerProps {
  isFollowUp: boolean;
  lockedMode?: ModeType;
  mode: ModeType;
  onModeChange: (m: ModeType) => void;
  catalog: ModelCatalogItem[];
  loadingModels: boolean;
  onRefreshModels: () => void;
  selectedModels: string[];
  onChangeSelectedModels: (models: string[]) => void;
  chairmanModel: string;
  onChangeChairmanModel: (m: string) => void;
  sharedConstraints: string;
  onChangeSharedConstraints: (c: string) => void;
  presets: PresetRecord[];
  onApplyPreset: (p: PresetRecord) => void;
  onSavePreset: (name: string) => Promise<void>;
  onDeletePreset: (id: string) => Promise<void>;
  onSubmit: (prompt: string, attachments: AttachmentPayload[]) => Promise<void>;
  disabled?: boolean;
}

export const Composer: React.FC<ComposerProps> = ({
  isFollowUp,
  lockedMode,
  mode,
  onModeChange,
  catalog,
  loadingModels,
  onRefreshModels,
  selectedModels,
  onChangeSelectedModels,
  chairmanModel,
  onChangeChairmanModel,
  sharedConstraints,
  onChangeSharedConstraints,
  presets,
  onApplyPreset,
  onSavePreset,
  onDeletePreset,
  onSubmit,
  disabled = false,
}) => {
  const [prompt, setPrompt] = useState('');
  const [attachments, setAttachments] = useState<AttachmentPayload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [showConfig, setShowConfig] = useState(!isFollowUp);
  const [showConstraints, setShowConstraints] = useState(Boolean(sharedConstraints));
  const [presetName, setPresetName] = useState('');
  const [showSavePreset, setShowSavePreset] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const effectiveMode = lockedMode || mode;
  const maxModels = effectiveMode === 'council' ? 5 : 3;

  const toggleModel = (id: string) => {
    setErrorMsg(null);
    if (selectedModels.includes(id)) {
      onChangeSelectedModels(selectedModels.filter((m) => m !== id));
    } else {
      if (selectedModels.length >= maxModels) {
        setErrorMsg(
          `Maximum ${maxModels} models allowed in ${
            effectiveMode === 'council' ? 'Independent Council' : 'Conversation'
          } mode.`
        );
        return;
      }
      onChangeSelectedModels([...selectedModels, id]);
    }
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setErrorMsg(null);
    try {
      const uploaded: AttachmentPayload[] = [];
      for (const file of Array.from(files)) {
        const parsed = await uploadAttachment(file);
        uploaded.push(parsed);
      }
      setAttachments((prev) => [...prev, ...uploaded]);
    } catch (err: any) {
      setErrorMsg(err?.message || 'Attachment extraction failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (disabled || uploading) return;
    const trimmed = prompt.trim();
    if (!trimmed) return;
    if (selectedModels.length < 2 || selectedModels.length > maxModels) {
      setErrorMsg(`Select between 2 and ${maxModels} distinct models.`);
      setShowConfig(true);
      return;
    }
    setErrorMsg(null);
    const currentPrompt = trimmed;
    const currentAtts = attachments;
    setPrompt('');
    setAttachments([]);
    try {
      await onSubmit(currentPrompt, currentAtts);
    } catch (err: any) {
      setPrompt(currentPrompt);
      setAttachments(currentAtts);
      setErrorMsg(err?.message || 'Failed to start deliberation');
    }
  };

  const filteredPresets = presets.filter((p) => p.mode === effectiveMode);

  return (
    <form
      onSubmit={handleSend}
      className="rounded-3xl md3-card p-4 sm:p-5 shadow-sm transition-all space-y-3.5"
    >
      {/* Mode Switcher (only unlocked on fresh session) + Config Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        {!isFollowUp ? (
          <div className="inline-flex rounded-full p-1 bg-[var(--md-surface-container-lowest)] border border-[var(--md-outline-variant)]">
            <button
              type="button"
              onClick={() => onModeChange('council')}
              className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                effectiveMode === 'council'
                  ? 'md3-chip-primary shadow-xs'
                  : 'text-[var(--md-on-surface-variant)] hover:text-[var(--md-on-surface)]'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              1. Independent Council (2–5)
            </button>
            <button
              type="button"
              onClick={() => onModeChange('conversation')}
              className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                effectiveMode === 'conversation'
                  ? 'md3-chip-tertiary shadow-xs'
                  : 'text-[var(--md-on-surface-variant)] hover:text-[var(--md-on-surface)]'
              }`}
            >
              <GitCompareArrows className="w-3.5 h-3.5" />
              2. Consensus Plan Mode (2–3)
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-[var(--md-on-surface-variant)]">
            <Sparkles className="w-3.5 h-3.5 text-[var(--md-primary)]" />
            <span>
              {effectiveMode === 'council'
                ? 'Follow-up Council Run (carries prior prompt + Chairman answer)'
                : 'Follow-up Plan Cycle (re-randomizes blind slots from agreed plan)'}
            </span>
          </div>
        )}

        <div className="flex items-center gap-2">
          {isFollowUp && (
            <button
              type="button"
              onClick={() => setShowConfig((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium md3-btn-tonal cursor-pointer"
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              Roster ({selectedModels.length}/{maxModels})
            </button>
          )}

          <button
            type="button"
            onClick={() => setShowConstraints((v) => !v)}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium cursor-pointer ${
              sharedConstraints.trim() ? 'md3-chip-primary' : 'md3-card-high'
            }`}
          >
            <SlidersHorizontal className="w-3 h-3" />
            Constraints
          </button>
        </div>
      </div>

      {/* Model Roster & Presets */}
      {showConfig && (
        <div className="rounded-2xl p-3.5 md3-card-low space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-semibold text-[var(--md-on-surface)] flex items-center gap-2">
              <span>
                Select {effectiveMode === 'council' ? '2–5 Council LLMs' : '2–3 Blind Plan LLMs'}
              </span>
              <span className="font-mono-code text-[11px] px-2 py-0.5 rounded-full md3-card-high">
                {selectedModels.length} / {maxModels}
              </span>
              {effectiveMode === 'conversation' && (
                <span className="text-[11px] font-normal text-[var(--md-on-surface-variant)]">
                  · Shuffled blindly at launch
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {filteredPresets.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                  {filteredPresets.map((p) => (
                    <span
                      key={p.id}
                      className="inline-flex items-center gap-1 rounded-full pl-2.5 pr-1 py-0.5 text-[11px] md3-card-high"
                    >
                      <button
                        type="button"
                        onClick={() => onApplyPreset(p)}
                        className="hover:underline cursor-pointer font-medium"
                      >
                        {p.name}
                      </button>
                      <button
                        type="button"
                        onClick={() => onDeletePreset(p.id)}
                        className="p-0.5 rounded-full hover:text-[var(--md-error)] cursor-pointer"
                        title="Delete preset"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}

              <button
                type="button"
                onClick={() => setShowSavePreset((v) => !v)}
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] md3-card-high hover:brightness-105 cursor-pointer"
                title="Save current roster as preset"
              >
                <BookmarkPlus className="w-3 h-3" />
                Save Preset
              </button>

              <button
                type="button"
                onClick={onRefreshModels}
                disabled={loadingModels}
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] md3-card-high hover:brightness-105 cursor-pointer"
                title="Sync models from LiteLLM"
              >
                <RefreshCw className={`w-3 h-3 ${loadingModels ? 'animate-spin' : ''}`} />
                Sync LiteLLM
              </button>
            </div>
          </div>

          {showSavePreset && (
            <div className="flex items-center gap-2 pt-1">
              <input
                type="text"
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
                placeholder="Preset name (e.g., Frontier Trio)…"
                className="flex-1 rounded-full px-3 py-1.5 text-xs md3-card-lowest text-[var(--md-on-surface)] focus:outline-none focus:border-[var(--md-primary)]"
              />
              <button
                type="button"
                onClick={async () => {
                  if (!presetName.trim()) return;
                  await onSavePreset(presetName.trim());
                  setPresetName('');
                  setShowSavePreset(false);
                }}
                className="rounded-full px-3 py-1.5 text-xs font-semibold md3-btn-filled cursor-pointer"
              >
                Save
              </button>
            </div>
          )}

          {/* Model Filter Chips */}
          <div className="flex flex-wrap gap-1.5">
            {catalog.map((m) => {
              const selected = selectedModels.includes(m.id);
              const idx = selectedModels.indexOf(m.id);
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => toggleModel(m.id)}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all cursor-pointer border ${
                    selected
                      ? effectiveMode === 'council'
                        ? 'md3-chip-primary border-transparent shadow-2xs'
                        : 'md3-chip-tertiary border-transparent shadow-2xs'
                      : 'bg-[var(--md-surface-container-lowest)] border-[var(--md-outline-variant)] text-[var(--md-on-surface-variant)] hover:text-[var(--md-on-surface)]'
                  }`}
                >
                  <span className="text-[10px] uppercase tracking-wider opacity-70">
                    {m.provider}
                  </span>
                  <span className="font-mono-code text-[11.5px]">{m.id}</span>
                  {selected && effectiveMode === 'council' && (
                    <span className="w-4 h-4 rounded-full bg-black/20 text-[10px] inline-flex items-center justify-center font-bold">
                      {idx + 1}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Chairman Selector (Mode 1 Only) */}
          {effectiveMode === 'council' && (
            <div className="flex flex-wrap items-center gap-2.5 pt-1 border-t border-[var(--md-outline-variant)]">
              <label className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--md-on-surface-variant)]">
                <Crown className="w-3.5 h-3.5 text-amber-400" />
                Stage 3 Chairman LLM:
              </label>
              <select
                value={chairmanModel}
                onChange={(e) => onChangeChairmanModel(e.target.value)}
                className="rounded-full px-3 py-1.5 text-xs font-medium md3-card-lowest text-[var(--md-on-surface)] focus:outline-none focus:border-[var(--md-primary)] cursor-pointer"
              >
                <option value="auto">
                  Auto — Highest Peer-Rated Model (Accuracy + Insight)
                </option>
                {catalog.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id} ({m.provider})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

      {/* Optional Shared Constraints Drawer */}
      {showConstraints && (
        <div className="rounded-2xl p-3 md3-card-low space-y-1.5">
          <div className="flex items-center justify-between text-xs font-medium text-[var(--md-on-surface-variant)]">
            <span>Shared System Constraints / Guardrails (sent identically to all models)</span>
            {sharedConstraints && (
              <button
                type="button"
                onClick={() => onChangeSharedConstraints('')}
                className="text-[11px] hover:underline cursor-pointer"
              >
                Clear
              </button>
            )}
          </div>
          <textarea
            rows={2}
            value={sharedConstraints}
            onChange={(e) => onChangeSharedConstraints(e.target.value)}
            placeholder="e.g., Target Python 3.12 + FastAPI, include Mermaid sequence diagrams, prefer zero-downtime patterns…"
            className="w-full rounded-xl p-2.5 text-xs md3-card-lowest text-[var(--md-on-surface)] placeholder:text-[var(--md-on-surface-variant)] focus:outline-none focus:border-[var(--md-primary)] resize-y"
          />
        </div>
      )}

      {/* Attached Files Chips */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {attachments.map((att, idx) => (
            <div
              key={`${att.filename}-${idx}`}
              className="inline-flex items-center gap-1.5 rounded-full pl-3 pr-2 py-1 text-xs md3-card-high"
            >
              <FileText className="w-3.5 h-3.5 text-[var(--md-primary)]" />
              <span className="truncate max-w-44 font-medium">{att.filename}</span>
              <span className="text-[10px] font-mono-code opacity-65">
                {(att.char_count / 1000).toFixed(1)}k ch
              </span>
              <button
                type="button"
                onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
                className="p-0.5 rounded-full hover:text-[var(--md-error)] cursor-pointer"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {errorMsg && (
        <div className="rounded-2xl px-3.5 py-2 text-xs md3-chip-error">{errorMsg}</div>
      )}

      {/* Main Prompt Input + Action Bar */}
      <div className="rounded-2xl md3-card-lowest p-3 focus-within:border-[var(--md-primary)] transition-colors">
        <textarea
          rows={isFollowUp ? 2 : 4}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              handleSend();
            }
          }}
          placeholder={
            isFollowUp
              ? effectiveMode === 'council'
                ? 'Ask a follow-up question to the council… (⌘ + Enter to send)'
                : 'Request revisions or new constraints on the agreed plan… (⌘ + Enter to send)'
              : effectiveMode === 'council'
              ? 'Ask a complex technical, architectural, or analytical question for independent council evaluation… (⌘ + Enter)'
              : 'Describe the system, migration, or project you want up to 3 blind LLMs to negotiate into a single agreed Markdown plan… (⌘ + Enter)'
          }
          className="w-full bg-transparent text-sm text-[var(--md-on-surface)] placeholder:text-[var(--md-on-surface-variant)] focus:outline-none resize-y"
        />

        <div className="flex items-center justify-between gap-2 pt-2 mt-1 border-t border-[var(--md-outline-variant)]">
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".md,.txt,.py,.ts,.tsx,.js,.json,.yaml,.yml,.toml,.sql,.sh,.csv,.pdf,.html,.css,.go,.rs"
              onChange={(e) => handleFiles(e.target.files)}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || disabled}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium md3-btn-tonal cursor-pointer"
              title="Attach code, Markdown, text, or PDF files as context"
            >
              {uploading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Paperclip className="w-3.5 h-3.5" />
              )}
              Attach Context
            </button>
            <span className="hidden sm:inline text-[11px] text-[var(--md-on-surface-variant)]">
              Markdown, code, JSON/YAML, or PDF
            </span>
          </div>

          <button
            type="submit"
            disabled={disabled || uploading || !prompt.trim()}
            className="inline-flex items-center gap-2 rounded-full px-5 py-2 text-xs sm:text-sm font-semibold md3-btn-filled cursor-pointer"
          >
            <Send className="w-3.5 h-3.5" />
            {effectiveMode === 'council' ? 'Convene Council' : 'Start Plan Deliberation'}
          </button>
        </div>
      </div>
    </form>
  );
};
