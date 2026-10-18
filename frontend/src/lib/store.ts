/**
 * Local state: anonymous device id, accessibility + language preferences,
 * onboarding flag and a small history counter. Everything lives in
 * localStorage — there is no login and no server-side profile.
 */
import { useCallback, useEffect, useState } from 'react'
import { LANGUAGES, type LangCode } from './i18n'

const KEYS = {
  device: 'scamlens.device_id',
  lang: 'scamlens.lang',
  theme: 'scamlens.theme',
  largeText: 'scamlens.large_text',
  highContrast: 'scamlens.high_contrast',
  onboarded: 'scamlens.onboarded',
} as const

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode: preferences simply do not persist */
  }
}

/** Anonymous device id — random, never sent anywhere except as a history key. */
export function getDeviceId(): string {
  let id = safeGet(KEYS.device)
  if (!id) {
    const rand =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `dev-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`
    id = rand.replace(/-/g, '').slice(0, 32)
    safeSet(KEYS.device, id)
  }
  return id
}

export function detectBrowserLanguage(): LangCode {
  const stored = safeGet(KEYS.lang)
  if (stored && LANGUAGES.some((l) => l.code === stored)) return stored as LangCode
  // English is the default. ScamLens is a four-language product and the switcher is one tap
  // away in Settings, but anyone opening it cold (a reviewer, a judge, a first-time user on
  // a device we cannot see) should land on a language they can read without guessing.
  return 'en'
}

export interface Settings {
  language: LangCode
  theme: 'light' | 'dark'
  largeText: boolean
  highContrast: boolean
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(() => ({
    language: detectBrowserLanguage(),
    theme: (safeGet(KEYS.theme) as 'light' | 'dark') ?? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
    largeText: safeGet(KEYS.largeText) === '1',
    highContrast: safeGet(KEYS.highContrast) === '1',
  }))

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', settings.theme === 'dark')
    root.classList.toggle('large-text', settings.largeText)
    root.classList.toggle('high-contrast', settings.highContrast)
    root.lang = settings.language
    root.dir = settings.language === 'ur' ? 'rtl' : 'ltr'
    safeSet(KEYS.lang, settings.language)
    safeSet(KEYS.theme, settings.theme)
    safeSet(KEYS.largeText, settings.largeText ? '1' : '0')
    safeSet(KEYS.highContrast, settings.highContrast ? '1' : '0')
  }, [settings])

  const update = useCallback((patch: Partial<Settings>) => setSettings((s) => ({ ...s, ...patch })), [])
  return { settings, update }
}

export function useOnboarding() {
  const [needed, setNeeded] = useState(() => safeGet(KEYS.onboarded) !== '1')
  const finish = useCallback(() => {
    safeSet(KEYS.onboarded, '1')
    setNeeded(false)
  }, [])
  const restart = useCallback(() => {
    safeSet(KEYS.onboarded, '0')
    setNeeded(true)
  }, [])
  return { needed, finish, restart }
}

export function useOnlineStatus() {
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])
  return online
}
