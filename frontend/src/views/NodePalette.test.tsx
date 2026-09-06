// @vitest-environment jsdom
//
// The palette's branch actions — `docs/POL_Recipe_Chart_GRAFCET.md` §7.
//
// The point of the gating is pedagogical: each action is enabled **only** on the node kind
// that can legally open that structure, so the palette teaches §4.3.2's link multiplicity
// instead of letting you build a chart that `graphToTransitions` will later refuse.
//   • parallel  — [IEC 60848:2013] §6.2.6, one **transition** to several steps
//   • selection — §6.2.3, one **step** to several transitions

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { NodeKind } from '../ui/recipeGraph'
import { NodePalette } from './NodePalette'

afterEach(cleanup)

function open(selectedKind: NodeKind | null) {
  const onBranch = vi.fn()
  const onQuickAdd = vi.fn()
  render(<NodePalette onQuickAdd={onQuickAdd} selectedKind={selectedKind} onBranch={onBranch} />)
  return { onBranch, onQuickAdd }
}

const parallel = () => screen.getByRole('button', { name: '+ parallel branch' }) as HTMLButtonElement
const selection = () => screen.getByRole('button', { name: '+ selection branch' }) as HTMLButtonElement

describe('a branch action is offered only on the kind that can open it', () => {
  it('offers nothing when nothing is selected', () => {
    open(null)
    expect(parallel().disabled).toBe(true)
    expect(selection().disabled).toBe(true)
  })

  it('a TRANSITION enables parallel and greys selection', () => {
    open('transition')
    expect(parallel().disabled).toBe(false)
    expect(selection().disabled).toBe(true)
  })

  it('a STEP enables selection and greys parallel', () => {
    open('step')
    expect(selection().disabled).toBe(false)
    expect(parallel().disabled).toBe(true)
  })
})

describe('clicking an enabled action reports it', () => {
  it('asks for a parallel branch off a transition', async () => {
    const user = userEvent.setup()
    const { onBranch } = open('transition')
    await user.click(parallel())
    expect(onBranch).toHaveBeenCalledWith('parallel')
  })

  it('asks for a selection branch off a step', async () => {
    const user = userEvent.setup()
    const { onBranch } = open('step')
    await user.click(selection())
    expect(onBranch).toHaveBeenCalledWith('selection')
  })

  it('a greyed action does nothing when clicked', async () => {
    const user = userEvent.setup()
    const { onBranch } = open('step')
    await user.click(parallel())
    expect(onBranch).not.toHaveBeenCalled()
  })
})

describe('the greyed action says what to select', () => {
  it('names the kind the action needs, so the rule is learnable', () => {
    open('step')
    expect(parallel().title).toMatch(/select a transition first/i)
  })

  it('explains the enabled one instead of scolding', () => {
    open('transition')
    expect(parallel().title).not.toMatch(/select a/i)
    expect(parallel().title).toMatch(/at the same time/i)
  })
})

describe('the two droppable kinds are still just step and transition', () => {
  it('offers no AND, OR, START or END block', () => {
    open(null)
    // §4.3.2 closes the element list; bar/START/END nodes were deleted.
    for (const gone of ['AND', 'OR', 'Start', 'End']) expect(screen.queryByText(gone)).toBeNull()
    expect(screen.getByText('Step')).toBeTruthy()
    expect(screen.getByText('Transition')).toBeTruthy()
  })
})
