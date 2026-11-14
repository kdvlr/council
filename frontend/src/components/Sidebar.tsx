import React from 'react';
import {
  GitCompareArrows,
  Loader2,
  MessageSquarePlus,
  Search,
  Sparkles,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import type { SessionSummary } from '../types';

interface SidebarProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  sessions,
  activeSessionId,
  searchQuery,
  onSearchChange,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  mobileOpen,
  onCloseMobile,
}) => {
  const drawerContent = (
    <div className="flex flex-col h-full w-72 bg-[var(--md-surface-container-low)] border-r border-[var(--md-outline-variant)] select-none">
      {/* Brand + Close Mobile */}
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-2xl md3-chip-primary flex items-center justify-center shadow-xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <div className="font-display font-bold text-base tracking-tight leading-none">
              Council
            </div>
            <div className="text-[11px] text-[var(--md-on-surface-variant)] mt-0.5">
              Multi-LLM Deliberation
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onCloseMobile}
          className="lg:hidden p-1.5 rounded-full hover:bg-[var(--md-surface-container-high)] cursor-pointer"
          aria-label="Close navigation"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* New Deliberation FAB-style Action */}
      <div className="px-3 pb-3">
        <button
          type="button"
          onClick={() => {
            onNewSession();
            onCloseMobile();
          }}
          className="w-full flex items-center justify-center gap-2 rounded-2xl py-2.5 px-4 text-sm font-semibold md3-btn-filled shadow-xs cursor-pointer"
        >
          <MessageSquarePlus className="w-4 h-4" />
          New Deliberation
        </button>
      </div>

      {/* Search Sessions */}
      <div className="px-3 pb-2.5">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--md-on-surface-variant)]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search deliberations…"
            className="w-full rounded-full pl-8 pr-3 py-1.5 text-xs bg-[var(--md-surface-container-high)] text-[var(--md-on-surface)] placeholder:text-[var(--md-on-surface-variant)] border border-transparent focus:border-[var(--md-primary)] focus:outline-none"
          />
        </div>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto px-2.5 py-1 space-y-1">
        {sessions.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-[var(--md-on-surface-variant)]">
            {searchQuery ? 'No matching sessions found.' : 'Your council & plan sessions will appear here.'}
          </div>
        ) : (
          sessions.map((s) => {
            const active = s.id === activeSessionId;
            const isCouncil = s.mode === 'council';
            return (
              <div
                key={s.id}
                onClick={() => {
                  onSelectSession(s.id);
                  onCloseMobile();
                }}
                className={`group flex items-start justify-between gap-2 rounded-2xl px-3 py-2.5 cursor-pointer transition-colors ${
                  active
                    ? 'bg-[var(--md-secondary-container)] text-[var(--md-on-secondary-container)]'
                    : 'hover:bg-[var(--md-surface-container-high)] text-[var(--md-on-surface)]'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        isCouncil ? 'md3-chip-primary' : 'md3-chip-tertiary'
                      }`}
                    >
                      {isCouncil ? (
                        <Users className="w-2.5 h-2.5" />
                      ) : (
                        <GitCompareArrows className="w-2.5 h-2.5" />
                      )}
                      {isCouncil ? 'Council' : 'Plan'}
                    </span>
                    {s.latest_status === 'running' && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-[var(--md-primary)] font-medium">
                        <Loader2 className="w-2.5 h-2.5 animate-spin" />
                        Live
                      </span>
                    )}
                  </div>
                  <div className="text-xs font-medium truncate leading-snug">{s.title}</div>
                  <div className="text-[10px] opacity-65 mt-0.5">
                    {new Date(s.updated_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                    })}{' '}
                    · {s.run_count} {s.run_count === 1 ? 'run' : 'runs'}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(s.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded-full hover:bg-black/20 text-[var(--md-on-surface-variant)] hover:text-[var(--md-error)] transition-opacity cursor-pointer"
                  title="Delete session"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );

  return (
    <>
      <aside className="hidden lg:block shrink-0 h-screen sticky top-0">{drawerContent}</aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden flex">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs"
            onClick={onCloseMobile}
          />
          <div className="relative z-10 h-full">{drawerContent}</div>
        </div>
      )}
    </>
  );
};
