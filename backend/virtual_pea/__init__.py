"""VirtualPEA — a standards-conformant OPC UA PEA for testing the POL offline.

This is a **test double**, not part of the POL. It serves exactly the address
space our HC30 fixture declares (namespace URI + node identifiers read straight
from the .aml) and runs the [2658-4:2022] service state machine behind it, so the
POL can be driven end-to-end without live hardware.

Deliberately independent of `orchestrion.mtp` for its *semantics*: the state
codes (Table 14) and the state machine (§6.2.2) are re-derived here from the
standard, never imported from the POL. If both sides shared one encoding, a
mistake in it could not be caught. Only the node *addresses* are read from the
same .aml the POL parses — those come from the vendor file, not from either side.

NOT built from the MTPPy framework: its ServiceControl omits 10 of Table 13's
attributes, invents a Manual source mode and `IsDefault`, assigns the forbidden
ProcedureID 0, and hardcodes namespace index 3 without registering a URI. See
docs/progress for the full measurement.
"""
