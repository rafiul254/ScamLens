import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { MicroLesson, PatternCard, ScamIQ } from '../lib/types'

/** 60-second lesson + 3-question quiz, opened from the Learn tab. */
export function LessonPanel({
  pattern,
  lang,
  deviceId,
  onClose,
  onIqUpdate,
  onTryCheck,
}: {
  pattern: PatternCard
  lang: LangCode
  deviceId: string
  onClose: () => void
  onIqUpdate: (iq: ScamIQ) => void
  onTryCheck: () => void
}) {
  const [lesson, setLesson] = useState<MicroLesson | null>(null)
  const [loading, setLoading] = useState(true)
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [result, setResult] = useState<{ correct: number; total: number; gain: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLesson(null)
    setAnswers({})
    setResult(null)
    api
      .lesson(pattern.id, lang)
      .then((data) => {
        if (!cancelled) setLesson(data)
      })
      .catch(() => {
        if (!cancelled) setError(t('common.error'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pattern.id, lang])

  const submit = async () => {
    if (!lesson) return
    const correct = lesson.quiz.filter((q, i) => answers[i] === q.answer_index).length
    setResult({ correct, total: lesson.quiz.length, gain: 0 })
    try {
      const iq = await api.submitQuiz(deviceId, pattern.id, correct, lesson.quiz.length)
      onIqUpdate(iq)
      setResult({ correct, total: lesson.quiz.length, gain: iq.score_gain ?? 0 })
    } catch {
      /* progress simply does not persist if the API is unreachable */
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={pattern.name[lang] ?? pattern.name.en}
    >
      <div className="max-h-[92dvh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-4 shadow-xl sm:rounded-2xl dark:bg-slate-900">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-extrabold leading-tight">{pattern.name[lang] ?? pattern.name.en}</h2>
            <p className="muted mt-0.5 text-xs">
              {t('learn.severity')}: {Math.round(pattern.severity * 100)}% · {pattern.category.replace(/_/g, ' ')}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-sm font-bold" aria-label={t('common.close')}>
            ✕
          </button>
        </div>

        <p className="mt-2 text-sm leading-relaxed">{pattern.summary[lang] ?? pattern.summary.en}</p>

        {pattern.red_flag_hints.length > 0 && (
          <>
            <p className="mt-3 text-sm font-bold">{t('learn.takeaways')}</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
              {pattern.red_flag_hints.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </>
        )}

        <p className="mt-3 rounded-xl bg-emerald-50 p-3 text-sm dark:bg-emerald-900/25">
          <strong>{lang === 'bn' ? 'নিরাপদ উত্তর' : lang === 'hi' ? 'सुरक्षित जवाब' : lang === 'ur' ? 'محفوظ جواب' : 'Safe response'}:</strong>{' '}
          {pattern.safe_response}
        </p>

        {loading && (
          <div className="mt-4 space-y-2" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-4 animate-pulse rounded bg-slate-200 dark:bg-slate-700" style={{ width: `${90 - i * 12}%` }} />
            ))}
            <p className="muted text-xs">{t('learn.lessonLoading')}</p>
          </div>
        )}

        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        {lesson && !loading && (
          <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
            <p className="text-sm font-bold">{lesson.title}</p>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{lesson.body}</p>

            {lesson.quiz.length > 0 && (
              <div className="mt-3">
                <p className="text-sm font-bold">{t('learn.quiz')}</p>
                {lesson.quiz.map((q, qi) => (
                  <fieldset key={qi} className="mt-2">
                    <legend className="text-sm font-semibold">{`${qi + 1}. ${q.question}`}</legend>
                    <div className="mt-1 space-y-1">
                      {q.options.map((opt, oi) => {
                        const chosen = answers[qi] === oi
                        const revealed = result !== null
                        const isRight = revealed && oi === q.answer_index
                        const isWrong = revealed && chosen && oi !== q.answer_index
                        return (
                          <label
                            key={oi}
                            className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${
                              isRight
                                ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-900/30'
                                : isWrong
                                  ? 'border-red-400 bg-red-50 dark:bg-red-900/30'
                                  : 'border-slate-200 dark:border-slate-700'
                            }`}
                          >
                            <input
                              type="radio"
                              name={`lesson-${pattern.id}-${qi}`}
                              checked={chosen ?? false}
                              onChange={() => setAnswers((a) => ({ ...a, [qi]: oi }))}
                            />
                            <span>{opt}</span>
                          </label>
                        )
                      })}
                    </div>
                    {result && q.explanation && <p className="muted mt-1 text-xs">{q.explanation}</p>}
                  </fieldset>
                ))}
                {result === null ? (
                  <button
                    type="button"
                    onClick={submit}
                    disabled={Object.keys(answers).length !== lesson.quiz.length}
                    className="mt-3 rounded-xl bg-brand-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
                  >
                    {t('learn.submit')}
                  </button>
                ) : (
                  <div className="mt-3 rounded-xl bg-brand-50 p-3 dark:bg-brand-900/25">
                    <p className="font-bold">
                      {t('learn.result', { correct: result.correct, total: result.total })}
                      {result.gain > 0 && ` · +${result.gain} Scam IQ`}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <button type="button" onClick={onClose} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-bold text-white">
                        {t('common.close')}
                      </button>
                      <button type="button" onClick={onTryCheck} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold dark:border-slate-600">
                        {t('home.analyze')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default LessonPanel
