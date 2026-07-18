import { useState } from 'react'
import { Button, Modal } from './primitives'
import { Icon } from './icons'

export function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Delete',
  onConfirm,
  onClose,
}: {
  title: string
  message: string
  confirmLabel?: string
  onConfirm: () => Promise<void> | void
  onClose: () => void
}) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal title="" onClose={onClose}>
      <div className="-mt-2 flex flex-col items-center text-center">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-danger/12 text-danger">
          <Icon name="trash" size={22} />
        </span>
        <h2 className="mt-4 text-lg font-semibold text-ink">{title}</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-dim">{message}</p>
        <div className="mt-6 flex w-full gap-2">
          <Button variant="ghost" className="flex-1" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="danger"
            className="flex-1"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onConfirm()
              } finally {
                setBusy(false)
              }
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
