import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { DemoSample } from '../lib/types'

/**
 * Demo Mode: one tap runs a realistic sample through the real pipeline.
 * Samples are synthetic and labelled with what a careful human analyst would
 * decide — including two "legitimate" controls, so judges can see the product
 * is not a machine that shouts "scam" at everything.
 */
export function DemoCarousel({
  lang,
  onPick,
  busy,
}: {
  lang: LangCode
  onPick: (sample: DemoSample) => void
  busy: boolean
}) {
  const [samples, setSamples] = useState<DemoSample[]>([])
  const [open, setOpen] = useState(true)

  useEffect(() => {
    api
      .samples()
      .then((data) => setSamples(data.samples ?? []))
      .catch(() => setSamples([]))
  }, [])

  if (!samples.length) return null
  const t = (k: string) => translate(lang, k)

  return (
    <section className="card p-3 sm:p-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="min-w-0 pr-3">
          <span className="text-base font-bold">⚡ {t('home.samples')}</span>
          {/* the chevron is on the right; keep the sentence clear of it */}
          <span className="muted block pr-1 text-xs">{t('home.samplesHint')}</span>
        </span>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <ul className="mt-3 flex snap-x gap-2 overflow-x-auto pb-1">
          {samples.map((sample) => (
            <li key={sample.id} className="w-[232px] shrink-0 snap-start">
              <button
                type="button"
                disabled={busy}
                onClick={() => onPick(sample)}
                className="card h-full w-full p-3 text-left transition hover:-translate-y-0.5 disabled:opacity-60"
              >
                <span className="flex items-center justify-between text-[0.7rem] font-bold uppercase tracking-wide">
                  <span className="muted">{sample.kind.replace('_', ' ')}</span>
                  <span className="flex gap-1">
                    <span className="rounded-full bg-slate-100 px-1.5 py-0.5 dark:bg-slate-700">{sample.language}</span>
                    <span
                      className={`rounded-full px-1.5 py-0.5 ${
                        sample.expected === 'SAFE'
                          ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100'
                          : sample.expected === 'SUSPICIOUS'
                            ? 'bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100'
                            : 'bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-100'
                      }`}
                      title="What a careful human analyst would decide"
                    >
                      {sample.expected}
                    </span>
                  </span>
                </span>
                <span className="mt-1.5 block text-sm font-bold leading-snug">
                  {sample.title[lang] ?? sample.title.en}
                </span>
                <span className="muted mt-1 line-clamp-3 block text-xs leading-snug">{sample.text.slice(0, 120)}…</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default DemoCarousel
