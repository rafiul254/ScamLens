/** Types mirror backend/app/schemas.py — the API contract is the source of truth. */
export type Verdict = 'SAFE' | 'SUSPICIOUS' | 'SCAM'
export type Language = 'bn' | 'en' | 'hi' | 'ur' | 'unknown'
export type InputKind = 'text' | 'url' | 'image' | 'audio_transcript'

export interface RedFlag {
  text_span: string
  reason: string
  severity: number
}

export interface QuizQuestion {
  question: string
  options: string[]
  answer_index: number
  explanation?: string
}

export interface MicroLesson {
  title: string
  pattern_id: string
  language: Language
  level: 'basic' | 'intermediate'
  seconds: number
  body: string
  key_takeaways: string[]
  quiz: QuizQuestion[]
}

export interface Evidence {
  ml_score: number | null
  ml_label: string | null
  url_score: number | null
  pattern_matches: Array<{
    pattern_id: string
    category: string
    score: number
    severity: number
    matched_keywords: string[]
    languages: string[]
    red_flag_hints: string[]
    psychology: string[]
  }>
  pattern_score: number | null
  llm_score: number | null
  llm_verdict?: string | null
  ensemble_breakdown: {
    signals?: Record<string, number | null>
    effective_weights?: Record<string, number>
    final_score?: number
    formula?: string
    model_disagreement?: string
  }
  top_tokens: Array<{ token: string; contribution: number; start?: number; end?: number; text?: string }>
  url_findings: Array<{ type: string; detail: string; severity: number; brand?: string }>
  pii_found: Array<{ kind: string; placeholder: string; masked_preview: string; length: number }>
  agent_steps: Array<{
    step: number
    tool: string
    source: 'agent_call' | 'precomputed'
    duration_ms: number
    ok: boolean
    summary: string
  }>
  model_versions: Record<string, string>
  actionability?: {
    actionable: boolean
    ask_keywords: string[]
    has_link: boolean
    has_contact: boolean
    cap_applied: boolean
    uncapped_score?: number
    explanation: string
  }
}

export interface Analysis {
  verdict: Verdict
  risk_score: number
  confidence: number
  language: Language
  scam_type: string
  scam_type_label: string
  input_kind: InputKind
  red_flags: RedFlag[]
  explanation: string
  recommended_actions: string[]
  report_draft: string | null
  family_alert: string | null
  lesson: MicroLesson | null
  evidence: Evidence
  pii_redacted: boolean
  mode: 'agent' | 'local_fallback'
  degraded_reason: string | null
  analysis_id: string
  created_at: string
}

export interface HealthInfo {
  status: string
  version: string
  llm_enabled: boolean
  llm_model: string | null
  agent_max_steps: number
  text_model: Record<string, unknown>
  url_model: string
  url_probe_enabled: boolean
  limits: Record<string, number>
}

export interface BenchmarkModelMetrics {
  label?: string
  precision: number
  recall: number
  f1: number
  accuracy: number
  roc_auc: number
  pr_auc?: number
  confusion_matrix: number[][]
  roc_curve?: { fpr: number[]; tpr: number[] }
  n?: number
  threshold?: number
  per_language?: Record<string, { precision: number; recall: number; f1: number; roc_auc: number; n: number }>
  validation_threshold?: number
}

export interface Benchmark {
  available: boolean
  generated_at: string | null
  dataset: Record<string, any> | null
  models: {
    ml_only?: BenchmarkModelMetrics
    ml_tfidf?: BenchmarkModelMetrics
    ml_embedding?: BenchmarkModelMetrics
    ensemble?: BenchmarkModelMetrics
  } | null
  url_model: any
  ensemble_weights: Record<string, number> | null
  shipped_pipeline?: {
    split: string
    n: number
    note: string
    results: Record<string, BenchmarkModelMetrics>
    override_effect: {
      changed_decisions: number
      rows_fixed: number
      rows_broken: number
      note: string
    }
  } | null
  limitations: string[]
  notes: string | null
}

export interface PatternCard {
  id: string
  category: string
  severity: number
  name: Record<string, string>
  summary: Record<string, string>
  psychology: string[]
  safe_response: string
  red_flag_hints: string[]
}

export interface DemoSample {
  id: string
  title: Record<string, string>
  kind: InputKind
  language: Language
  text: string
  expected: Verdict
  note?: string
}

export interface ScamIQ {
  score: number
  level: string
  streak_days: number
  lessons_completed: number
  quizzes_passed: number
  correct_answers: number
  total_answers: number
  badges: Array<{ id: string; title: string; description: string; earned_at: string }>
  score_gain?: number
  passed?: boolean
}

export interface HistoryEntry {
  id: string
  created_at: string
  verdict: string
  risk_score: number
  scam_type: string
  language: string
  input_kind: string
  preview: string
}

export interface Stats {
  total_scans: number
  scam_count: number
  suspicious_count: number
  safe_count: number
  by_type: Array<{ scam_type: string; count: number }>
  by_language: Array<{ language: string; count: number }>
  last_7_days: Array<{ date: string; count: number }>
  privacy_note: string
}
