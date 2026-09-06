import { useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { Button, Input, Modal } from '../ui/primitives'
import { Icon } from '../ui/icons'

export function ImportDialog({
  projectId,
  onClose,
  onImported,
}: {
  projectId: number
  onClose: () => void
  onImported: () => void
}) {
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** A **successful** import that the operator still needs to see — today, a duplicate
   *  endpoint. Held in state because the dialog must NOT close on it: the import worked,
   *  so there is nothing to retry, but a message that vanishes with the dialog is a
   *  message nobody reads. The conflict outlives this dialog, which is why `ProjectView`
   *  also badges the cards. */
  const [warning, setWarning] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function pick(f: File | null) {
    setFile(f)
    setError(null)
    if (f && !name.trim()) setName(f.name.replace(/\.aml$/i, ''))
  }

  async function submit() {
    if (!file || !name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const imported = await api.importPea(projectId, name.trim(), file)
      onImported()
      if (imported.warning) {
        setWarning(imported.warning)
        return // the PEA is stored; hold the dialog open so the warning is actually seen
      }
      onClose()
    } catch (e) {
      // The parser's clause-level message (HTTP 422) — shown inline, highlighted.
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Import a PEA" onClose={onClose}>
      <label className="mb-1.5 block text-xs font-medium text-dim">Name</label>
      <Input
        placeholder="e.g. Stirrer HC30"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <label className="mb-1.5 mt-4 block text-xs font-medium text-dim">MTP file (.aml)</label>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="flex w-full items-center gap-3 rounded-xl border border-dashed border-edge-strong
                   bg-elev px-4 py-4 text-left transition hover:border-accent/50 hover:bg-white/5"
      >
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent/12 text-accent">
          <Icon name="upload" size={20} />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm text-ink">
            {file ? file.name : 'Choose an .aml file'}
          </span>
          <span className="block text-xs text-faint">
            {file ? `${(file.size / 1024).toFixed(0)} kB` : 'CAEX 3.0 / manifest 1.1.0'}
          </span>
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".aml,application/xml,text/xml"
        className="hidden"
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />

      {error && (
        <div className="mt-4 rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-danger">
            Invalid MTP
          </div>
          <div className="mt-1 font-mono text-xs leading-relaxed text-ink/90">{error}</div>
        </div>
      )}

      {warning && (
        <div className="mt-4 rounded-lg border border-warn/40 bg-warn/10 px-3.5 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-warn">
            Imported — with a conflict
          </div>
          <div className="mt-1 text-xs leading-relaxed text-ink/90">{warning}</div>
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        {warning ? (
          // The import succeeded, so there is nothing to cancel and nothing to retry —
          // one button that acknowledges and closes.
          <Button variant="primary" onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" onClick={submit} disabled={busy || !file || !name.trim()}>
              {busy ? 'Validating…' : 'Import'}
            </Button>
          </>
        )}
      </div>
    </Modal>
  )
}
