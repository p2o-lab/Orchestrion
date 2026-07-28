import { useState } from 'react'
import type { PeaDetail } from '../api/types'
import { Button, Input, Modal } from '../ui/primitives'
import type { StepNodeData } from './StepNode'

// Edit a step's procedure parameters. Recipe params are numeric (float) — controlled value
// assignment handles analog/integer channels (MTP §8.1.3), so only those are settable here.
export function StepEditor({
  pea,
  data,
  onSave,
  onClose,
}: {
  pea: PeaDetail | undefined
  data: StepNodeData
  onSave: (params: Record<string, number>) => void
  onClose: () => void
}) {
  const proc = pea?.services
    .find((s) => s.name === data.service)
    ?.procedures.find((p) => p.procedure_id === data.procedure_id)
  const numeric = (proc?.parameters ?? []).filter((p) => p.kind === 'analog' || p.kind === 'integer')

  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(
      numeric.map((p) => [p.name, data.params[p.name] !== undefined ? String(data.params[p.name]) : '']),
    ),
  )

  function save() {
    const out: Record<string, number> = {}
    for (const p of numeric) {
      const v = values[p.name]
      if (v !== '' && v !== undefined && !Number.isNaN(Number(v))) out[p.name] = Number(v)
    }
    onSave(out)
  }

  return (
    <Modal title={`${data.service} · ${data.procedure}`} onClose={onClose}>
      <div className="mb-3 text-xs uppercase tracking-wide text-faint">{data.pea}</div>
      {numeric.length === 0 ? (
        <p className="text-sm text-dim">This procedure has no settable parameters.</p>
      ) : (
        <div className="grid gap-3">
          {numeric.map((p) => (
            <div key={p.name}>
              <label className="mb-1 block text-xs font-medium text-dim">
                {p.name} <span className="text-faint">· {p.kind}</span>
              </label>
              <Input
                type="number"
                value={values[p.name] ?? ''}
                onChange={(e) => setValues((v) => ({ ...v, [p.name]: e.target.value }))}
                placeholder="leave blank for the PEA default"
              />
            </div>
          ))}
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={save}>Save</Button>
      </div>
    </Modal>
  )
}
