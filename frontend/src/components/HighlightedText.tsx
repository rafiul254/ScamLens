import { useMemo } from 'react'
import type { Evidence, RedFlag } from '../lib/types'

interface Span {
  start: number
  end: number
  severity: number
  reason: string
  source: 'red_flag' | 'ml_token'
}

/**
 * Shows the user's own message with the suspicious parts highlighted.
 * Intensity = the severity returned by the API (pattern-library weight or the
 * classifier's token contribution), so the colour is information, not decoration.
 */
export function HighlightedText({
  text,
  redFlags,
  evidence,
}: {
  text: string
  redFlags: RedFlag[]
  evidence?: Evidence
}) {
  const spans = useMemo<Span[]>(() => {
    const found: Span[] = []
    const lowered = text.toLowerCase()
    for (const flag of redFlags ?? []) {
      const needle = (flag.text_span ?? '').trim()
      if (!needle) continue
      let index = lowered.indexOf(needle.toLowerCase())
      if (index === -1 && needle.length > 6) {
        // tolerate the API quoting a slightly different substring
        const firstWords = needle.split(/\s+/).slice(0, 3).join(' ')
        index = lowered.indexOf(firstWords.toLowerCase())
        if (index === -1) continue
        found.push({
          start: index,
          end: index + firstWords.length,
          severity: flag.severity ?? 0.6,
          reason: flag.reason,
          source: 'red_flag',
        })
        continue
      }
      if (index === -1) continue
      found.push({ start: index, end: index + needle.length, severity: flag.severity ?? 0.6, reason: flag.reason, source: 'red_flag' })
    }
    for (const token of evidence?.top_tokens ?? []) {
      if (typeof token.start !== 'number' || typeof token.end !== 'number') continue
      if (token.end <= token.start) continue
      found.push({
        start: token.start,
        end: token.end,
        severity: Math.min(0.85, 0.25 + (token.contribution ?? 0.3) * 0.6),
        reason: `The classifier weighted this word ${(token.contribution ?? 0).toFixed(2)}`,
        source: 'ml_token',
      })
    }
    // keep the strongest span when two overlap
    found.sort((a, b) => a.start - b.start || b.severity - a.severity)
    const merged: Span[] = []
    for (const span of found) {
      const last = merged[merged.length - 1]
      if (last && span.start < last.end) {
        if (span.severity > last.severity) merged[merged.length - 1] = span
        continue
      }
      merged.push(span)
    }
    return merged
  }, [text, redFlags, evidence])

  if (!spans.length) {
    return <p className="whitespace-pre-wrap break-words text-[1.05rem] leading-relaxed">{text}</p>
  }

  const nodes: React.ReactNode[] = []
  let cursor = 0
  spans.forEach((span, i) => {
    if (span.start > cursor) nodes.push(<span key={`t${i}`}>{text.slice(cursor, span.start)}</span>)
    const color = span.severity >= 0.66 ? 'var(--color-danger)' : span.severity >= 0.4 ? 'var(--color-warn)' : '#0ea5e9'
    nodes.push(
      <mark
        key={`m${i}`}
        className="flag"
        style={{ ['--flag-color' as any]: color, ['--flag-strength' as any]: span.severity.toFixed(2) }}
        title={span.reason}
      >
        {text.slice(span.start, span.end)}
      </mark>,
    )
    cursor = span.end
  })
  if (cursor < text.length) nodes.push(<span key="tail">{text.slice(cursor)}</span>)

  return (
    <p className="whitespace-pre-wrap break-words text-[1.05rem] leading-relaxed">
      {nodes}
      <span className="sr-only">
        {' '}
        Highlighted text is suspicious and is explained in the list below.
      </span>
    </p>
  )
}

export default HighlightedText
