import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { Benchmark as BenchmarkData, BenchmarkModelMetrics } from '../lib/types'

function pct(v: number | undefined | null): string {
  return v === undefined || v === null ? '—' : `${(v * 100).toFixed(1)}%`
}

function ConfusionMatrix({ m, labels }: { m: number[][]; labels: string[] }) {
  const [[tn, fp], [fn, tp]] = m
  const cells = [
    { value: tn, label: labels[0], tone: 'safe' },
    { value: fp, label: labels[1], tone: 'warn' },
    { value: fn, label: labels[2], tone: 'warn' },
    { value: tp, label: labels[3], tone: 'safe' },
  ]
  return (
    <div className="grid max-w-xs grid-cols-2 gap-1.5">
      {cells.map((c) => (
        <div
          key={c.label}
          className={`rounded-xl p-2 text-center ${
            c.tone === 'safe' ? 'bg-emerald-50 dark:bg-emerald-900/25' : 'bg-amber-50 dark:bg-amber-900/25'
          }`}
        >
          <p className="text-lg font-extrabold tabular-nums">{c.value}</p>
          <p className="muted text-[0.65rem] leading-tight">{c.label}</p>
        </div>
      ))}
    </div>
  )
}

function RocChart({ curve, color = '#1e6ff0' }: { curve: { fpr: number[]; tpr: number[] }; color?: string }) {
  const size = 220
  const path = curve.fpr.map((x, i) => `${i === 0 ? 'M' : 'L'} ${x * size} ${size - curve.tpr[i] * size}`).join(' ')
  return (
    <svg viewBox={`-18 -8 ${size + 34} ${size + 30}`} className="w-full max-w-[240px]" role="img"
      aria-label="ROC curve">
      <rect x="0" y="0" width={size} height={size} fill="none" stroke="#94a3b8" strokeWidth="1" />
      <line x1="0" y1={size} x2={size} y2="0" stroke="#cbd5e1" strokeWidth="1" strokeDasharray="4 4" />
      <path d={path} fill="none" stroke={color} strokeWidth="2.5" />
      <text x={size / 2} y={size + 18} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.7">
        false positive rate
      </text>
      <text x={-10} y={size / 2} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.7"
        transform={`rotate(-90 -10 ${size / 2})`}>
        true positive rate
      </text>
    </svg>
  )
}

function ModelRow({ name, m, t, unavailable }: { name: string; m?: BenchmarkModelMetrics; t: (k: string) => string; unavailable?: boolean }) {
  if (!m) {
    return (
      <tr className="border-t border-slate-200 dark:border-slate-700">
        <td className="p-2 font-semibold">{name}</td>
        <td colSpan={4} className="p-2 text-xs muted">
          {unavailable ? t('bench.notEvaluated') : '—'}
        </td>
      </tr>
    )
  }
  return (
    <tr className="border-t border-slate-200 dark:border-slate-700">
      <td className="p-2">
        <span className="font-semibold">{name}</span>
        {m.label && <span className="muted block text-[0.68rem] leading-tight">{m.label}</span>}
      </td>
      <td className="p-2 text-right tabular-nums">{pct(m.precision)}</td>
      <td className="p-2 text-right tabular-nums">{pct(m.recall)}</td>
      <td className="p-2 text-right font-bold tabular-nums">{pct(m.f1)}</td>
      <td className="p-2 text-right tabular-nums">{m.roc_auc?.toFixed(4) ?? '—'}</td>
    </tr>
  )
}

export function Benchmark({ lang }: { lang: LangCode }) {
  const [data, setData] = useState<BenchmarkData | null>(null)
  const [loading, setLoading] = useState(true)
  const t = (k: string) => translate(lang, k)

  useEffect(() => {
    api
      .benchmark()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="space-y-2 pt-4" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card h-24 animate-pulse" />
        ))}
      </div>
    )
  }

  const shipped = data?.shipped_pipeline?.results?.ensemble_override

  return (
    <div className="space-y-4 pb-4">
      <header className="pt-2">
        <h1 className="text-2xl font-extrabold">{t('bench.title')}</h1>
        <p className="muted mt-1 text-sm leading-relaxed">{t('bench.subtitle')}</p>
      </header>

      {!data?.available && (
        <div className="card border-amber-300 p-4 text-sm">
          <p className="font-bold">{t('bench.unavailable')}</p>
        </div>
      )}

      {data?.available && (
        <>
          <section className="card p-4">
            <h2 className="text-base font-bold">{t('bench.dataset')}</h2>
            <p className="muted mt-1 text-xs">{t('bench.generated')}: {data.generated_at?.slice(0, 19).replace('T', ' ')} UTC</p>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="muted text-xs">Rows (train / val / test)</dt>
                <dd className="font-semibold">
                  {data.dataset?.train_rows} / {data.dataset?.validation_rows} / {data.dataset?.test_rows}
                </dd>
              </div>
              <div>
                <dt className="muted text-xs">Test positive rate</dt>
                <dd className="font-semibold">{pct(data.dataset?.test_positive_rate)}</dd>
              </div>
            </dl>
            <p className="muted mt-2 text-xs">{data.dataset?.name}</p>
            {data.dataset?.languages && (
              <p className="muted mt-1 text-xs">
                Test split languages: {Object.entries(data.dataset.languages).map(([k, v]) => `${k}:${v}`).join(' · ')}
              </p>
            )}
          </section>

          <section className="card overflow-x-auto p-4">
            <h2 className="text-base font-bold">{t('bench.compare')}</h2>
            <table className="mt-2 w-full min-w-[420px] text-sm">
              <thead>
                <tr className="muted text-xs uppercase">
                  <th className="p-2 text-left">{t('bench.model')}</th>
                  <th className="p-2 text-right">{t('bench.precision')}</th>
                  <th className="p-2 text-right">{t('bench.recall')}</th>
                  <th className="p-2 text-right">{t('bench.f1')}</th>
                  <th className="p-2 text-right">{t('bench.auc')}</th>
                </tr>
              </thead>
              <tbody>
                <ModelRow name="ML-only" m={data.models?.ml_only} t={t} />
                {shipped && (
                  <ModelRow name={t('bench.shipped')} m={shipped} t={t} />
                )}
                <ModelRow name="LLM-only (Gemini)" m={undefined} t={t} unavailable />
                <ModelRow name="Ensemble" m={data.models?.ensemble} t={t} />
                <ModelRow name="TF-IDF baseline" m={data.models?.ml_tfidf} t={t} />
                {data.models?.ml_embedding && <ModelRow name="Multilingual embeddings" m={data.models.ml_embedding} t={t} />}
              </tbody>
            </table>
            <p className="muted mt-2 text-xs">{t('bench.llmHint')}</p>
            {data.shipped_pipeline && (
              <div className="mt-3 rounded-xl border border-dashed p-3">
                <p className="text-sm font-bold">{t('bench.shipped')}</p>
                <p className="muted mt-1 text-xs leading-relaxed">{t('bench.shippedBody')}</p>
                <p className="mt-2 text-xs font-semibold">
                  {t('bench.override')}
                </p>
                <p className="muted text-xs leading-relaxed">
                  {t('bench.overrideBody').replace(
                    '{changed}',
                    String(data.shipped_pipeline.override_effect?.changed_decisions ?? 0),
                  )}
                </p>
                <p className="muted mt-1 text-[0.7rem] leading-relaxed">{data.shipped_pipeline.note}</p>
              </div>
            )}
            <p className="muted mt-1 text-xs">{data.notes}</p>
          </section>

          <section className="card p-4">
            <h2 className="text-base font-bold">{t('bench.confusion')} · {t('bench.roc')}</h2>
            <div className="mt-2 grid gap-4 sm:grid-cols-2">
              {data.models?.ensemble?.confusion_matrix && (
                <div>
                  <p className="text-xs font-bold uppercase muted">Ensemble</p>
                  <div className="mt-1">
                    <ConfusionMatrix
                      m={data.models.ensemble.confusion_matrix}
                      labels={[t('bench.tn'), t('bench.fp'), t('bench.fn'), t('bench.tp')]}
                    />
                  </div>
                </div>
              )}
              {data.models?.ensemble?.roc_curve && (
                <div>
                  <RocChart curve={data.models.ensemble.roc_curve} />
                </div>
              )}
            </div>
          </section>

          {data.models?.ensemble?.per_language && (
            <section className="card overflow-x-auto p-4">
              <h2 className="text-base font-bold">{t('bench.perLanguage')}</h2>
              <table className="mt-2 w-full min-w-[380px] text-sm">
                <thead>
                  <tr className="muted text-xs uppercase">
                    <th className="p-2 text-left">Language</th>
                    <th className="p-2 text-right">n</th>
                    <th className="p-2 text-right">{t('bench.precision')}</th>
                    <th className="p-2 text-right">{t('bench.recall')}</th>
                    <th className="p-2 text-right">{t('bench.f1')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.models.ensemble.per_language).map(([language, m]) => (
                    <tr key={language} className="border-t border-slate-200 dark:border-slate-700">
                      <td className="p-2 font-semibold uppercase">{language}</td>
                      <td className="p-2 text-right tabular-nums">{m.n}</td>
                      <td className="p-2 text-right tabular-nums">{pct(m.precision)}</td>
                      <td className="p-2 text-right tabular-nums">{pct(m.recall)}</td>
                      <td className="p-2 text-right font-bold tabular-nums">{pct(m.f1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {data.url_model && (
            <section className="card p-4">
              <h2 className="text-base font-bold">{t('bench.urlModel')}</h2>
              <p className="muted mt-1 text-xs">
                {data.url_model.chosen_model} · {data.url_model.n_features} lexical features · version {data.url_model.feature_order_version}
              </p>
              <table className="mt-2 w-full text-sm">
                <thead>
                  <tr className="muted text-xs uppercase">
                    <th className="p-2 text-left">{t('bench.model')}</th>
                    <th className="p-2 text-right">{t('bench.precision')}</th>
                    <th className="p-2 text-right">{t('bench.recall')}</th>
                    <th className="p-2 text-right">{t('bench.f1')}</th>
                    <th className="p-2 text-right">{t('bench.auc')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.url_model.models ?? {}).map(([name, m]: [string, any]) => (
                    <tr key={name} className="border-t border-slate-200 dark:border-slate-700">
                      <td className="p-2 font-semibold">{name}</td>
                      <td className="p-2 text-right tabular-nums">{pct(m.precision)}</td>
                      <td className="p-2 text-right tabular-nums">{pct(m.recall)}</td>
                      <td className="p-2 text-right font-bold tabular-nums">{pct(m.f1)}</td>
                      <td className="p-2 text-right tabular-nums">{m.roc_auc?.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted mt-2 text-xs">
                {data.url_model.dataset?.name} · {data.url_model.dataset?.license} · test n={data.url_model.dataset?.test}
              </p>
            </section>
          )}

          {data.ensemble_weights && (
            <section className="card p-4">
              <h2 className="text-base font-bold">{t('bench.weights')}</h2>
              <ul className="mt-2 space-y-1 text-sm">
                {Object.entries(data.ensemble_weights).map(([k, v]) => (
                  <li key={k} className="flex items-center justify-between">
                    <span className="font-semibold">{k}</span>
                    <span className="tabular-nums">{Math.round(v * 100)}%</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card border-amber-300 p-4">
            <h2 className="text-base font-bold">⚠️ {t('bench.limitations')}</h2>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-relaxed">
              {(data.limitations ?? []).map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}

export default Benchmark
