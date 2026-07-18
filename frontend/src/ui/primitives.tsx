// Small styled building blocks — utility classes wrapped as React components so
// the views stay clean and there is no hand-written CSS.

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium ' +
  'cursor-pointer transition disabled:opacity-40 disabled:cursor-not-allowed select-none'

const VARIANT: Record<Variant, string> = {
  primary:
    'border border-transparent font-semibold text-canvas bg-gradient-to-b from-accent-bright ' +
    'to-accent shadow-[0_4px_18px_rgba(124,156,255,0.25)] hover:brightness-110',
  secondary: 'border border-edge-strong bg-panel-2 text-ink hover:bg-hover hover:border-accent/40',
  ghost: 'border border-edge bg-transparent text-dim hover:text-ink hover:bg-white/5',
  danger: 'border border-edge-strong bg-panel-2 text-ink hover:border-danger hover:text-danger',
}

export function Button({
  variant = 'secondary',
  small,
  className = '',
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean }) {
  return (
    <button
      className={`${BASE} ${VARIANT[variant]} ${small ? 'px-3 py-1.5 text-xs' : ''} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Input({ className = '', ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={
        'w-full rounded-lg border border-edge-strong bg-elev px-3.5 py-2.5 text-sm text-ink ' +
        'outline-none transition placeholder:text-faint focus:border-accent ' +
        `focus:ring-2 focus:ring-accent/20 ${className}`
      }
      {...rest}
    />
  )
}

export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={`rounded-[14px] border border-edge shadow-[0_8px_30px_rgba(0,0,0,0.35)] ${className}`}
      style={{ background: 'linear-gradient(180deg, var(--color-panel), var(--color-elev))' }}
    >
      {children}
    </div>
  )
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-edge-strong ` +
        `border-t-accent ${className}`}
    />
  )
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <Card className="p-6 animate-fade-in">
          <h2 className="text-lg text-ink">{title}</h2>
          <div className="mt-4">{children}</div>
        </Card>
      </div>
    </div>
  )
}
