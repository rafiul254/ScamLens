import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { Analysis, HistoryEntry } from '../lib/types'

const DOT: Record<string, string> = { SAFE: 'bg-safe', SUSPICIOUS: 'bg-warn', SCAM: 'bg-danger' }

export function HistoryPage({
  lang,
  deviceId,
  onResult,
}: {
  lang: LangCode
  deviceId: string
  onResult: (analysis: Analysis, original: string) => void
}) {
  const [items, setItems] = useState<HistoryEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const t = (k: string) => translate(lang, k)
  const navigate = useNavigate()

  const load = () => {
    setLoading(true)
    api
      .history(deviceId)
      .then((d) => {
        setItems(d.items)
        setTotal(d.total)
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(load, [deviceId])

  const open = async (id: string) => {
    try {
      const analysis = await api.historyItem(deviceId, id)
      onResult(analysis, analysis.evidence?.top_tokens?.[0]?.text ?? '')
      navigate('/result')
    } catch {
      setMessage(t('common.error'))
    }
  }

  const wipe = async () => {
    setConfirming(false)
    try {
      await api.deleteAll(deviceId)
      setMessage(t('hist.deleted'))
      load()
    } catch {
      setMessage(t('common.error'))
    }
  }

  return (
    <div className="space-y-4 pb-4">
      <header className="pt-2">
        <h1 className="text-2xl font-extrabold">{t('hist.title')}</h1>
        <p className="muted mt-1 text-sm">{t('hist.privacy')}</p>
      </header>

      {message && <p className="card p-3 text-sm">{message}</p>}

      {loading && (
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-16 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && items.length === 0 && <p className="card p-4 text-sm muted">{t('hist.empty')}</p>}

      {items.length > 0 && (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => open(item.id)}
                className="card flex w-full items-center gap-3 p-3 text-left transition hover:-translate-y-0.5"
              >
                <span className={`size-2.5 shrink-0 rounded-full ${DOT[item.verdict] ?? 'bg-slate-400'}`} aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 text-xs muted">
                    <span className="font-bold uppercase">{item.verdict}</span>
                    <span>· {item.risk_score}/100</span>
                    <span>· {new Date(item.created_at).toLocaleString()}</span>
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-sm">{item.preview}</span>
                </span>
                <span className="text-xs font-bold text-brand-700 dark:text-brand-300">{t('hist.view')} →</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {total > 0 && (
        <section className="card border-red-200 p-4 dark:border-red-900">
          <h2 className="text-base font-bold">{t('hist.deleteAll')}</h2>
          {!confirming ? (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="mt-2 rounded-xl border border-red-300 px-3 py-2 text-sm font-bold text-red-700 dark:border-red-800 dark:text-red-300"
            >
              {t('hist.deleteAll')}
            </button>
          ) : (
            <div className="mt-2">
              <p className="text-sm">{t('hist.deleteConfirm')}</p>
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={wipe} className="rounded-xl bg-danger px-3 py-2 text-sm font-bold text-white">
                  {t('hist.deleteAll')}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold dark:border-slate-600"
                >
                  {t('common.close')}
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

export default HistoryPage
