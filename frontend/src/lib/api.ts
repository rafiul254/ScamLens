import type { Analysis, Benchmark, DemoSample, HealthInfo, HistoryEntry, InputKind, Language, MicroLesson, PatternCard, ScamIQ, Stats } from './types'

/**
 * The browser never talks to a third-party service: every call is same-origin
 * (/api/...) and proxied by the dev server or the hosting platform.
 * No API keys exist in this bundle — the Gemini API call happens server-side.
 */
const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, message: string, detail?: any) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (err) {
    throw new ApiError(0, 'offline', err)
  }
  const text = await res.text()
  const data = text ? safeJson(text) : null
  if (!res.ok) {
    const message = data?.detail?.message ?? data?.message ?? data?.detail ?? `Request failed (${res.status})`
    throw new ApiError(res.status, typeof message === 'string' ? message : JSON.stringify(message), data)
  }
  return data as T
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

export interface AnalyzeOptions {
  makeLesson?: boolean
  makeReport?: boolean
  makeFamilyAlert?: boolean
}

export const api = {
  health: () => request<HealthInfo>('/api/health'),

  analyzeText: (text: string, deviceId: string, kind: InputKind = 'text', language?: Language, opts: AnalyzeOptions = {}) =>
    request<Analysis>('/api/analyze/text', {
      method: 'POST',
      body: JSON.stringify({
        text,
        kind,
        device_id: deviceId,
        language: language && language !== 'unknown' ? language : null,
        make_lesson: opts.makeLesson ?? true,
        make_report: opts.makeReport ?? true,
        make_family_alert: opts.makeFamilyAlert ?? true,
      }),
    }),

  analyzeUrl: (url: string, deviceId: string, language?: Language, opts: AnalyzeOptions = {}) =>
    request<Analysis>('/api/analyze/url', {
      method: 'POST',
      body: JSON.stringify({
        url,
        device_id: deviceId,
        // A bare link carries no prose to detect a language from, so the interface language
        // is sent explicitly and the answer comes back in it.
        language: language && language !== 'unknown' ? language : null,
        make_lesson: opts.makeLesson ?? true,
      }),
    }),

  analyzeImage: async (file: File, deviceId: string, noteText = '') => {
    const form = new FormData()
    form.append('file', file)
    form.append('device_id', deviceId)
    form.append('text', noteText)
    const res = await fetch(`${BASE}/api/analyze/image`, { method: 'POST', body: form })
    const data = safeJson(await res.text())
    if (!res.ok) {
      throw new ApiError(res.status, data?.detail?.message ?? 'Could not read that screenshot.', data)
    }
    return data as Analysis
  },

  redact: (text: string) =>
    request<{ redacted_text: string; entities: any[]; count: number }>('/api/redact', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  patterns: () => request<{ count: number; patterns: PatternCard[] }>('/api/learn/patterns'),
  lesson: (patternId: string, language: string, level = 'basic') =>
    request<MicroLesson>(`/api/learn/lesson?pattern_id=${encodeURIComponent(patternId)}&language=${language}&level=${level}`),
  submitQuiz: (deviceId: string, patternId: string, correct: number, total: number) =>
    request<ScamIQ>('/api/learn/quiz', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, pattern_id: patternId, correct, total }),
    }),
  scamIq: (deviceId: string) => request<ScamIQ>(`/api/learn/scamiq?device_id=${encodeURIComponent(deviceId)}`),

  benchmark: () => request<Benchmark>('/api/benchmark'),
  samples: () => request<{ version: string; samples: DemoSample[] }>('/api/samples'),
  history: (deviceId: string, limit = 50) =>
    request<{ items: HistoryEntry[]; total: number }>(`/api/history?device_id=${encodeURIComponent(deviceId)}&limit=${limit}`),
  historyItem: (deviceId: string, id: string) =>
    request<Analysis>(`/api/history/${id}?device_id=${encodeURIComponent(deviceId)}`),
  stats: (deviceId: string) => request<Stats>(`/api/stats?device_id=${encodeURIComponent(deviceId)}`),
  deleteAll: (deviceId: string) =>
    request<{ deleted: boolean; message: string }>(`/api/data?device_id=${encodeURIComponent(deviceId)}`, { method: 'DELETE' }),
}
