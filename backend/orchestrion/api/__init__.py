"""HTTP + WebSocket surface: the workspace of projects and their PEAs.

Thin layer over the domain — parse/validate MTPs (`mtp_import`), persist projects and
PEAs (`orchestrion.db`), and expose live PEA state over WebSocket. Every response is a
plain schema; no XML or SQLAlchemy object crosses this boundary.
"""
