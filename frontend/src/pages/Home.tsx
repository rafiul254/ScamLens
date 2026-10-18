import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import { redactPii } from '../lib/pii'
import type { Analysis, DemoSample, Stats } from '../lib/types'
import DemoCarousel from '../components/DemoCarousel'
import InputTabs, { type SubmissionPayload } from '../components/InputTabs'

export function Home({
  lang,
  deviceId,
  onResult,
}: {
  lang: LangCode
  deviceId: string
  onResult: (analysis: Analysis, original: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [pendingText, setPendingText] = useState('')
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v)
  const navigate = useNavigate()

  useEffect(() => {
    api.stats(deviceId).then(setStats).catch(() => setStats(null))
  }, [deviceId])

  const handle = async (payload: SubmissionPayload) => {
    setBusy(true)
    setError(null)
    try {
      // Privacy: the browser redacts PII before anything is uploaded.
      const redacted = redactPii(payload.text).text
      let analysis: Analysis
      if (payload.kind === 'image' && payload.file) {
        analysis = await api.analyzeImage(payload.file, deviceId, redacted)
      } else if (payload.kind === 'url') {
        analysis = await api.analyzeUrl(payload.text.trim(), deviceId, lang)
      } else {
        analysis = await api.analyzeText(redacted, deviceId, payload.kind)
      }
      onResult(analysis, payload.text)
      navigate('/result')
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.status === 429) setError(t('common.rateLimited'))
      else if (apiErr.status === 0) setError(t('common.offline'))
      else setError(apiErr.message || t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const runSample = async (sample: DemoSample) => {
    setBusy(true)
    setError(null)
    setPendingText(sample.text)
    try {
      const analysis = await api.analyzeText(
        redactPii(sample.text).text,
        deviceId,
        sample.kind === 'audio_transcript' ? 'audio_transcript' : 'text',
      )
      onResult(analysis, sample.text)
      navigate('/result')
    } catch (err) {
      const apiErr = err as ApiError
      setError(apiErr.status === 0 ? t('common.offline') : apiErr.message || t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <header className="pt-2">
        <h1 className="text-2xl font-extrabold leading-tight sm:text-3xl">{t('home.title')}</h1>
        <p className="muted mt-1.5 text-sm leading-relaxed">{t('home.subtitle')}</p>
      </header>

      {error && (
        <div role="alert" className="card border-red-300 p-3 text-sm text-red-800 dark:text-red-200">
          {error}
        </div>
      )}

      <InputTabs lang={lang} busy={busy} onSubmit={handle} initialText={pendingText} />

      <DemoCarousel lang={lang} onPick={runSample} busy={busy} />

      {stats && stats.total_scans > 0 && (
        <section className="card p-4">
          <h2 className="text-base font-bold">📊 {t('stats.title')}</h2>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            <Stat value={stats.total_scans} label={t('stats.total')} />
            <Stat value={stats.scam_count} label={t('stats.scam')} tone="danger" />
            <Stat value={stats.suspicious_count} label={t('result.verdict.suspicious')} tone="warn" />
          </div>
          {stats.by_type.length > 0 && (
            <ul className="mt-3 space-y-1">
              {stats.by_type.slice(0, 4).map((row) => (
                <li key={row.scam_type} className="flex items-center justify-between text-sm">
                  <span className="font-semibold">{row.scam_type.replace(/_/g, ' ')}</span>
                  <span className="muted">{row.count}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="muted mt-2 text-xs">{stats.privacy_note}</p>
        </section>
      )}

      <p className="muted px-1 pb-4 text-center text-xs leading-relaxed">{t('home.privacy')}</p>
    </div>
  )
}

function Stat({ value, label, tone }: { value: number; label: string; tone?: 'danger' | 'warn' }) {
  const color = tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : 'text-brand-700 dark:text-brand-300'
  return (
    <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60">
      <p className={`text-xl font-extrabold ${color}`}>{value}</p>
      <p className="muted text-xs">{label}</p>
    </div>
  )
}

export default Home
