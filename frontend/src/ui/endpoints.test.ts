import { describe, expect, it } from 'vitest'
import type { PeaSummary } from '../api/types'
import { conflictingEndpoints, hasEndpointConflict, normaliseEndpoint } from './endpoints'

function pea(id: number, name: string, endpoint_url: string): PeaSummary {
  return {
    id,
    project_id: 1,
    name,
    aml_filename: 'HC30.aml',
    endpoint_url,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('normaliseEndpoint', () => {
  it('ignores case and a trailing slash', () => {
    expect(normaliseEndpoint('OPC.TCP://127.0.0.1:48050/')).toBe('opc.tcp://127.0.0.1:48050')
    expect(normaliseEndpoint('  opc.tcp://127.0.0.1:48050  ')).toBe('opc.tcp://127.0.0.1:48050')
  })

  it('does NOT resolve localhost to 127.0.0.1 — the documented limitation', () => {
    // Same server, two spellings. Pinned so the limitation is a decision on record rather
    // than something a later reader mistakes for a bug. Mirrors `_normalise_endpoint`.
    expect(normaliseEndpoint('opc.tcp://localhost:48050')).not.toBe(
      normaliseEndpoint('opc.tcp://127.0.0.1:48050'),
    )
  })
})

describe('conflictingEndpoints', () => {
  it('is empty for a plant on distinct ports', () => {
    // Exactly what `virtual_pea.plant --count 3` produces.
    const plant = [
      pea(1, 'Reactor_A', 'opc.tcp://127.0.0.1:48050'),
      pea(2, 'Reactor_B', 'opc.tcp://127.0.0.1:48051'),
      pea(3, 'Blender', 'opc.tcp://127.0.0.1:48052'),
    ]
    expect(conflictingEndpoints(plant).size).toBe(0)
  })

  it('flags an endpoint used twice', () => {
    const peas = [
      pea(1, 'Reactor_A', 'opc.tcp://127.0.0.1:48050'),
      pea(2, 'Reactor_B', 'opc.tcp://127.0.0.1:48050'),
      pea(3, 'Blender', 'opc.tcp://127.0.0.1:48052'),
    ]
    expect([...conflictingEndpoints(peas)]).toEqual(['opc.tcp://127.0.0.1:48050'])
  })

  it('groups spellings that normalise to the same endpoint', () => {
    const peas = [
      pea(1, 'A', 'opc.tcp://127.0.0.1:48050'),
      pea(2, 'B', 'OPC.TCP://127.0.0.1:48050/'),
    ]
    expect(conflictingEndpoints(peas).size).toBe(1)
  })

  it('does not group PEAs that merely share a port number', () => {
    // Different hosts, same port — two real modules, not a conflict. This is why the check
    // is on the whole endpoint rather than the port.
    const peas = [
      pea(1, 'Reactor', 'opc.tcp://192.168.1.5:4840'),
      pea(2, 'Filler', 'opc.tcp://192.168.1.9:4840'),
    ]
    expect(conflictingEndpoints(peas).size).toBe(0)
  })

  it('ignores empty endpoints rather than grouping them', () => {
    // An MTP with no OPC UA server stores "". Several unknowns are not "the same server".
    const peas = [pea(1, 'A', ''), pea(2, 'B', ''), pea(3, 'C', '  ')]
    expect(conflictingEndpoints(peas).size).toBe(0)
  })

  it('is empty for an empty list', () => {
    expect(conflictingEndpoints([]).size).toBe(0)
  })
})

describe('hasEndpointConflict', () => {
  it('reports every member of a colliding group, not just the later one', () => {
    // The badge belongs on *both* cards: neither is more at fault than the other.
    const peas = [
      pea(1, 'Reactor_A', 'opc.tcp://127.0.0.1:48050'),
      pea(2, 'Reactor_B', 'opc.tcp://127.0.0.1:48050'),
      pea(3, 'Blender', 'opc.tcp://127.0.0.1:48052'),
    ]
    const conflicts = conflictingEndpoints(peas)
    expect(hasEndpointConflict(conflicts, peas[0].endpoint_url)).toBe(true)
    expect(hasEndpointConflict(conflicts, peas[1].endpoint_url)).toBe(true)
    expect(hasEndpointConflict(conflicts, peas[2].endpoint_url)).toBe(false)
  })

  it('matches regardless of spelling', () => {
    const conflicts = new Set(['opc.tcp://127.0.0.1:48050'])
    expect(hasEndpointConflict(conflicts, 'OPC.TCP://127.0.0.1:48050/')).toBe(true)
  })
})
