import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { readLast, storeLast } from '../App'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { Analysis } from '../lib/types'
import ResultView from '../components/ResultView'
import RiskGauge from '../components/RiskGauge'

/** The message languages a result can come back in. */
const LANGS: Record<string, string> = { en: 'English', bn: '\u09ac\u09be\u0982\u09b2\u09be', hi: '\u0939\u093f\u0928\u094d\u0926\u0940', ur: '\u0627\u0631\u062f\u0648' }

export function ResultPage({ lang, deviceId }: { lang: LangCode; deviceId: string }) {
  const [data, setData] = useState<{ analysis: Analysis; original: string } | null>(null)
  const [translating, setTranslating] = useState(false)
  const navigate = useNavigate()
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v)

  useEffect(() => {
    try {
      // Oldest-first attempt in case the user refreshed after the tab idled.
      const stored = readLast()
      if (stored?.analysis) setData(stored)
    } catch {
      setData(null)
    }
  }, [])

  if (!data) {
    return (
      <div className="card p-6 text-center">
        <p className="text-base font-semibold">{t('hist.empty')}</p>
        <Link to="/" className="mt-3 inline-block rounded-xl bg-brand-600 px-4 py-2.5 font-bold text-white">
          {t('nav.home')}
        </Link>
      </div>
    )
  }

  const { analysis, original } = data

  // A Bangla message produces a Bangla verdict — correct, but a reader who cannot read
  // Bangla should still get the explanation. One tap re-runs the same message and asks
  // the agent for its output in the interface language.
  const canTranslate = Boolean(original) && analysis.language !== lang && analysis.language !== 'unknown'

  async function readIn(language: LangCode) {
    if (!original) return
    setTranslating(true)
    try {
      const fresh = await api.analyzeText(original, deviceId, 'text', language)
      const next = { analysis: fresh, original }
      setData(next)
      storeLast(fresh, original)
    } catch {
      /* keep the original result if the re-run fails */
    } finally {
      setTranslating(false)
    }
  }

  // The message shown for highlighting: the original submission text, or the
  // preview returned in evidence when the result came from history.
  const shownText = original || (analysis.evidence?.top_tokens ?? []).map((tk) => tk.text ?? '').join(' ')

  return (
    <div className="space-y-3">
      <div className="sm:hidden">
        <div className="card flex items-center justify-between p-3">
          <RiskGauge score={analysis.risk_score} verdict={analysis.verdict} label={t('result.riskScore')} size={140} />
          <div className="text-right">
            <p className="text-sm font-bold">{t('result.confidence')}</p>
            <p className="text-2xl font-extrabold">{Math.round(analysis.confidence * 100)}%</p>
          </div>
        </div>
      </div>
      {canTranslate && (
        <div className="card flex items-center justify-between gap-3 p-3 text-sm">
          <p className="muted">
            {t('result.otherLanguage', { language: LANGS[analysis.language] ?? analysis.language })}
          </p>
          <button
            type="button"
            onClick={() => readIn(lang)}
            disabled={translating}
            className="shrink-0 rounded-lg border border-brand-500 px-3 py-1.5 font-semibold text-brand-600 disabled:opacity-50"
          >
            {translating ? t('result.translating') : t('result.readIn', { language: LANGS[lang] })}
          </button>
        </div>
      )}

      <ResultView
        analysis={analysis}
        originalText={shownText}
        lang={lang}
        onNewScan={() => {
          try {
            sessionStorage.removeItem('scamlens.last_analysis')
          } catch {
            /* ignore */
          }
          navigate('/')
        }}
      />
      {/* deviceId is intentionally only used by pages that query history */}
      <span className="hidden">{deviceId}</span>
    </div>
  )
}

export default ResultPage
