# Open-Source POL — MVP & Architecture

> Bridge doc from research → build. Companion to **`POL_and_MTP_Standards_Research.md`** (the standards foundation). This one makes the *decisions* that research deliberately left open, and defines the **walking skeleton** we build first.
>
> _Created 2026-07-08._

---

## 1. Decision record (locked)

| Decision | Choice | Why |
|---|---|---|
| **Backend** | **FastAPI + asyncua** (Python) | A POL's core is long-lived async machinery — persistent OPC UA sessions per PEA, continuous subscriptions, a state manager, WebSocket push. All want **one asyncio event loop**. asyncua's client sits in the same loop as the API + WebSockets: `subscription → state manager → WebSocket push` is one seamless async chain. Django's sync core would need Channels+Daphne+Redis and the OPC UA logic outside the request cycle anyway. |
| **Frontend** | **React** | Web HMI for the drag-and-drop/monitoring vision; talks REST + WebSocket to the backend. |
| **Approach** | **Full greenfield** | Build from the standards we hold (2658-1…7, ISA-88, free schemas). Recipol/Polaris are **reference material**, not foundations. |
| **Precedence** | **Standards → peers → peer-bugs-as-tests** | When our POL and a peer disagree, the **standard decides**. Recipol/Polaris bugs become explicit regression tests. |

**Peers, demoted to reference:** consult for (a) worked examples when a draft clause is ambiguous, (b) test artifacts, (c) documented anti-patterns → our regression tests (Recipol's hardcoded CAEX-3.0; Polaris's OpMode/SourceMode non-classic bugs).

---

## 2. Scope — the walking skeleton (v1)

**In scope (the spine, end-to-end against live VisionForge):**
1. **Import one MTP** (`.aml`) → parse into an internal model.
2. **Connect** to the PEA over OPC UA (asyncua client), resolving namespace **by URI**.
3. **List services** + subscribe to and display **live `StateCur`** (the 16-state machine).
4. **Handshake** — switch the target service to **Automatic mode + External source** (or **Operator** mode) via the mode DataAssemblies (`ServiceOperationMode`/`ServiceSourceMode`), then **select a service procedure** (write the procedure request `ProcedureExt`/`ProcedureOp`, verify the `ProcedureReq` readback). *Without this, the PEA silently ignores `CommandExt` — see research §4.3.1.*
5. **Send commands** — Start / Stop (write `CommandExt`/`CommandOp`), respecting `CommandEn`.
6. **Log** everything (mode/procedure changes, state transitions, commands, operator actions) — visible in the UI.

**Explicit non-goals for v1** (come *after* the spine works):
- Drag-and-drop recipe builder + recipe engine (ISA-88/BatchML).
- Auto-generated faceplates from the HMI aspect (Blatt 2).
- Alarm management (Blatt 6/7).
- Multi-PEA orchestration, MES/ERP northbound, MTP 2.0 profiles.

> Rule: if a feature isn't on the 6-step spine, it's v2. Resist scope creep — that's what stalls builds.

---

## 3. Architecture (simplified, open-source scope)

```
┌────────────────────────── React frontend (SPA) ──────────────────────────┐
│  PEA list · Service cards (live state) · Start/Stop buttons · Log panel    │
└───────────────▲───────────────────────────────────────┬───────────────────┘
                │ WebSocket (live state/log push)        │ REST (import MTP, commands)
┌───────────────┴───────────────────────────────────────▼───────────────────┐
│                       FastAPI app  (single asyncio loop)                    │
│  ┌────────────┐  ┌───────────────┐  ┌────────────────┐  ┌───────────────┐  │
│  │ MTP parser │→ │ PEA registry  │  │ State manager  │  │ Event log     │  │
│  │ (AML/CAEX) │  │ (model+status)│  │ (16-state SM)  │  │ (audit trail) │  │
│  └────────────┘  └───────┬───────┘  └───────▲────────┘  └───────▲───────┘  │
│                          │                  │ StateCur changes  │          │
│                  ┌───────▼──────────────────┴───────────────────┴───────┐  │
│                  │   OPC UA connection manager  (asyncua client/session) │  │
│                  └───────────────────────────▲───────────────────────────┘ │
└──────────────────────────────────────────────┼─────────────────────────────┘
                                                │ OPC UA (subscribe StateCur/CommandEn; write Command)
                                        ┌───────┴────────┐
                                        │  VisionForge   │  PEA (OPC UA server, :48050)
                                        └────────────────┘
```

**The async chain that defines the design:** asyncua subscription fires on a `StateCur` change → state manager updates the service model → change is pushed to the browser over WebSocket **and** appended to the event log. One event loop, no bridges.

---

## 4. Components (v1 = spine; rest deferred)

| Component | v1 responsibility | Standard | Deferred |
|---|---|---|---|
| **MTP parser** | Parse AML/CAEX **2.15, namespace-agnostic**; extract services, procedures, comm bindings (ns URI + node id). No RoleClasses. | 2658-1/-3/-4, IEC 62714/62424 | HMI + alarm aspects |
| **PEA registry** | Hold parsed model + endpoint + online status | 2658-1 | multi-PEA, persistence |
| **OPC UA conn. mgr** | asyncua session per PEA; resolve ns **by URI**; subscribe `StateCur`/`CommandEn` **and the mode (`StateOpAct`/`StateAutAct`/`SrcExtAct`) + `ProcedureReq`/`ProcedureCur`** nodes; write `Command`, mode, and procedure requests | IEC 62541, 2658-4/-5 | reconnection policy, security |
| **State manager** | Canonical **16-state machine** (Table 14 encoding); expose Start/Stop now, full command set later; enforce layer priority | 2658-4 | Hold/Pause/Abort UI |
| **Service control** *(op-mode / source-mode / procedure)* | Own the **mode handshake** (Operator ↔ Automatic, Internal ↔ External) via `ServiceOperationMode`/`ServiceSourceMode`, confirming with the `*Act` readbacks; **select the procedure** (`ProcedureExt`/`ProcedureOp` → verify `ProcedureReq`) before Start; resolve mode from the split BOOLs, not a combined `OpMode` node | 2658-4 §6.2.1, §8.2.2.2–.4 | Auto-Internal ctrl, per-source policy |
| **Event log** | Append state transitions, commands, operator actions; stream to UI | — | historian/DB, GMP audit |
| **Recipe engine** | — | ISA-88, B2MML | **all v2** |
| **HMI aggregation** | Basic service cards + command buttons | 2658-2 | auto faceplates, drag-drop |

---

## 5. Locked technical facts from research (build to these)

- **CAEX 2.15**, `noNamespaceSchemaLocation` → parser must be **namespace-agnostic** (tolerate 2.15 *and* 3.0). Recipol's hardcoded 3.0 = anti-pattern → regression test. `[research §4.1]`
- **Namespace by URI**, not index: server registers a URI; POL resolves it to whatever index the live server reports. `[research §4.4]`
- **Control/status encoding = 2658-4 Table 14** (verified): `StateCur` states (idle=16, execute=64, …), `Command` (start=4, stop=8, reset=2, …), `CommandEn` bitmask for legal transitions. One bit set for state/command; undefined commands ignored+reset by PEA. `[research §4.3]`
- **16-state machine**, 5 priority layers (Abort > Stop > Hold > …). `[research §4.3]`
- **Command gating:** `CommandExt` is honored **only in Automatic mode + External source**; `CommandOp` only in Operator mode. The **mode + procedure handshake precedes any command** — a PEA silently drops commands on the wrong channel. `[2658-4][research §4.3.1]`
- **No CAEX RoleClasses** in MTP. `[research §4.1]`

---

## 6. Project structure

Package name is **`orchestrion`** (locked). The repo, `backend/.venv` (Python 3.12.6), and the Vite `react-ts` frontend already exist; the tree below shows the target once M0 is finished.

```
Orchestrion/                 (repo root — already exists)
├─ backend/
│  ├─ .venv/                  Python 3.12.6 virtualenv (done)
│  ├─ pyproject.toml          fastapi, asyncua, uvicorn, pytest, pydantic  (requires-python >=3.12)
│  ├─ orchestrion/            the backend package
│  │  ├─ main.py              FastAPI app + lifespan (starts asyncio machinery)
│  │  ├─ mtp/                 parser (AML/CAEX 2.15, namespace-agnostic)
│  │  │  ├─ parser.py
│  │  │  └─ model.py          Pea, Service, ServiceProcedure, DataAssembly
│  │  ├─ opcua/               asyncua connection manager + subscriptions
│  │  │  └─ connection.py
│  │  ├─ state/               16-state machine + Table 14 codes
│  │  │  ├─ machine.py
│  │  │  └─ codes.py          StateCode/CommandCode enums (from Table 14)
│  │  ├─ registry.py          PEA registry
│  │  ├─ log.py               event log + WebSocket broadcast
│  │  └─ api/                 REST routes + WebSocket endpoint
│  └─ tests/                  incl. regression tests (peer anti-patterns)
│     └─ artifacts/           MTP samples (MTPPy examples, VisionForge output)
└─ frontend/                  React app (Vite, react-ts): PEA list, service cards, log
                              — scaffolded; dev proxy + .gitignore done
```

---

## 7. Milestones

| M | Goal | Done when |
|---|---|---|
| **M0** | Scaffold backend (FastAPI + asyncua deps) + frontend (Vite/React); health endpoint | `GET /api/health` returns ok; React shell loads |
| **M1** | **MTP parser** builds the model from a real `.aml` | Parses VisionForge `.aml` → services/procedures/comm bindings; unit-tested |
| **M2** | **Connect + read** live state | asyncua connects to VisionForge:48050, resolves ns by URI, subscribes `StateCur`; UI shows live state |
| **M3** | **Command** the service | **Mode switched to Automatic/External** (confirmed via `StateAutAct`/`SrcExtAct`), **procedure selected and confirmed** (`ProcedureReq` readback), **then** Start/Stop accepted on `CommandExt`; state transitions observed live; `CommandEn` drives button enable |
| **M4** | **Log + polish** | Transitions/commands stream to a UI log panel; end-to-end demo vs VisionForge |

**M1–M3 are stack-independent proof the spine works.** After M4, revisit v2 (recipe engine, faceplates, alarms).

---

## 8. Testing strategy

- **Standards-authoritative:** conformance asserted against 2658 (Table 14 codes, state transitions, manifest structure).
- **Peer bugs → regression tests:**
  - CAEX-3.0-hardcoding test: parser must accept a 2.15 file with no default namespace (Recipol failed this).
  - Non-classic OpMode/SourceMode test: split-boolean mode nodes must resolve without an `OpMode` node (Polaris failed this).
- **Test artifacts:** MTPPy `examples/*.aml`, VisionForge generated `.aml`, vendor HC30 sample.
- **Live integration:** the ultimate check is M4 against the running VisionForge PEA.

---

## 9. Next action

**M0 remainder.** The `Orchestrion` repo, `backend/.venv` (Python 3.12.6), and the Vite `react-ts` frontend (dev proxy + `.gitignore`) already exist. Remaining: add `backend/pyproject.toml` (`requires-python >=3.12`; deps `fastapi`, `asyncua`, `uvicorn`, `pytest`, `pydantic`), create the `orchestrion` package with a FastAPI `/api/health` endpoint, and verify both dev servers run. Then M1 (parser) against a real VisionForge `.aml`.

> **Endpoint path — `/api/health`, not `/health`.** The Vite dev proxy forwards `/api/*` **without a `rewrite`**, so the backend must own the `/api` prefix; a bare `/health` is shadowed by the `:5173` dev server and never reaches uvicorn. *(Decided 2026-07-16 — see `docs/progress/001_m0_scaffold.md` open item 5.)*

> **Live progress lives in the journal.** This section is the original plan of record; for what is actually done, read `docs/progress/000_INDEX.md` + the latest journal (Rule 3). As of 2026-07-16 `pyproject.toml` and the `/api/health` endpoint are **done**.
