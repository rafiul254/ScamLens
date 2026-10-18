import { useState } from 'react'
import { languageName, verdictKey, translate, type LangCode } from '../lib/i18n'
import { PII_BADGE_TEXT } from '../lib/pii'
import { speak, speechOutputSupported, stopSpeaking } from '../lib/speech'
import type { Analysis, MicroLesson, Verdict } from '../lib/types'
import { HighlightedText } from './HighlightedText'

const VERDICT_STYLE: Record<Verdict, { bg: string; ring: string; text: string; icon: string }> = {
  SAFE: { bg: 'bg-emerald-50 dark:bg-emerald-900/25', ring: 'ring-emerald-300', text: 'text-emerald-900 dark:text-emerald-100', icon: '✅' },
  SUSPICIOUS: { bg: 'bg-amber-50 dark:bg-amber-900/25', ring: 'ring-amber-300', text: 'text-amber-900 dark:text-amber-100', icon: '⚠️' },
  SCAM: { bg: 'bg-red-50 dark:bg-red-900/25', ring: 'ring-red-300', text: 'text-red-900 dark:text-red-100', icon: '⛔' },
}

function CopyButton({ text, lang, label }: { text: string; lang: LangCode; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
        } catch {
          const area = document.createElement('textarea')
          area.value = text
          document.body.appendChild(area)
          area.select()
          document.execCommand('copy')
          document.body.removeChild(area)
        }
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1800)
      }}
      aria-label={`${translate(lang, 'result.copy')}: ${label ?? ''}`}
      className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
    >
      {copied ? `✓ ${translate(lang, 'result.copied')}` : `⧉ ${translate(lang, 'result.copy')}`}
    </button>
  )
}

function LessonQuizCard({ lesson, lang }: { lesson: MicroLesson; lang: LangCode }) {
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [checked, setChecked] = useState(false)
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v)
  const correct = lesson.quiz.filter((q, i) => answers[i] === q.answer_index).length

  return (
    <div className="card p-4">
      <h3 className="text-base font-bold">{t('result.lesson')}</h3>
      <p className="mt-1 text-lg font-extrabold">{lesson.title}</p>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{lesson.body}</p>

      {lesson.key_takeaways.length > 0 && (
        <>
          <p className="mt-3 text-sm font-bold">{t('learn.takeaways')}</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {lesson.key_takeaways.map((k, i) => (
              <li key={i}>{k}</li>
            ))}
          </ul>
        </>
      )}

      {lesson.quiz.length > 0 && (
        <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
          <p className="text-sm font-bold">{t('learn.quiz')}</p>
          {lesson.quiz.map((q, qi) => (
            <fieldset key={qi} className="mt-3">
              <legend className="text-sm font-semibold">{`${qi + 1}. ${q.question}`}</legend>
              <div className="mt-1.5 space-y-1.5">
                {q.options.map((opt, oi) => {
                  const chosen = answers[qi] === oi
                  const isRight = checked && oi === q.answer_index
                  const isWrong = checked && chosen && oi !== q.answer_index
                  return (
                    <label
                      key={oi}
                      className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${
                        isRight
                          ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-900/30'
                          : isWrong
                            ? 'border-red-400 bg-red-50 dark:bg-red-900/30'
                            : chosen
                              ? 'border-brand-400 bg-brand-50 dark:bg-brand-900/25'
                              : 'border-slate-200 dark:border-slate-700'
                      }`}
                    >
                      <input
                        type="radio"
                        name={`q${qi}`}
                        checked={chosen ?? false}
                        onChange={() => setAnswers((a) => ({ ...a, [qi]: oi }))}
                        className="size-4"
                      />
                      <span>{opt}</span>
                    </label>
                  )
                })}
              </div>
              {checked && q.explanation && <p className="muted mt-1 text-xs">{q.explanation}</p>}
            </fieldset>
          ))}
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setChecked(true)}
              disabled={Object.keys(answers).length !== lesson.quiz.length}
              className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-bold text-white disabled:opacity-50"
            >
              {t('learn.submit')}
            </button>
            {checked && (
              <span className="text-sm font-semibold">
                {t('learn.result', { correct, total: lesson.quiz.length })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SignalRow({ label, value }: { label: string; value: number | null | undefined }) {
  if (value === null || value === undefined) return null
  const pct = Math.round(value * 100)
  const color = pct >= 66 ? 'bg-danger' : pct >= 35 ? 'bg-warn' : 'bg-safe'
  return (
    <div className="flex items-center gap-3 py-1">
      <span className="w-40 shrink-0 text-xs font-semibold">{label}</span>
      <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <span className={`block h-full ${color}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="w-10 text-right text-xs font-bold tabular-nums">{pct}%</span>
    </div>
  )
}

export function ResultView({
  analysis,
  originalText,
  lang,
  onNewScan,
}: {
  analysis: Analysis
  originalText: string
  lang: LangCode
  onNewScan: () => void
}) {
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v)
  const [reading, setReading] = useState(false)
  const [showEvidence, setShowEvidence] = useState(false)
  const [showTrace, setShowTrace] = useState(false)
  const style = VERDICT_STYLE[analysis.verdict]
  const verdictLabel = t(verdictKey(analysis.verdict))
  const speechLang = analysis.language

  const whatsappLink = analysis.family_alert
    ? `https://wa.me/?text=${encodeURIComponent(analysis.family_alert)}`
    : null

  const readAloud = () => {
    if (reading) {
      stopSpeaking()
      setReading(false)
      return
    }
    const spoken = [
      verdictLabel,
      analysis.explanation,
      ...analysis.recommended_actions.slice(0, 4),
    ].join('. ')
    if (speak(spoken, speechLang === 'unknown' ? 'en-IN' : `${speechLang}`, () => setReading(false))) {
      setReading(true)
    }
  }

  return (
    <div className="space-y-3" style={{ animation: 'rise .45s cubic-bezier(.22,1,.36,1) both' }}>
      {/* Degraded-mode banner: honesty over polish */}
      {analysis.mode === 'local_fallback' && (
        <div className="rounded-xl bg-amber-100 p-3 text-sm text-amber-950 dark:bg-amber-900/30 dark:text-amber-100" role="status">
          <strong>{t('result.degraded')}</strong>
          {analysis.degraded_reason && <span className="muted block text-xs">{analysis.degraded_reason}</span>}
        </div>
      )}

      {/* Verdict banner */}
      <section className={`card ring-2 ${style.ring} ${style.bg} p-4`} aria-live="polite">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className={`text-2xl font-extrabold ${style.text}`}>
              <span aria-hidden="true">{style.icon}</span> {verdictLabel}
            </p>
            <p className="muted mt-1 text-sm">
              {t('result.riskScore')}: <strong className="text-base">{analysis.risk_score}/100</strong> ·{' '}
              {t('result.confidence')}: {Math.round(analysis.confidence * 100)}%
            </p>
            <p className="mt-1 flex flex-wrap gap-1.5 text-xs">
              {analysis.scam_type_label && (
                <span className="rounded-full bg-white/70 px-2 py-1 font-semibold dark:bg-black/30">
                  {t('result.type')}: {analysis.scam_type_label}
                </span>
              )}
              <span className="rounded-full bg-white/70 px-2 py-1 font-semibold dark:bg-black/30">
                {t('result.language')}: {languageName(analysis.language)}
              </span>
              <span className="rounded-full bg-white/70 px-2 py-1 font-semibold dark:bg-black/30">
                {analysis.mode === 'agent' ? t('result.llmTrace') : t('result.localTrace')}
              </span>
            </p>
          </div>
          <div className="hidden sm:block">
            <svg width="86" height="86" viewBox="0 0 36 36" role="img" aria-label={`${t('result.riskScore')} ${analysis.risk_score}`}>
              <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" strokeWidth="3" className="text-white/60" />
              <circle
                cx="18" cy="18" r="15.5" fill="none" strokeWidth="3.5" strokeLinecap="round"
                stroke={analysis.verdict === 'SCAM' ? '#dc2626' : analysis.verdict === 'SUSPICIOUS' ? '#d97706' : '#16a34a'}
                strokeDasharray={`${(analysis.risk_score / 100) * 97.4} 97.4`}
                transform="rotate(-90 18 18)"
              />
              <text x="18" y="20.5" textAnchor="middle" fontSize="9" fontWeight="800" fill="currentColor">
                {analysis.risk_score}
              </text>
            </svg>
          </div>
        </div>
      </section>

      {/* The message with highlights */}
      <section className="card p-4">
        <h2 className="text-sm font-bold uppercase tracking-wide muted">{t('result.redFlags')}</h2>
        <div className="mt-2">
          {/* HighlightedText is lazily imported below to keep this file readable */}
          <HighlightedMessage analysis={analysis} text={originalText} lang={lang} />
        </div>
        {analysis.evidence.pii_found.length > 0 && (
          <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900 dark:bg-emerald-900/25 dark:text-emerald-100">
            🛡️ {PII_BADGE_TEXT[lang] ?? PII_BADGE_TEXT.en}{' '}
            {analysis.evidence.pii_found.map((p) => p.placeholder).join(' ')}
          </p>
        )}
      </section>

      {/* Why */}
      <section className="card p-4">
        <h2 className="text-base font-bold">{t('result.why', { verdict: verdictLabel })}</h2>
        <p className="mt-2 whitespace-pre-wrap text-[1.05rem] leading-relaxed">{analysis.explanation}</p>
        {analysis.red_flags.length > 0 && (
          <ul className="mt-3 space-y-2">
            {analysis.red_flags.map((flag, i) => (
              <li
                key={i}
                className="rounded-xl border border-slate-200 p-2.5 text-sm dark:border-slate-700"
                style={{ animation: `rise .45s cubic-bezier(.22,1,.36,1) ${i * 70}ms both` }}
              >
                <span className="font-semibold text-danger">“{flag.text_span}”</span>
                <span className="muted"> — {flag.reason}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          {speechOutputSupported() && (
            <button
              type="button"
              onClick={readAloud}
              className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold dark:border-slate-600"
              aria-label={reading ? t('result.stopReading') : t('result.readAloud')}
            >
              {reading ? `⏹ ${t('result.stopReading')}` : `🔊 ${t('result.readAloud')}`}
            </button>
          )}
          <CopyButton text={`${verdictLabel}. ${analysis.explanation}`} lang={lang} />
        </div>
      </section>

      {/* Actions */}
      <section className="card p-4">
        <h2 className="text-base font-bold">{t('result.whatToDo')}</h2>
        <ol className="mt-2 space-y-2">
          {analysis.recommended_actions.map((action, i) => (
            <li
              key={i}
              className="flex items-start gap-3 rounded-xl bg-slate-50 p-2.5 text-sm dark:bg-slate-800/60"
              style={{ animation: `rise .45s cubic-bezier(.22,1,.36,1) ${i * 60}ms both` }}
            >
              <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
                {i + 1}
              </span>
              <span className="flex-1 leading-relaxed">{action}</span>
              <CopyButton text={action} lang={lang} label={`step ${i + 1}`} />
            </li>
          ))}
        </ol>
        <CopyButton text={analysis.recommended_actions.map((a, i) => `${i + 1}. ${a}`).join('\n')} lang={lang} label={t('result.copyAll')} />
      </section>

      {/* Family Mode */}
      {analysis.family_alert && (
        <section className="card border-brand-200 p-4 dark:border-brand-800">
          <h2 className="text-base font-bold">👨‍👩‍👧 {t('result.familyMode')}</h2>
          <p className="muted mt-1 text-sm">{t('result.familyHint')}</p>
          <p className="mt-2 whitespace-pre-wrap rounded-xl bg-brand-50 p-3 text-sm dark:bg-brand-900/25">{analysis.family_alert}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <a
              href={whatsappLink ?? '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-xl bg-[#25D366] px-3 py-2 text-sm font-bold text-[#0b3d24]"
            >
              {t('result.shareWhatsapp')}
            </a>
            <CopyButton text={analysis.family_alert} lang={lang} />
          </div>
        </section>
      )}

      {/* Report draft */}
      {analysis.report_draft && (
        <section className="card p-4">
          <h2 className="text-base font-bold">📄 {t('result.reportDraft')}</h2>
          <p className="muted mt-1 text-sm">{t('result.reportHint')}</p>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
            {analysis.report_draft}
          </pre>
          <CopyButton text={analysis.report_draft} lang={lang} />
        </section>
      )}

      {/* Lesson */}
      {analysis.lesson && <LessonQuizCard lesson={analysis.lesson} lang={lang} />}

      {/* Evidence */}
      <section className="card p-4">
        <button
          type="button"
          onClick={() => setShowEvidence((v) => !v)}
          aria-expanded={showEvidence}
          className="flex w-full items-center justify-between text-left"
        >
          <span className="text-base font-bold">🔬 {t('result.evidence')}</span>
          <span aria-hidden="true">{showEvidence ? '▾' : '▸'}</span>
        </button>
        {showEvidence && (
          <div className="mt-3 space-y-3">
            <SignalRow label={t('result.score.ml')} value={analysis.evidence.ml_score} />
            <SignalRow label={t('result.score.url')} value={analysis.evidence.url_score} />
            <SignalRow label={t('result.score.pattern')} value={analysis.evidence.pattern_score} />
            <SignalRow label={t('result.score.llm')} value={analysis.evidence.llm_score} />
            <p className="muted text-xs">{t('result.weightsNote')}</p>
            {analysis.evidence.ensemble_breakdown?.effective_weights && (
              <p className="muted text-xs">
                {Object.entries(analysis.evidence.ensemble_breakdown.effective_weights)
                  .filter(([, w]) => (w as number) > 0)
                  .map(([k, w]) => `${k} ${Math.round((w as number) * 100)}%`)
                  .join(' · ')}
              </p>
            )}
            {analysis.evidence.ensemble_breakdown?.model_disagreement && (
              <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-900/25 dark:text-amber-100">
                {analysis.evidence.ensemble_breakdown.model_disagreement}
              </p>
            )}

            {analysis.evidence.actionability?.explanation && (
              <div>
                <p className="text-xs font-bold uppercase muted">Actionability check</p>
                <p className="mt-1 text-sm">{analysis.evidence.actionability.explanation}</p>
                {analysis.evidence.actionability.ask_keywords?.length > 0 && (
                  <p className="muted mt-0.5 text-xs">
                    Requests found: {analysis.evidence.actionability.ask_keywords.join(', ')}
                  </p>
                )}
              </div>
            )}

            {analysis.evidence.pattern_matches.length > 0 && (
              <div>
                <p className="text-xs font-bold uppercase muted">Pattern library</p>
                <ul className="mt-1 space-y-1 text-sm">
                  {analysis.evidence.pattern_matches.map((m) => (
                    <li key={m.pattern_id}>
                      <span className="font-semibold">{m.pattern_id}</span> · score {Math.round(m.score * 100)}%
                      {m.matched_keywords.length > 0 && (
                        <span className="muted"> · matched: {m.matched_keywords.slice(0, 5).join(', ')}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {analysis.evidence.url_findings.length > 0 && (
              <div>
                <p className="text-xs font-bold uppercase muted">Link findings</p>
                <ul className="mt-1 space-y-1 text-sm">
                  {analysis.evidence.url_findings.map((f, i) => (
                    <li key={i}>
                      <span className="font-semibold">{f.type}</span> — {f.detail}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {analysis.evidence.top_tokens.length > 0 && (
              <div>
                <p className="text-xs font-bold uppercase muted">{t('result.tokens')}</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {analysis.evidence.top_tokens.slice(0, 10).map((tok, i) => (
                    <span
                      key={i}
                      className="rounded-full px-2 py-0.5 text-xs font-semibold"
                      style={{
                        background: `color-mix(in srgb, var(--color-danger) ${Math.round(tok.contribution * 40)}%, transparent)`,
                      }}
                    >
                      {tok.text ?? tok.token} · {tok.contribution.toFixed(2)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Agent trace */}
      <section className="card p-4">
        <button
          type="button"
          onClick={() => setShowTrace((v) => !v)}
          aria-expanded={showTrace}
          className="flex w-full items-center justify-between text-left"
        >
          <span className="text-base font-bold">🧭 {t('result.agentTrace')}</span>
          <span aria-hidden="true">{showTrace ? '▾' : '▸'}</span>
        </button>
        {showTrace && (
          <>
            <p className="muted mt-1 text-xs">{t('result.agentTraceHint')}</p>
            <ol className="mt-2 space-y-1.5 text-sm">
              {analysis.evidence.agent_steps.map((step) => (
                <li key={step.step} className="flex items-start gap-2 rounded-lg bg-slate-50 p-2 dark:bg-slate-800/60">
                  <span className="font-mono text-xs muted">{String(step.step).padStart(2, '0')}</span>
                  <span className="flex-1">
                    <span className="font-semibold">{step.tool}</span>
                    <span className="muted"> · {step.source === 'agent_call' ? 'agent call' : 'precomputed'} · {step.duration_ms} ms</span>
                    <span className="muted block text-xs">{step.summary}</span>
                  </span>
                  <span aria-hidden="true">{step.ok ? '✓' : '⚠'}</span>
                </li>
              ))}
            </ol>
            {analysis.evidence.model_versions && (
              <p className="muted mt-2 text-xs">
                {Object.entries(analysis.evidence.model_versions)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(' · ')}
              </p>
            )}
          </>
        )}
      </section>

      <button
        type="button"
        onClick={onNewScan}
        className="w-full rounded-xl bg-brand-600 px-4 py-3 text-base font-bold text-white"
      >
        {t('result.newScan')}
      </button>
    </div>
  )
}

// Kept as a tiny local component so the highlight logic stays in one place.
function HighlightedMessage({ analysis, text, lang }: { analysis: Analysis; text: string; lang: LangCode }) {
  const shown = text && text.trim().length > 0 ? text : analysis.scam_type_label || ''
  return <HighlightedText text={shown} redFlags={analysis.red_flags} evidence={analysis.evidence} />
}

export default ResultView
