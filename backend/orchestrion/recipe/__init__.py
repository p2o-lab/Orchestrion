"""The recipe / orchestration engine (v0.2.0).

Design foundation: docs/POL_Recipe_Engine_Design.md. This package holds the master-recipe
data model (`model.py`), and — in later increments — condition evaluation (`conditions.py`)
and the execution engine (`engine.py`). It sits on top of the existing `opcua.control` and
`opcua.registry` seams; it adds orchestration logic only, no new OPC UA/control code.
"""
