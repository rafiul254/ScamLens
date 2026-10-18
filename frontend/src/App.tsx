import { useEffect, useState } from 'react'
import { HashRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { LANGUAGES, translate, type LangCode } from './lib/i18n'
import { getDeviceId, useOnboarding, useOnlineStatus, useSettings } from './lib/store'
import type { Analysis } from './lib/types'
import { Logo } from './components/Logo'
import Onboarding from './components/Onboarding'
import Home from './pages/Home'
import Learn from './pages/Learn'
import Benchmark from './pages/Benchmark'
import HistoryPage from './pages/History'
import About from './pages/About'
import ResultPage from './pages/ResultPage'
import InputTabs from './components/InputTabs'

const LAST_KEY = 'scamlens.last_analysis'

function Layout({
  lang,
  settings,
  update,
  deviceId,
}: {
  lang: LangCode
  settings: ReturnType<typeof useSettings>['settings']
  update: ReturnType<typeof useSettings>['update']
  deviceId: string
}) {
  const [showSettings, setShowSettings] = useState(false)
  const online = useOnlineStatus()
  const t = (k: string) => translate(lang, k)
  const location = useLocation()

  const navItems = [
    { to: '/', label: t('nav.home'), icon: '🔍' },
    { to: '/learn', label: t('nav.learn'), icon: '🎓' },
    { to: '/benchmark', label: t('nav.benchmark'), icon: '📈' },
    { to: '/history', label: t('nav.history'), icon: '🗂️' },
    { to: '/about', label: t('nav.about'), icon: 'ℹ️' },
  ]

  return (
    <div
      className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col px-3 sm:pb-4"
      style={{ paddingBottom: 'calc(6rem + env(safe-area-inset-bottom, 0px))' }}
    >
      <header className="sticky top-0 z-30 -mx-3 flex items-center justify-between gap-2 border-b border-slate-200 bg-[#f7fafc]/95 px-3 py-2.5 backdrop-blur dark:border-slate-800 dark:bg-[#071722]/95">
        <a href="#/" className="shrink-0">
          <Logo />
        </a>
        <div className="flex items-center gap-1">
          {!online && <span className="rounded-full bg-amber-100 px-2 py-1 text-[0.65rem] font-bold text-amber-900">offline</span>}
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            aria-label={t('a11y.settings')}
            data-testid="open-settings"
            className="rounded-xl border border-slate-300 px-2.5 text-sm font-bold dark:border-slate-600"
          >
            ⚙︎
          </button>
        </div>
      </header>

      <main className="flex-1 py-3">
        <Routes>
          <Route path="/" element={<Home lang={lang} deviceId={deviceId} onResult={storeLast} />} />
          <Route path="/result" element={<ResultPage lang={lang} deviceId={deviceId} />} />
          <Route path="/learn" element={<Learn lang={lang} deviceId={deviceId} />} />
          <Route path="/benchmark" element={<Benchmark lang={lang} />} />
          <Route path="/history" element={<HistoryPage lang={lang} deviceId={deviceId} onResult={storeLast} />} />
          <Route path="/about" element={<About lang={lang} />} />
        </Routes>
      </main>

      {/* Desktop top nav */}
      <nav className="hidden gap-1 border-t border-slate-200 pt-2 sm:flex dark:border-slate-800">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex-1 rounded-xl px-2 py-2 text-center text-xs font-bold transition ${
                isActive ? 'bg-brand-600 text-white' : 'bg-slate-100 dark:bg-slate-800'
              }`
            }
          >
            <span aria-hidden="true">{item.icon}</span> {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Mobile bottom nav */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-slate-200 bg-white/95 backdrop-blur sm:hidden dark:border-slate-800 dark:bg-slate-900/95"
      >
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 py-2 text-[0.65rem] font-bold ${isActive ? 'text-brand-700 dark:text-brand-300' : 'muted'}`
            }
          >
            <span aria-hidden="true" className="text-lg leading-none">
              {item.icon}
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-end bg-black/40 p-0 sm:items-center sm:justify-center sm:p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-t-2xl bg-white p-4 sm:rounded-2xl dark:bg-slate-900">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-extrabold">{t('a11y.settings')}</h2>
              <button type="button" onClick={() => setShowSettings(false)} className="px-2 py-1 font-bold" aria-label={t('common.close')}>
                ✕
              </button>
            </div>

            <p className="mt-3 text-sm font-bold">{t('a11y.language')}</p>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => update({ language: l.code as LangCode })}
                  aria-pressed={settings.language === l.code}
                  className={`rounded-xl px-3 py-2.5 text-sm font-bold ${
                    settings.language === l.code ? 'bg-brand-600 text-white' : 'bg-slate-100 dark:bg-slate-800'
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>

            <div className="mt-4 space-y-2">
              <Toggle label={t('a11y.theme')} checked={settings.theme === 'dark'} onChange={(v) => update({ theme: v ? 'dark' : 'light' })} />
              <Toggle label={t('a11y.largeText')} checked={settings.largeText} onChange={(v) => update({ largeText: v })} />
              <Toggle label={t('a11y.highContrast')} checked={settings.highContrast} onChange={(v) => update({ highContrast: v })} />
            </div>

            <p className="muted mt-4 text-xs">
              device id: <code>{deviceId.slice(0, 8)}…</code> · {t('hist.privacy')}
            </p>
            <button
              type="button"
              onClick={() => setShowSettings(false)}
              className="mt-3 w-full rounded-xl bg-brand-600 px-4 py-2.5 font-bold text-white"
            >
              {t('common.close')}
            </button>
          </div>
        </div>
      )}
      {location.pathname === '/result' ? null : null}
    </div>
  )
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2.5 text-sm font-semibold dark:bg-slate-800/60">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-5" role="switch" />
    </label>
  )
}

/** Keeps the last analysis in sessionStorage so the result page survives a refresh. */
export function storeLast(analysis: Analysis, original: string) {
  try {
    sessionStorage.setItem(LAST_KEY, JSON.stringify({ analysis, original }))
  } catch {
    /* ignore */
  }
}

export function readLast(): { analysis: Analysis; original: string } | null {
  try {
    const raw = sessionStorage.getItem(LAST_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function useDeviceId() {
  const [id] = useState(() => getDeviceId())
  return id
}

export default function App() {
  const { settings, update } = useSettings()
  const { needed, finish } = useOnboarding()
  const deviceId = useDeviceId()
  const lang = settings.language

  useEffect(() => {
    document.title = 'ScamLens — check a message before you trust it'
  }, [])

  return (
    <HashRouter>
      {needed && <Onboarding lang={lang} onDone={finish} />}
      <Layout lang={lang} settings={settings} update={update} deviceId={deviceId} />
    </HashRouter>
  )
}

export { InputTabs }
