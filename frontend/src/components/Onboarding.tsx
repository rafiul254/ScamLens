import { useState } from 'react'
import { Logo } from './Logo'
import { translate, type LangCode } from '../lib/i18n'

/**
 * Three-screen onboarding. Deliberately short and always skippable — the target
 * user is on a phone, possibly for the first time.
 */
export function Onboarding({ lang, onDone }: { lang: LangCode; onDone: () => void }) {
  const [step, setStep] = useState(1)
  const t = (k: string) => translate(lang, k)
  const screens = [1, 2, 3] as const

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-white p-5 dark:bg-slate-900" role="dialog" aria-modal="true">
      <div className="flex items-center justify-between">
        <Logo />
        <button type="button" onClick={onDone} className="text-sm font-semibold muted">
          {t('onboard.skip')}
        </button>
      </div>

      <div className="flex flex-1 flex-col justify-center">
        <div key={step} style={{ animation: 'rise .4s cubic-bezier(.22,1,.36,1) both' }}>
          <div className="mb-5 flex justify-center">
            <OnboardArt step={step} />
          </div>
          <h2 className="text-2xl font-extrabold leading-tight">{t(`onboard.${step}.title`)}</h2>
          <p className="mt-3 text-base leading-relaxed muted">{t(`onboard.${step}.body`)}</p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-1.5" aria-hidden="true">
          {screens.map((s) => (
            <span
              key={s}
              className={`h-2 rounded-full transition-all ${s === step ? 'w-6 bg-brand-600' : 'w-2 bg-slate-300 dark:bg-slate-600'}`}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={() => (step === 3 ? onDone() : setStep((s) => ((s + 1) as 1 | 2 | 3)))}
          className="rounded-xl bg-brand-600 px-5 py-3 text-base font-bold text-white"
        >
          {step === 3 ? t('onboard.start') : t('onboard.next')}
        </button>
      </div>
    </div>
  )
}

function OnboardArt({ step }: { step: number }) {
  const common = 'size-40'
  if (step === 1) {
    return (
      <svg viewBox="0 0 160 160" className={common} role="img" aria-hidden="true">
        <rect x="40" y="18" width="80" height="124" rx="14" fill="#e2eef4" />
        <rect x="48" y="34" width="64" height="10" rx="4" fill="#b9d6e3" />
        <rect x="48" y="52" width="64" height="10" rx="4" fill="#b9d6e3" />
        <rect x="48" y="70" width="44" height="10" rx="4" fill="#b9d6e3" />
        <circle cx="80" cy="120" r="6" fill="#b9d6e3" />
        <circle cx="118" cy="46" r="20" fill="#dc2626" />
        <text x="118" y="53" textAnchor="middle" fontSize="22" fill="#fff" fontWeight="800">
          !
        </text>
      </svg>
    )
  }
  if (step === 2) {
    return (
      <svg viewBox="0 0 160 160" className={common} role="img" aria-hidden="true">
        <circle cx="72" cy="72" r="34" fill="none" stroke="#1e6ff0" strokeWidth="9" />
        <path d="M97 97 L124 124" stroke="#1e6ff0" strokeWidth="11" strokeLinecap="round" />
        <path d="M58 72 l10 11 20-22" fill="none" stroke="#16a34a" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 160 160" className={common} role="img" aria-hidden="true">
      <path d="M80 26c-16 0-28 11-28 26 0 20-8 26-14 32h84c-6-6-14-12-14-32 0-15-12-26-28-26z" fill="#0f9f9a" />
      <circle cx="118" cy="58" r="17" fill="#16a34a" />
      <path d="M110 58 l6 7 12-13" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="56" y="92" width="48" height="30" rx="8" fill="#e2eef4" />
      <path d="M64 104h32M64 112h20" stroke="#8fb7c7" strokeWidth="4" strokeLinecap="round" />
    </svg>
  )
}

export default Onboarding
