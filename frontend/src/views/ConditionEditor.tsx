import { useState } from 'react'
import type { Condition, PeaDetail } from '../api/types'
import { Button, Modal } from '../ui/primitives'

// The 7 stable [2658-4 Table 14] states worth waiting on (transient "-ing" states are fleeting).
const STABLE_STATES = ['IDLE', 'EXECUTE', 'COMPLETED', 'PAUSED', 'HELD', 'STOPPED', 'ABORTED']
const OPS = ['<', '<=', '>', '>=', '==', '!='] as const
type CondType = 'StateReached' | 'ValueThreshold' | 'Elapsed'

const sel =
  'w-full rounded-lg border border-edge-strong bg-elev px-3 py-2 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20'

// Every value TagName a PEA publishes (mirrors the backend's _value_names).
function valueNames(pea: PeaDetail): string[] {
  const names = new Set<string>()
  pea.process_values.forEach((v) => names.add(v.name))
  pea.services.forEach((s) => {
    s.config_parameters.forEach((v) => names.add(v.name))
    s.procedures.forEach((p) => {
      p.report_values.forEach((v) => names.add(v.name))
      p.process_values.forEach((v) => names.add(v.name))
    })
  })
  return [...names]
}

export function ConditionEditor({
  peas,
  initial,
  onSave,
  onClose,
}: {
  peas: PeaDetail[]
  initial: Condition
  onSave: (c: Condition) => void
  onClose: () => void
}) {
  const [type, setType] = useState<CondType>(
    initial.type === 'ValueThreshold' || initial.type === 'Elapsed' ? initial.type : 'StateReached',
  )
  const firstPea = peas[0]?.id ?? ''

  // StateReached
  const [srPea, setSrPea] = useState<number | ''>(initial.type === 'StateReached' ? initial.pea_id : firstPea)
  const [srService, setSrService] = useState(initial.type === 'StateReached' ? initial.service : '')
  const [srState, setSrState] = useState(initial.type === 'StateReached' ? initial.state : 'COMPLETED')
  // ValueThreshold
  const [vtPea, setVtPea] = useState<number | ''>(initial.type === 'ValueThreshold' ? initial.pea_id : firstPea)
  const [vtValue, setVtValue] = useState(initial.type === 'ValueThreshold' ? initial.value_name : '')
  const [vtOp, setVtOp] = useState<(typeof OPS)[number]>(initial.type === 'ValueThreshold' ? initial.op : '>')
  const [vtThr, setVtThr] = useState(initial.type === 'ValueThreshold' ? String(initial.threshold) : '0')
  // Elapsed
  const [seconds, setSeconds] = useState(initial.type === 'Elapsed' ? String(initial.seconds) : '5')

  const srServices = peas.find((p) => p.id === srPea)?.services ?? []
  const vtValues = valueNames(peas.find((p) => p.id === vtPea) ?? ({ process_values: [], services: [] } as unknown as PeaDetail))

  function build(): Condition | null {
    if (type === 'StateReached')
      return srPea === '' || !srService ? null : { type, pea_id: Number(srPea), service: srService, state: srState }
    if (type === 'ValueThreshold')
      return vtPea === '' || !vtValue || vtThr === '' ? null
        : { type, pea_id: Number(vtPea), value_name: vtValue, op: vtOp, threshold: Number(vtThr) }
    return { type: 'Elapsed', seconds: Number(seconds || 0) }
  }
  const result = build()

  return (
    <Modal title="Edit transition condition" onClose={onClose}>
      <label className="mb-1.5 block text-xs font-medium text-dim">Advance when…</label>
      <select className={sel} value={type} onChange={(e) => setType(e.target.value as CondType)}>
        <option value="StateReached">a service reaches a state</option>
        <option value="ValueThreshold">a value crosses a threshold</option>
        <option value="Elapsed">a time has elapsed</option>
      </select>

      {type === 'StateReached' && (
        <div className="mt-4 grid gap-3">
          <select className={sel} value={srPea} onChange={(e) => { setSrPea(Number(e.target.value)); setSrService('') }}>
            <option value="" disabled>PEA…</option>
            {peas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className={sel} value={srService} disabled={srPea === ''} onChange={(e) => setSrService(e.target.value)}>
            <option value="" disabled>Service…</option>
            {srServices.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
          <select className={sel} value={srState} onChange={(e) => setSrState(e.target.value)}>
            {STABLE_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      )}

      {type === 'ValueThreshold' && (
        <div className="mt-4 grid gap-3">
          <select className={sel} value={vtPea} onChange={(e) => { setVtPea(Number(e.target.value)); setVtValue('') }}>
            <option value="" disabled>PEA…</option>
            {peas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className={sel} value={vtValue} disabled={vtPea === ''} onChange={(e) => setVtValue(e.target.value)}>
            <option value="" disabled>Value…</option>
            {vtValues.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
          <div className="flex gap-2">
            <select className={`${sel} w-24`} value={vtOp} onChange={(e) => setVtOp(e.target.value as (typeof OPS)[number])}>
              {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <input
              className={sel}
              type="number"
              value={vtThr}
              onChange={(e) => setVtThr(e.target.value)}
              placeholder="threshold"
            />
          </div>
        </div>
      )}

      {type === 'Elapsed' && (
        <div className="mt-4 flex items-center gap-2">
          <input className={`${sel} w-32`} type="number" min={0} value={seconds} onChange={(e) => setSeconds(e.target.value)} />
          <span className="text-sm text-dim">seconds after the step starts</span>
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!result} onClick={() => result && onSave(result)}>Save</Button>
      </div>
    </Modal>
  )
}
