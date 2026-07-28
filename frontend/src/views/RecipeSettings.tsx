import { useState } from 'react'
import type { RecipeHeader } from '../api/types'
import { Button, Input, Modal } from '../ui/primitives'
import { Icon } from '../ui/icons'

// Edit a recipe's header ([IEC 61512-1 §6.3.2]) + formula (§6.3.3 — recipe-level parameters).
export function RecipeSettings({
  header,
  formula,
  onSave,
  onClose,
}: {
  header: RecipeHeader
  formula: Record<string, number>
  onSave: (header: RecipeHeader, formula: Record<string, number>) => void
  onClose: () => void
}) {
  const [name, setName] = useState(header.name)
  const [author, setAuthor] = useState(header.author)
  const [product, setProduct] = useState(header.product)
  const [rows, setRows] = useState<{ k: string; v: string }[]>(
    Object.entries(formula).map(([k, v]) => ({ k, v: String(v) })),
  )

  function save() {
    const f: Record<string, number> = {}
    for (const r of rows) {
      if (r.k.trim() && r.v !== '' && !Number.isNaN(Number(r.v))) f[r.k.trim()] = Number(r.v)
    }
    onSave({ name: name.trim() || header.name, version: header.version, author, product }, f)
  }

  return (
    <Modal title="Recipe settings" onClose={onClose}>
      <div className="grid gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-dim">Name</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-dim">Author</label>
            <Input value={author} onChange={(e) => setAuthor(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-dim">Product</label>
            <Input value={product} onChange={(e) => setProduct(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="mt-5 mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-faint">Formula</span>
        <button
          onClick={() => setRows((r) => [...r, { k: '', v: '' }])}
          className="flex items-center gap-1 text-xs text-accent transition hover:text-accent-bright"
        >
          <Icon name="plus" size={13} /> Add parameter
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-faint">No formula parameters.</p>
      ) : (
        <div className="grid gap-2">
          {rows.map((row, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input
                className="flex-1"
                placeholder="name"
                value={row.k}
                onChange={(e) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, k: e.target.value } : r)))}
              />
              <Input
                className="w-28"
                type="number"
                placeholder="value"
                value={row.v}
                onChange={(e) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, v: e.target.value } : r)))}
              />
              <button
                onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-faint transition hover:bg-white/8 hover:text-danger"
                title="Remove"
              >
                <Icon name="trash" size={15} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={save} disabled={!name.trim()}>Save</Button>
      </div>
    </Modal>
  )
}
