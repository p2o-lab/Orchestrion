// @vitest-environment jsdom
//
// Tier-2 tests — the first in the project. Everything provable by pure logic lives in
// `ui/conditions.test.ts` (node environment, fast); this file covers only what genuinely
// needs a DOM: that the form *renders* what it was handed and *returns* what was authored.
//
// The regression it exists for: the old editor knew three leaf kinds, so an
// incoming `And`/`Or`/`Always` degraded to `StateReached` on open and Save wrote that back,
// **destroying the authored compound** (chart §11 item 4).

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Condition, PeaDetail } from '../api/types'
import { ConditionEditor } from './ConditionEditor'

// RTL only auto-registers its cleanup when vitest runs with `globals: true`. This project
// keeps globals off (the pure suites import what they use), so unmounting is explicit —
// without it every render stacks up in the same document and queries match across tests.
afterEach(cleanup)

const value = (name: string) => ({ name, kind: 'analog', direction: 'out' as const, writable: false })

const PEA: PeaDetail = {
  id: 1,
  project_id: 1,
  name: 'HC30',
  aml_filename: 'hc30.aml',
  endpoint_url: 'opc.tcp://localhost:4840',
  created_at: '2026-01-01T00:00:00Z',
  type_name: 'HC30',
  mtp_version: '1.1.0',
  device_revision: '1',
  manufacturer_uri: 'urn:test',
  product_code: 'HC30',
  process_values: [value('Temp'), value('Level')],
  services: [
    {
      name: 'Stirring',
      config_parameters: [],
      control_nodes: [],
      procedures: [
        { name: 'Continuous', procedure_id: 1, is_self_completing: false, parameters: [], report_values: [], process_values: [] },
      ],
    },
  ],
}

function open(initial: Condition, allowAlways = true) {
  const onSave = vi.fn()
  const onClose = vi.fn()
  render(<ConditionEditor peas={[PEA]} initial={initial} onSave={onSave} onClose={onClose} allowAlways={allowAlways} />)
  return { onSave, onClose }
}

const kindSelects = () => screen.getAllByLabelText('Condition kind')
const save = () => screen.getByRole('button', { name: 'Save' })

describe('an authored compound survives a round trip', () => {
  const compound: Condition = {
    type: 'And',
    conditions: [
      { type: 'StateReached', pea_id: 1, service: 'Stirring', state: 'COMPLETED' },
      { type: 'ValueThreshold', pea_id: 1, value_name: 'Temp', op: '>', threshold: 80 },
    ],
  }

  it('opens showing ALL of… — not a degraded StateReached', () => {
    open(compound)
    expect((kindSelects()[0] as HTMLSelectElement).value).toBe('And')
  })

  it('renders a row per child', () => {
    open(compound)
    // one select for the root + one per child
    expect(kindSelects()).toHaveLength(3)
    expect((kindSelects()[1] as HTMLSelectElement).value).toBe('StateReached')
    expect((kindSelects()[2] as HTMLSelectElement).value).toBe('ValueThreshold')
  })

  it('saves it back byte-identical when nothing is touched — THE regression', () => {
    const { onSave } = open(compound)
    save().click()
    expect(onSave).toHaveBeenCalledWith(compound)
  })

  it('shows the whole expression, not a placeholder', () => {
    open(compound)
    expect(screen.getByText('✓ COMPLETED AND Temp > 80')).toBeTruthy()
  })
})

describe('Always round-trips too', () => {
  it('opens as Always and saves as Always', () => {
    const { onSave } = open({ type: 'Always' })
    expect((kindSelects()[0] as HTMLSelectElement).value).toBe('Always')
    save().click()
    expect(onSave).toHaveBeenCalledWith({ type: 'Always' })
  })
})

describe('authoring a compound from a leaf', () => {
  it('keeps the leaf as the first child instead of discarding it', async () => {
    const user = userEvent.setup()
    const leaf: Condition = { type: 'StateReached', pea_id: 1, service: 'Stirring', state: 'HELD' }
    const { onSave } = open(leaf)

    await user.selectOptions(kindSelects()[0], 'And')
    save().click()

    expect(onSave).toHaveBeenCalledWith({ type: 'And', conditions: [leaf] })
  })

  it('adds and removes children, and refuses to remove the last one', async () => {
    const user = userEvent.setup()
    const leaf: Condition = { type: 'StateReached', pea_id: 1, service: 'Stirring', state: 'HELD' }
    open(leaf)

    await user.selectOptions(kindSelects()[0], 'And')
    // one child → no remove button offered (min_length=1, audit P2c)
    expect(screen.queryByLabelText('Remove condition 1')).toBeNull()

    await user.click(screen.getByRole('button', { name: '+ add condition' }))
    expect(kindSelects()).toHaveLength(3)
    expect(screen.getByLabelText('Remove condition 1')).toBeTruthy()

    await user.click(screen.getByLabelText('Remove condition 2'))
    expect(kindSelects()).toHaveLength(2)
    expect(screen.queryByLabelText('Remove condition 1')).toBeNull()
  })
})

describe('Save is gated on a complete tree', () => {
  it('is disabled while a nested leaf is unfilled', async () => {
    const user = userEvent.setup()
    open({ type: 'StateReached', pea_id: 1, service: 'Stirring', state: 'HELD' })

    await user.selectOptions(kindSelects()[0], 'And')
    await user.click(screen.getByRole('button', { name: '+ add condition' }))
    // the new child has no service picked yet
    expect((save() as HTMLButtonElement).disabled).toBe(true)

    const second = screen.getByText('and · 2').closest('div')!.parentElement!
    await user.selectOptions(within(second).getByLabelText('Service'), 'Stirring')
    expect((save() as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('Always is withheld where a continuous step precedes the transition', () => {
  it('is not offered in the kind list', () => {
    open({ type: 'StateReached', pea_id: 1, service: 'Stirring', state: 'HELD' }, false)
    const options = within(kindSelects()[0]).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(options).not.toContain('Always')
    expect(options).toContain('StateReached')
  })

  it('still SHOWS an Always that is already there, and blocks Save with a reason', () => {
    // Refusing to render it would repeat the disappearing-data bug this rewrite exists to fix.
    open({ type: 'Always' }, false)
    expect((kindSelects()[0] as HTMLSelectElement).value).toBe('Always')
    expect((save() as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/completion criterion/)).toBeTruthy()
  })

  it('catches an Always buried inside an Or', () => {
    // `Or` is true the moment any child is, so a nested Always is exactly as fatal as a bare one.
    open({ type: 'Or', conditions: [{ type: 'Elapsed', seconds: 5 }, { type: 'Always' }] }, false)
    expect((save() as HTMLButtonElement).disabled).toBe(true)
  })
})
