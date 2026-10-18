/**
 * Voice: speech-to-text in (Web Speech API) and read-aloud out (SpeechSynthesis).
 * Both degrade gracefully: if a browser lacks support the UI explains it instead
 * of failing silently.
 */

type RecognitionCtor = new () => any

function getRecognitionCtor(): RecognitionCtor | null {
  const w = window as any
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export const speechInputSupported = (): boolean => getRecognitionCtor() !== null
export const speechOutputSupported = (): boolean => typeof window !== 'undefined' && 'speechSynthesis' in window

export interface VoiceHandle {
  stop: () => void
}

export function startListening(
  locale: string,
  onResult: (transcript: string, isFinal: boolean) => void,
  onError: (message: string) => void,
): VoiceHandle | null {
  const Ctor = getRecognitionCtor()
  if (!Ctor) {
    onError('unsupported')
    return null
  }
  const recognition = new Ctor()
  recognition.lang = locale
  recognition.continuous = true
  recognition.interimResults = true
  recognition.maxAlternatives = 1

  recognition.onresult = (event: any) => {
    let interim = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i]
      if (result.isFinal) onResult(result[0].transcript, true)
      else interim += result[0].transcript
    }
    if (interim) onResult(interim, false)
  }
  recognition.onerror = (event: any) => {
    const map: Record<string, string> = {
      'not-allowed': 'Microphone permission was blocked.',
      'service-not-allowed': 'Speech service is not allowed in this browser.',
      'no-speech': 'We did not hear anything. Please try again.',
      network: 'Speech recognition needs a network connection.',
    }
    onError(map[event.error] ?? 'Voice input failed.')
  }
  try {
    recognition.start()
  } catch {
    onError('Voice input could not start.')
    return null
  }
  return { stop: () => recognition.stop() }
}

/** Read text aloud in the detected language, picking the closest available voice. */
export function speak(text: string, locale: string, onEnd?: () => void): boolean {
  if (!speechOutputSupported()) return false
  const synth = window.speechSynthesis
  synth.cancel()
  const clean = text.replace(/[*_#`>|]/g, '').replace(/\s+/g, ' ').trim()
  if (!clean) return false
  const utterance = new SpeechSynthesisUtterance(clean.slice(0, 1200))
  utterance.lang = locale
  utterance.rate = 0.95
  utterance.pitch = 1
  const voices = synth.getVoices()
  const exact = voices.find((v) => v.lang.toLowerCase() === locale.toLowerCase())
  const prefix = voices.find((v) => v.lang.toLowerCase().startsWith(locale.split('-')[0].toLowerCase()))
  if (exact ?? prefix) utterance.voice = (exact ?? prefix) as SpeechSynthesisVoice
  if (onEnd) utterance.onend = () => onEnd()
  synth.speak(utterance)
  return true
}

export function stopSpeaking(): void {
  if (speechOutputSupported()) window.speechSynthesis.cancel()
}

export function isSpeaking(): boolean {
  return speechOutputSupported() && window.speechSynthesis.speaking
}
