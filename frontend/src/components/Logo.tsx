import { memo } from 'react'

/** ScamLens wordmark. Self-contained SVG so the preview never needs a network fetch. */
export function Logo({ size = 28, withText = true }: { size?: number; withText?: boolean }) {
  return (
    <span className="flex items-center gap-2" aria-label="ScamLens">
      <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-hidden="true">
        <defs>
          <linearGradient id="sl-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#338efb" />
            <stop offset="100%" stopColor="#0f9f9a" />
          </linearGradient>
        </defs>
        <rect x="3" y="3" width="42" height="42" rx="13" fill="url(#sl-grad)" />
        <circle cx="21" cy="21" r="8.5" fill="none" stroke="#fff" strokeWidth="3.4" />
        <path d="M27.5 27.5 L36 36" stroke="#fff" strokeWidth="4.2" strokeLinecap="round" />
        <path d="M17.6 21.2 l2.6 2.7 4.8-5.2" fill="none" stroke="#fff" strokeWidth="2.6"
          strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {withText && (
        <span className="text-lg font-extrabold tracking-tight">
          Scam<span className="text-brand-600 dark:text-brand-300">Lens</span>
        </span>
      )}
    </span>
  )
}

export default memo(Logo)
