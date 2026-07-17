"""Persistence for the workspace — projects and their imported PEAs (SQLite).

A **Project** is a modular plant / plant configuration (VDI 2776 "modular plant";
the NAMUR-ZVEI position paper's "plant topology + assigned PEAs"). A **Pea** is one
imported MTP scoped to a project. Inter-PEA topology and recipes are deliberately NOT
modelled yet (Rule 4) — they are POL-level engineering artifacts that attach to these
same ids later, so the schema leaves room without building them now.
"""
