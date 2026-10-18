import { useEffect, useState } from 'react'
import type { Verdict } from '../lib/types'

const COLORS: Record<Verdict, string> = {
  SAFE: '#16a34a',
  SUSPICIOUS: '#d97706',
  SCAM: '#dc2626',
}

/**
 * Animated risk gauge. The arc fills to the real risk score returned by the API
 * (never a decorative number) and the colour is the semantic verdict colour.
 */
export function RiskGauge({
  score,
  verdict,
  label,
  size = 168,
}: {
  score: number
  verdict: Verdict
  label: string
  size?: number
}) {
  const [shown, setShown] = useState(0)
  const radius = size / 2 - 14
  const circumference = Math.PI * radius // half circle
  const target = circumference - (Math.min(100, Math.max(0, score)) / 100) * circumference

  useEffect(() => {
    const t = window.setTimeout(() => setShown(score), 60)
    return () => window.clearTimeout(t)
  }, [score])

  // Count-up so the number animates with the arc.
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    let frame = 0
    const total = 34
    const id = window.setInterval(() => {
      frame += 1
      const p = 1 - Math.pow(1 - frame / total, 3)
      setDisplay(Math.round(shown * p))
      if (frame >= total) window.clearInterval(id)
    }, 18)
    return () => window.clearInterval(id)
  }, [shown])

  const color = COLORS[verdict]

  return (
    <div
      className="flex flex-col items-center"
      role="meter"
      aria-valuenow={score}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <svg width={size} height={size * 0.62} viewBox={`0 0 ${size} ${size * 0.62}`}>
        <path
          d={`M 14 ${size * 0.55} A ${radius} ${radius} 0 0 1 ${size - 14} ${size * 0.55}`}
          fill="none"
          stroke="currentColor"
          className="text-slate-200 dark:text-slate-700"
          strokeWidth="13"
          strokeLinecap="round"
        />
        <path
          d={`M 14 ${size * 0.55} A ${radius} ${radius} 0 0 1 ${size - 14} ${size * 0.55}`}
          fill="none"
          stroke={color}
          strokeWidth="13"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={target}
          style={
            {
              transition: 'stroke-dashoffset 1.1s cubic-bezier(0.22,1,0.36,1)',
            } as React.CSSProperties
          }
        />
        <text x={size / 2} y={size * 0.46} textAnchor="middle" className="fill-current"
          style={{ fontSize: size * 0.26, fontWeight: 800 }}>
          {display}
        </text>
        <text x={size / 2} y={size * 0.58} textAnchor="middle" className="fill-current opacity-60"
          style={{ fontSize: size * 0.085 }}>
          {label} · 100
        </text>
      </svg>
    </div>
  )
}

export default RiskGauge
