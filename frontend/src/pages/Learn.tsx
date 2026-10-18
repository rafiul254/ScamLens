import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { PatternCard, ScamIQ } from '../lib/types'
import { LessonPanel } from '../components/LessonPanel'

const CATEGORIES = ['all', 'credential_theft', 'phishing', 'advance_fee', 'investment', 'authority', 'impersonation', 'remote_access', 'blackmail', 'greed'] as const

export function Learn({ lang, deviceId }: { lang: LangCode; deviceId: string }) {
  const [patterns, setPatterns] = useState<PatternCard[]>([])
  const [filter, setFilter] = useState<string>('all')
  const [active, setActive] = useState<PatternCard | null>(null)
  const [iq, setIq] = useState<ScamIQ | null>(null)
  const [error, setError] = useState<string | null>(null)
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v)
  const navigate = useNavigate()

  useEffect(() => {
    api.patterns().then((d) => setPatterns(d.patterns)).catch(() => setError(t('common.error')))
    api.scamIq(deviceId).then(setIq).catch(() => undefined)
  }, [deviceId])

  const shown = patterns.filter((p) => filter === 'all' || p.category === filter)
  const badgeCount = iq?.badges.length ?? 0

  return (
    <div className="space-y-4 pb-4">
      <header className="pt-2">
        <h1 className="text-2xl font-extrabold">{t('learn.title')}</h1>
        <p className="muted mt-1 text-sm">{t('learn.subtitle')}</p>
      </header>

      {/* Scam IQ */}
      {iq && (
        <section className="card p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold">🎯 {t('learn.iq')}</h2>
            <span className="rounded-full bg-brand-600 px-3 py-1 text-sm font-bold text-white">{iq.level}</span>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60">
              <p className="text-xl font-extrabold text-brand-700 dark:text-brand-300">{iq.score}</p>
              <p className="muted text-xs">Scam IQ</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60">
              <p className="text-xl font-extrabold">{iq.streak_days}🔥</p>
              <p className="muted text-xs">{t('learn.streak')}</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60">
              <p className="text-xl font-extrabold">{iq.lessons_completed}</p>
              <p className="muted text-xs">{t('learn.lessons')}</p>
            </div>
          </div>
          <div className="mt-3">
            <p className="text-sm font-bold">
              {t('learn.badges')} {badgeCount > 0 && <span className="muted">({badgeCount})</span>}
            </p>
            {badgeCount === 0 ? (
              <p className="muted text-xs">{t('learn.noBadges')}</p>
            ) : (
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {iq.badges.map((b) => (
                  <li
                    key={b.id}
                    title={b.description}
                    className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-bold text-amber-900 dark:bg-amber-900/40 dark:text-amber-100"
                  >
                    🏅 {b.title}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {error && <p className="card p-3 text-sm text-danger">{error}</p>}

      {/* Pattern library */}
      <section>
        <h2 className="px-1 text-base font-bold">{t('learn.patterns')}</h2>
        <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setFilter(c)}
              className={`shrink-0 rounded-xl px-3 py-1.5 text-xs font-bold ${
                filter === c ? 'bg-brand-600 text-white' : 'bg-slate-100 dark:bg-slate-800'
              }`}
            >
              {c === 'all' ? t('learn.filterAll') : c.replace(/_/g, ' ')}
            </button>
          ))}
        </div>

        <ul className="mt-2 grid gap-2 sm:grid-cols-2">
          {shown.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => setActive(p)}
                className="card h-full w-full p-3 text-left transition hover:-translate-y-0.5"
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="text-sm font-bold leading-snug">{p.name[lang] ?? p.name.en}</span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[0.65rem] font-bold ${
                      p.severity >= 0.9
                        ? 'bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-100'
                        : p.severity >= 0.8
                          ? 'bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100'
                          : 'bg-slate-100 dark:bg-slate-700'
                    }`}
                    title={`${t('learn.severity')}: ${Math.round(p.severity * 100)}%`}
                  >
                    {Math.round(p.severity * 100)}%
                  </span>
                </span>
                <span className="muted mt-1 line-clamp-3 block text-xs leading-snug">
                  {p.summary[lang] ?? p.summary.en}
                </span>
                <span className="mt-2 block text-xs font-bold text-brand-700 dark:text-brand-300">
                  {t('learn.openLesson')} →
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {active && (
        <LessonPanel
          pattern={active}
          lang={lang}
          deviceId={deviceId}
          onClose={() => setActive(null)}
          onIqUpdate={setIq}
          onTryCheck={() => {
            setActive(null)
            navigate('/')
          }}
        />
      )}
    </div>
  )
}

export default Learn
