"""Service state — the canonical [2658-4:2022] Table 14 encoding for the POL.

The state manager and API consume this; the MTP parser does not (it stops at node
addresses and never interprets a value). This is the POL's own decode of Table 14,
deliberately independent of `virtual_pea.codes` so that a mistake on either side is
caught when the POL runs against the VirtualPEA.
"""
