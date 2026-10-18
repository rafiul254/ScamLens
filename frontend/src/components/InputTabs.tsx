import { useEffect, useRef, useState } from 'react'
import { LANGUAGES, translate, type LangCode } from '../lib/i18n'
import { redactPii } from '../lib/pii'
import { speechInputSupported, startListening, type VoiceHandle } from '../lib/speech'
import type { InputKind } from '../lib/types'

export type TabId = 'paste' | 'screenshot' | 'voice' | 'link'

const TAB_ORDER: TabId[] = ['paste', 'screenshot', 'voice', 'link']
const TAB_LABEL: Record<TabId, string> = {
  paste: 'home.tab.paste',
  screenshot: 'home.tab.screenshot',
  voice: 'home.tab.voice',
  link: 'home.tab.link',
}

export interface SubmissionPayload {
  kind: InputKind
  text: string
  file?: File
}

export function InputTabs({
  lang,
  busy,
  onSubmit,
  initialText = '',
  maxChars = 6000,
}: {
  lang: LangCode
  busy: boolean
  onSubmit: (payload: SubmissionPayload) => void
  initialText?: string
  maxChars?: number
}) {
  const [tab, setTab] = useState<TabId>('paste')
  const [text, setText] = useState(initialText)
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [listening, setListening] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const handleRef = useRef<VoiceHandle | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setText(initialText)
  }, [initialText])

  const t = (key: string, vars?: Record<string, string | number>) => translate(lang, key, vars)
  const redaction = redactPii(text)
  const piiCount = tab === 'link' ? 0 : redaction.entities.length

  useEffect(() => () => handleRef.current?.stop(), [])

  const submit = () => {
    if (busy) return
    if (tab === 'screenshot') {
      if (file) onSubmit({ kind: 'image', text, file })
      return
    }
    const value = text.trim()
    if (!value) return
    onSubmit({ kind: tab === 'link' ? 'url' : tab === 'voice' ? 'audio_transcript' : 'text', text: value })
  }

  const toggleVoice = () => {
    if (listening) {
      handleRef.current?.stop()
      setListening(false)
      return
    }
    setVoiceError(null)
    const locale = LANGUAGES.find((l) => l.code === lang)?.speech ?? 'en-IN'
    handleRef.current = startListening(
      locale,
      (transcript, isFinal) => setText((prev) => (isFinal ? `${prev}${prev ? ' ' : ''}${transcript}` : prev)),
      (message) => {
        setListening(false)
        setVoiceError(message === 'unsupported' ? t('voice.unsupported') : message)
      },
    )
    if (handleRef.current) setListening(true)
  }

  const acceptFile = (candidate: File | null | undefined) => {
    setFileError(null)
    if (!candidate) return
    if (!/^image\/(png|jpe?g|webp|gif)$/.test(candidate.type)) {
      setFileError(t('drop.note'))
      return
    }
    if (candidate.size > 5 * 1024 * 1024) {
      setFileError(t('drop.note'))
      return
    }
    setFile(candidate)
  }

  const canSubmit = !busy && (tab === 'screenshot' ? Boolean(file) : text.trim().length > 0)

  return (
    <div className="card p-3 sm:p-4">
      {/* Tabs */}
      <div role="tablist" aria-label={t('home.subtitle')} className="flex gap-1.5 pb-1">
        {TAB_ORDER.map((id) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => {
              setTab(id)
              setFileError(null)
              if (id === 'link') setText('')
            }}
            className={`min-w-0 flex-1 rounded-xl px-1.5 py-2 text-[0.72rem] font-semibold leading-tight transition ${
              tab === id
                ? 'bg-brand-600 text-white shadow-sm'
                : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            {t(TAB_LABEL[id])}
          </button>
        ))}
      </div>

      <div className="mt-3">
        {tab === 'paste' && (
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, maxChars))}
            onPaste={(e) => {
              const pasted = e.clipboardData.getData('text')
              if (pasted && pasted.length > 40) {
                e.preventDefault()
                setText(pasted.slice(0, maxChars))
              }
            }}
            rows={6}
            placeholder={t('home.placeholder')}
            aria-label={t('home.tab.paste')}
            className="w-full resize-y rounded-xl border border-slate-200 bg-white p-3 text-base leading-relaxed outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900"
          />
        )}

        {tab === 'link' && (
          <input
            type="url"
            inputMode="url"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 2048))}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            placeholder={t('home.linkPlaceholder')}
            aria-label={t('home.tab.link')}
            className="w-full rounded-xl border border-slate-200 bg-white p-3 text-base outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900"
          />
        )}

        {tab === 'screenshot' && (
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              acceptFile(e.dataTransfer.files?.[0])
            }}
            className={`rounded-xl border-2 border-dashed p-6 text-center transition ${
              dragging ? 'border-brand-500 bg-brand-50 dark:bg-brand-900/20' : 'border-slate-300 dark:border-slate-600'
            }`}
          >
            <p className="font-semibold">{t('drop.prompt')}</p>
            <p className="muted mt-1 text-sm">
              {t('drop.or')}{' '}
              <label className="cursor-pointer font-semibold text-brand-700 underline dark:text-brand-300">
                {t('drop.browse')}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  className="sr-only"
                  onChange={(e) => acceptFile(e.target.files?.[0])}
                />
              </label>
            </p>
            {file && <p className="mt-2 text-sm font-semibold text-safe">{file.name}</p>}
            <p className="muted mt-2 text-xs">{t('drop.note')}</p>
            {fileError && <p className="mt-2 text-sm text-danger">{fileError}</p>}
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, maxChars))}
              rows={2}
              placeholder={t('voice.transcript')}
              aria-label="optional note"
              className="mt-3 w-full rounded-xl border border-slate-200 bg-white p-3 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900"
            />
          </div>
        )}

        {tab === 'voice' && (
          <div className="text-center">
            {speechInputSupported() ? (
              <>
                <button
                  type="button"
                  onClick={toggleVoice}
                  aria-pressed={listening}
                  className={`inline-flex items-center gap-3 rounded-full px-6 py-4 text-base font-bold text-white transition ${
                    listening ? 'bg-danger animate-pulse-soft' : 'bg-brand-600 hover:bg-brand-700'
                  }`}
                >
                  <span aria-hidden="true">{listening ? '■' : '🎤'}</span>
                  {listening ? t('voice.stop') : t('voice.start')}
                </button>
                {listening && <p className="mt-2 text-sm font-semibold text-danger">{t('voice.listening')}</p>}
              </>
            ) : (
              <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-100">
                {t('voice.unsupported')}
              </p>
            )}
            {voiceError && <p className="mt-2 text-sm text-danger">{voiceError}</p>}
            <label className="muted mt-4 block text-left text-sm font-semibold">{t('voice.transcript')}</label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, maxChars))}
              rows={4}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white p-3 text-base outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900"
            />
          </div>
        )}
      </div>

      {/* PII badge */}
      {piiCount > 0 && (
        <p
          className="mt-3 flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900 dark:bg-emerald-900/25 dark:text-emerald-100"
          role="status"
        >
          <span aria-hidden="true">🛡️</span>
          {t('home.piiDetected', { n: piiCount })} — {redaction.entities.map((e) => e.placeholder).join(' ')}
        </p>
      )}

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="flex-1 rounded-xl bg-brand-600 px-4 py-3 text-base font-bold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? t('home.analyzing') : t('home.analyze')}
        </button>
        {text && (
          <button
            type="button"
            onClick={() => {
              setText('')
              setFile(null)
            }}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm font-semibold dark:border-slate-600"
          >
            {t('home.clear')}
          </button>
        )}
      </div>
      <p className="muted mt-2 text-xs">{t('home.piiProtected')}</p>
    </div>
  )
}

export default InputTabs
