import type {
  AttachmentPayload,
  ModeType,
  ModelCatalogItem,
  PresetRecord,
  SessionDetail,
  SessionSummary,
} from './types';

export async function fetchModels(): Promise<ModelCatalogItem[]> {
  const res = await fetch('/api/models');
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to load models (${res.status})`);
  }
  const data = await res.json();
  return data.models || [];
}

export async function fetchSessions(search = ''): Promise<SessionSummary[]> {
  const q = search.trim() ? `?search=${encodeURIComponent(search.trim())}` : '';
  const res = await fetch(`/api/sessions${q}`);
  if (!res.ok) throw new Error('Failed to load sessions');
  const data = await res.json();
  return data.sessions || [];
}

export async function fetchSessionDetail(sessionId: string): Promise<SessionDetail> {
  const res = await fetch(`/api/sessions/${sessionId}`);
  if (!res.ok) throw new Error('Session not found');
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
}

export async function uploadAttachment(file: File): Promise<AttachmentPayload> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/attachments/extract', {
    method: 'POST',
    body: fd,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to parse attachment ${file.name}`);
  }
  return res.json();
}

export async function fetchPresets(): Promise<PresetRecord[]> {
  const res = await fetch('/api/presets');
  if (!res.ok) return [];
  const data = await res.json();
  return data.presets || [];
}

export async function createPreset(payload: {
  name: string;
  mode: ModeType;
  models: string[];
  chairman_model?: string;
  shared_constraints?: string;
}): Promise<PresetRecord> {
  const res = await fetch('/api/presets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to save preset');
  }
  return res.json();
}

export async function deletePreset(presetId: string): Promise<void> {
  await fetch(`/api/presets/${presetId}`, { method: 'DELETE' });
}

export async function createRun(payload: {
  session_id?: string | null;
  mode: ModeType;
  prompt: string;
  models: string[];
  chairman_model?: string;
  shared_constraints?: string;
  attachments?: AttachmentPayload[];
}): Promise<{ session_id: string; run_id: string; run_index: number }> {
  const res = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to launch deliberation');
  }
  return res.json();
}

export async function cancelRun(runId: string): Promise<void> {
  await fetch(`/api/runs/${runId}/cancel`, { method: 'POST' });
}
