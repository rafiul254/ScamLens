import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { translate, type LangCode } from '../lib/i18n'
import type { HealthInfo } from '../lib/types'

/** "How ScamLens uses AI" — required by the hackathon's AI-usage policy. */
export function About({ lang }: { lang: LangCode }) {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const t = (k: string) => translate(lang, k)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="space-y-4 pb-6">
      <header className="pt-2">
        <h1 className="text-2xl font-extrabold">{t('about.title')}</h1>
        <p className="muted mt-1 text-sm">{t('about.subtitle')}</p>
      </header>

      <section className="card p-4 text-sm leading-relaxed">
        <h2 className="text-base font-bold">The problem</h2>
        <p className="mt-1">
          Mobile-money fraud, fake KYC messages and “digital arrest” calls target people who are new to smartphones —
          often elderly parents in Bangladesh, India and Pakistan. Existing anti-spam tools give a label the reader
          cannot understand or act on, and they never teach the pattern, so the same family gets tricked again.
        </p>
      </section>

      <section className="card p-4 text-sm leading-relaxed">
        <h2 className="text-base font-bold">The agent (8 tools, max 6 steps)</h2>
        <ol className="mt-2 list-decimal space-y-1.5 pl-5">
          <li><strong>extract_content</strong> — Gemini vision reads a screenshot; voice notes arrive as on-device transcripts.</li>
          <li><strong>classify_text</strong> — the local ML classifier returns a calibrated scam probability and the words that drove it.</li>
          <li><strong>analyze_url</strong> — 32 lexical link features + safe HEAD-only redirect inspection (never renders the page).</li>
          <li><strong>match_pattern</strong> — 22 curated scam playbooks with red flags, psychology used, and the safe response.</li>
          <li><strong>detect_pii</strong> — phone numbers, OTPs, cards, accounts and NIDs, redacted in the browser <em>and</em> on the server.</li>
          <li><strong>draft_report</strong> — a ready-to-send complaint for the bank, MFS provider or cyber cell.</li>
          <li><strong>generate_family_alert</strong> — a short warning to forward to elderly relatives on WhatsApp.</li>
          <li><strong>create_micro_lesson</strong> — a 60-second lesson with a 3-question quiz in the user's language.</li>
        </ol>
        <p className="mt-2">
          The final risk score is a calibrated weighted mix of the ML score, the link score and the pattern score, with a
          published weight for the model's own judgement — so a single clever prompt cannot flip a verdict. Weights and
          thresholds are tuned on a validation split and shown on the Benchmark tab.
        </p>
        <p className="mt-2">
          Before the verdict is final, an <strong>actionability check</strong> asks the question a scam cannot avoid: does
          this message request money, a code, a click, an install or a callback? If it requests nothing and contains no
          link or contact number, the risk is capped — which is why a normal family message that happens to mention a
          hospital is not reported as fraud.
        </p>
      </section>

      <section className="card p-4 text-sm leading-relaxed">
        <h2 className="text-base font-bold">Privacy and ethics</h2>
        <ul className="mt-2 list-disc space-y-1.5 pl-5">
          <li>No login, no email, no analytics. An anonymous device id keys your local history.</li>
          <li>For typed text, PII is masked in the browser and again on the server before Gemini receives it. Screenshot images are sent to Gemini for OCR as uploaded and may still show personal details—crop or blur them first.</li>
          <li>“Delete all my data” removes every row this device created from ScamLens storage.</li>
          <li>This project uses the Gemini API free tier when configured. Google may use free-tier prompts and uploaded content to improve its products under its current terms; do not submit confidential or highly sensitive content. <a className="font-semibold underline" href="https://ai.google.dev/gemini-api/docs/pricing" target="_blank" rel="noreferrer">Review current Gemini data-use terms.</a></li>
          <li>We never click, fetch or render the links you submit — only an optional HEAD probe with a 3-second timeout.</li>
          <li>ScamLens never moves money or acts on your behalf. It explains, and it hands you the next step.</li>
        </ul>
      </section>

      <section className="card p-4 text-sm leading-relaxed">
        <h2 className="text-base font-bold">Honest limitations</h2>
        <ul className="mt-2 list-disc space-y-1.5 pl-5">
          <li>The classifier can miss novel wording, images and voice-only attacks. A low score is not a guarantee of safety.</li>
          <li>Bangla, Hindi and Urdu training data is far smaller than English, so those scores are weaker (per-language numbers are published).</li>
          <li>Reading screenshots needs the vision model; without an API key the app says so instead of guessing.</li>
          <li>ScamLens flags fraud, not marketing — an aggressive but legal promotion can still look suspicious.</li>
        </ul>
      </section>

      {health && (
        <section className="card p-4 text-xs muted">
          <h2 className="text-sm font-bold text-inherit">This deployment</h2>
          <ul className="mt-1 space-y-0.5">
            <li>version: {health.version}</li>
            <li>Gemini agent: {health.llm_enabled ? `${health.llm_model} (max ${health.agent_max_steps} steps)` : 'not configured — running the deterministic local agent'}</li>
            <li>text classifier: {String((health.text_model as any)?.available ? `${(health.text_model as any).backend} · ${(health.text_model as any).version}` : 'rules only')}</li>
            <li>link model: {health.url_model}{health.url_probe_enabled ? ' · HEAD probe on' : ''}</li>
            <li>rate limit: {health.limits?.rate_limit_per_minute}/min · max text {health.limits?.max_text_chars} chars</li>
          </ul>
        </section>
      )}
    </div>
  )
}

export default About
