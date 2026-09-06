// @vitest-environment jsdom
//
// The OR-branch priority badge — `docs/POL_Recipe_Chart_GRAFCET.md` §8.
//
// Tested in isolation rather than through `TransitionNode`, because React Flow's `<Handle>`
// needs a node context that only a mounted canvas provides. The *ranking* logic is pure and
// covered in `ui/recipeGraph.test.ts`; what needs a DOM is the end-stop behaviour — the first
// branch cannot be raised and the last cannot be lowered.

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PriorityBadge } from './FlowNodes'

afterEach(cleanup)

const up = (rank: number) => screen.getByLabelText(`Raise branch ${rank} priority`) as HTMLButtonElement
const down = (rank: number) => screen.getByLabelText(`Lower branch ${rank} priority`) as HTMLButtonElement

describe('the badge shows where the branch sits', () => {
  it('renders the rank as a circled numeral', () => {
    render(<PriorityBadge rank={2} of={3} />)
    expect(screen.getByText('②')).toBeTruthy()
  })

  it('falls back to a plain number past the circled glyphs', () => {
    render(<PriorityBadge rank={12} of={12} />)
    expect(screen.getByText('12')).toBeTruthy()
  })

  it('says which of how many, and which way priority runs', () => {
    render(<PriorityBadge rank={2} of={3} />)
    expect(screen.getByTitle('Branch 2 of 3 — lower numbers are tried first')).toBeTruthy()
  })
})

describe('the end stops', () => {
  it('cannot raise the first branch', () => {
    render(<PriorityBadge rank={1} of={3} onMove={vi.fn()} />)
    expect(up(1).disabled).toBe(true)
    expect(down(1).disabled).toBe(false)
  })

  it('cannot lower the last branch', () => {
    render(<PriorityBadge rank={3} of={3} onMove={vi.fn()} />)
    expect(down(3).disabled).toBe(true)
    expect(up(3).disabled).toBe(false)
  })

  it('a middle branch moves both ways', () => {
    render(<PriorityBadge rank={2} of={3} onMove={vi.fn()} />)
    expect(up(2).disabled).toBe(false)
    expect(down(2).disabled).toBe(false)
  })
})

describe('moving reports a direction', () => {
  it('raises', async () => {
    const onMove = vi.fn()
    render(<PriorityBadge rank={2} of={3} onMove={onMove} />)
    await userEvent.click(up(2))
    expect(onMove).toHaveBeenCalledWith('up')
  })

  it('lowers', async () => {
    const onMove = vi.fn()
    render(<PriorityBadge rank={2} of={3} onMove={onMove} />)
    await userEvent.click(down(2))
    expect(onMove).toHaveBeenCalledWith('down')
  })

  it('a disabled end stop reports nothing', async () => {
    const onMove = vi.fn()
    render(<PriorityBadge rank={1} of={2} onMove={onMove} />)
    await userEvent.click(up(1))
    expect(onMove).not.toHaveBeenCalled()
  })
})

describe('the badge does not hijack the canvas drag', () => {
  it('carries nodrag, so pressing it never starts moving the node', () => {
    // React Flow treats pointer-down on a node as "move it"; `nodrag` opts these buttons out.
    // This is why §8's "draggable ①②③" became ▲▼ — see the note on PriorityBadge.
    const { container } = render(<PriorityBadge rank={1} of={2} />)
    expect(container.querySelector('.nodrag')).toBeTruthy()
  })
})
