// The Orchestrion mark — a stylised orchestrion facade (arched cabinet + organ
// pipes). Inlined and monochrome via currentColor, so it takes the colour of
// whatever text context it sits in (we render it in the brand accent).

export function Logo({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 512 512"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label="Orchestrion"
      fill="currentColor"
    >
      {/* Cabinet: arched pediment + side walls */}
      <path
        d="M 84 440 L 84 244 A 172 172 0 0 1 428 244 L 428 440"
        fill="none"
        stroke="currentColor"
        strokeWidth={20}
        strokeLinecap="round"
      />
      {/* Slender framing columns */}
      <rect x="110" y="248" width="14" height="168" rx="7" />
      <rect x="388" y="248" width="14" height="168" rx="7" />
      {/* Medallion window in the arch */}
      <circle cx="256" cy="168" r="26" fill="none" stroke="currentColor" strokeWidth={13} />
      <circle cx="256" cy="168" r="7" />
      {/* Organ pipes / level bars (symmetric fan, tallest at centre) */}
      <rect x="136" y="312" width="24" height="100" rx="12" />
      <rect x="172" y="276" width="24" height="136" rx="12" />
      <rect x="208" y="244" width="24" height="168" rx="12" />
      <rect x="244" y="220" width="24" height="192" rx="12" />
      <rect x="280" y="244" width="24" height="168" rx="12" />
      <rect x="316" y="276" width="24" height="136" rx="12" />
      <rect x="352" y="312" width="24" height="100" rx="12" />
      {/* Plinth */}
      <rect x="58" y="436" width="396" height="26" rx="13" />
    </svg>
  )
}
