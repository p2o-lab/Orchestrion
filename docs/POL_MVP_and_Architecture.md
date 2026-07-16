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

**Peers, demoted to reference:** consult for (a) worked examples when a draft clause is ambiguous, (b) test artifacts, (c) documented anti-patterns → our regression tests (Recipol failing on CAEX 2.15; Polaris's OpMode/SourceMode non-classic bugs).

> **Peer standing — measured 2026-07-16 by the MTP version each one's shipped artifact declares** (research §8).
> This ranks them **as artifact sources only**; Rule 1 is unchanged — *peer **code** is never a source of truth,
> and the 2026-07-16 `ServiceProcedure` error is what happens when it leaks in.*
> - ⭐ **Recipol — the reference to go to.** Ships **HC30**: CAEX 3.0 / manifest **1.1.0** / `ServiceSet`
>   **1.0.0** (released Blatt 4). The only artifact matching both our container target and the released service
>   model → **the M1 fixture**.
> - **MTPPy — outdated; no longer serves the build.** Manifest 1.0.0 + `2658-4` **v0.1.0** draft; its service
>   model contradicts released Blatt 4:2022 in four measured ways. Retained **only** as the 2.15/1.0.0
>   regression fixture — **still accessible if needed**, never a model source.
> - **Polaris — most outdated** (`2658-2/-3/-4` all v0.1.0). Reference/access only.

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
| **MTP parser** | Parse AML/**CAEX 3.0 (manifest 1.1.0)**, namespace-agnostic, behind a version seam; extract services, procedures, comm bindings (ns URI + node id). Match types by `RefBaseSystemUnitPath`/`RefBaseClassPath`/`RefAttributeType`; join aspects by `RefID`. | 2658-1**:2022**/-3/-4 (+**-5.1** for the OPC UA classes), IEC 62714 Ed. 2.0 / CAEX 3.0 | **CAEX 2.15 / manifest 1.0.0 tolerance (later increment)**, HMI + alarm aspects, `ObjectItem`/`MethodItem` |
| **PEA registry** | Hold parsed model + endpoint + online status | 2658-1 | multi-PEA, persistence |
| **OPC UA conn. mgr** | asyncua session per PEA; resolve ns **by URI**; subscribe `StateCur`/`CommandEn` **and the mode (`StateOpAct`/`StateAutAct`/`SrcExtAct`) + `ProcedureReq`/`ProcedureCur`** nodes; write `Command`, mode, and procedure requests | IEC 62541, 2658-4/-5 | reconnection policy, security |
| **State manager** | Canonical **16-state machine** (Table 14 encoding); expose Start/Stop now, full command set later; enforce layer priority | 2658-4 | Hold/Pause/Abort UI |
| **Service control** *(op-mode / source-mode / procedure)* | Own the **mode handshake** (Operator ↔ Automatic, Internal ↔ External) via `ServiceOperationMode`/`ServiceSourceMode`, confirming with the `*Act` readbacks; **select the procedure** (`ProcedureExt`/`ProcedureOp` → verify `ProcedureReq`) before Start; resolve mode from the split BOOLs, not a combined `OpMode` node | 2658-4 §6.2.1, §8.2.2.2–.4 | Auto-Internal ctrl, per-source policy |
| **Event log** | Append state transitions, commands, operator actions; stream to UI | — | historian/DB, GMP audit |
| **Recipe engine** | — | ISA-88, B2MML | **all v2** |
| **HMI aggregation** | Basic service cards + command buttons | 2658-2 | auto faceplates, drag-drop |

---

## 5. Locked technical facts from research (build to these)

- **⚠ TWO manifest versions = two formats — corrected 2026-07-16 (was: "CAEX 2.15 … tolerate 2.15 and 3.0").**
  This is **not** just a namespace difference, and namespace-agnostic XPath alone is **not sufficient**:

  | | **Manifest 1.0.0** — `[2658-1:2019]` *released* | **Manifest 1.1.0** — `[2658-1:2022]` *draft* |
  |---|---|---|
  | Container | CAEX **2.15**, `noNamespaceSchemaLocation`, no namespace | CAEX **3.0**, `xmlns=http://www.dke.de/CAEX` (IEC 62714 Ed. 2.0) |
  | Aspect ToC | `ExternalDataConnector` + `refURI` | IC **`AspectSetReference`** + **`AspectRef`** → IH GUID |
  | Dynamic binding | `AttributeDataType="xs:IDREF"` | AT **`IDLinkAttributeType`** (`AttributeDataType` stays `xs:string`) |
  | Object IDs | CAEX-optional string | **mandatory GUID** (RFC 4122) |

  A 1.0.0-based parser finds **zero aspects** in a 1.1.0 file.
- **Build target = Manifest 1.1.0 (CAEX 3.0) + `ServiceSet` 1.0.0.** Forced, not preferred: `AttributeTypeLib`
  exists **only in CAEX 3.0**, and the **released** `[2658-4:2022]` defines three AttributeType libraries — so
  the released service standard **presumes CAEX 3.0**. A 2.15 file structurally cannot carry it.
  *Caveat: the 1.1.0 manifest spec is an **Entwurf/draft**, corroborated attribute-for-attribute by a real 2026
  vendor export.* `[research §4.1][002 §2]`
- **Sequencing (Rule 2):** build **1.1.0 only**, behind a **version-detection seam**
  (`CAEXFile/@SchemaVersion` + `AdditionalInformation/Document/@Version` — **not** namespace sniffing).
  **CAEX 2.15 / manifest 1.0.0 tolerance is a later, separate increment** (see §8). Never both in one unit.
- **Namespace-agnostic** matching is still required (1.1.0 is namespaced, 1.0.0 is not) — necessary, but only
  one part of the version split.
- **Type identification = `RefBaseSystemUnitPath` / `RefBaseClassPath` / `RefAttributeType`** — never
  RoleClasses (MTP **does** define them — `[2658-4:2022]` Table 21), never element **names** (free by spec;
  only the `ModuleTypePackage` IH name is fixed). `[research §4.1]`
- **Cross-aspect link = `RefID` GUID** (`LinkedObject` concept): IEs sharing a RefID are the same entity — this
  is how a `Service` reaches its `ServiceControl`. Verified in HC30. `[2658-1:2022 §8.5][002 §4]`
- **`ID` is a plain `xs:string` in both CAEX versions — never `xs:ID`.** No XML-native IDREF resolution exists;
  the parser **builds its own ID→element index**. `[002 §6.1]`
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
│  │  ├─ mtp/                 parser (AML/CAEX 3.0 @manifest 1.1.0; ns-agnostic; version seam)
│  │  │  ├─ parser.py
│  │  │  └─ model.py          Pea, Service, ServiceProcedure, DataAssembly   ← see naming note
│  │  ├─ opcua/               asyncua connection manager + subscriptions
│  │  │  └─ connection.py
│  │  ├─ state/               16-state machine + Table 14 codes
│  │  │  ├─ machine.py
│  │  │  └─ codes.py          StateCode/CommandCode enums (from Table 14)
│  │  ├─ registry.py          PEA registry
│  │  ├─ log.py               event log + WebSocket broadcast
│  │  └─ api/                 REST routes + WebSocket endpoint
│  └─ tests/                  incl. regression tests (peer anti-patterns)
│     └─ artifacts/           MTP samples — HC30 (1.1.0, primary); MTPPy minimal (2.15/1.0.0, later)
└─ frontend/                  React app (Vite, react-ts): PEA list, service cards, log
                              — scaffolded; dev proxy + .gitignore done
```

> **Naming note (`model.py`).** `ServiceProcedure` here is an **internal Python class name** and is a free
> choice. **The CAEX path the parser matches is the standard's: `MTPServiceSUCLib/Service/Procedure`**
> (`[2658-4:2022]` Table 30) — *not* `.../ServiceProcedure`, which is MTPPy's v0.1.0-draft spelling and matches
> **nothing** in a conformant file. Standards-facing strings must be exact; internal names need only be clear.

---

## 7. Milestones

| M | Goal | Done when |
|---|---|---|
| **M0** | Scaffold backend (FastAPI + asyncua deps) + frontend (Vite/React); health endpoint | `GET /api/health` returns ok; React shell loads |
| **M1** | **MTP parser** builds the model from a real `.aml` | Parses **HC30** (`2026-05-18-HC30_Stirring_V8.aml` — CAEX 3.0 / manifest 1.1.0 / ServiceSet 1.0.0) → services/procedures/comm bindings; unit-tested. *(Was "VisionForge `.aml`" — that file is MTPPy-generated (manifest 1.0.0 + 2658-4 v0.1.0) and the copy in Recipol's tree is malformed; corrected 2026-07-16, see `002` §7.)* |
| **M2** | **Connect + read** live state | asyncua connects to VisionForge:48050, resolves ns by URI, subscribes `StateCur`; UI shows live state |
| **M3** | **Command** the service | **Mode switched to Automatic/External** (confirmed via `StateAutAct`/`SrcExtAct`), **procedure selected and confirmed** (`ProcedureReq` readback), **then** Start/Stop accepted on `CommandExt`; state transitions observed live; `CommandEn` drives button enable |
| **M4** | **Log + polish** | Transitions/commands stream to a UI log panel; end-to-end demo vs VisionForge |

**M1–M3 are stack-independent proof the spine works.** After M4, revisit v2 (recipe engine, faceplates, alarms).

---

## 8. Testing strategy

- **Standards-authoritative:** conformance asserted against 2658 (Table 14 codes, state transitions, manifest structure).
- **Peer bugs → regression tests:**
  - **No-namespace / CAEX 2.15 test** *(re-framed 2026-07-16)*: the parser must accept a **manifest 1.0.0**
    file — CAEX 2.15, no default namespace, `xs:IDREF` binding, `ExternalDataConnector`/`refURI` ToC.
    Recipol fails this. **Note the earlier framing was wrong:** Recipol's CAEX-3.0 hardcoding is not itself the
    anti-pattern — 3.0 is where the standard went at manifest 1.1.0. **The defect is *failing on 2.15*, not
    *preferring 3.0*.** This test lands with the **1.0.0 tolerance increment**, not in the first M1 step.
  - Non-classic OpMode/SourceMode test: split-boolean mode nodes must resolve without an `OpMode` node (Polaris failed this).
- **Test artifacts** *(re-assessed 2026-07-16 by measuring each file's declared MTP version — see `002` §7)*:
  - ⭐ **`2026-05-18-HC30_Stirring_V8.aml`** (ships with **Recipol**) — CAEX 3.0 / manifest **1.1.0** /
    `ServiceSet` **1.0.0**; a real SIMATIC S7-1500 export. **The M1 fixture** — the only artifact on the current
    manifest *and* the released service model.
  - **`example_minimal_manifest.aml`** (MTPPy) — CAEX 2.15 / manifest 1.0.0, clean, `xs:IDREF` ×149. Fixture
    for the **1.0.0 tolerance** increment only. Its **service** model is 2658-4 **v0.1.0** and deviates from
    released Blatt 4:2022 → **do not build the service model against it.**
  - **Polaris `CPS EDP/Manifest.aml`** — 2658-2/-3/-4 all **v0.1.0**; oldest. Reference only.
  - ~~VisionForge generated `.aml`~~ — MTPPy-generated **and** malformed (3.0 namespace injected into a 2.15
    file). **Dropped as a fixture.**
- **Live integration:** the ultimate check is M4 against the running VisionForge PEA.

---

## 9. Next action

**M0 is complete** (2026-07-16). **Next: M1 — the MTP parser**, built against **HC30**
(`../reference/Recipol/Recipol/artifacts/2026-05-18-HC30_Stirring_V8.aml` — CAEX 3.0 / manifest 1.1.0 /
ServiceSet 1.0.0), one unit at a time per Rule 2, behind a version-detection seam (§5). The normative structure
is established from primary sources in **`docs/progress/002_m1_mtp_parser.md`** — read it before writing parser
code.

*(Historical: the M0 remainder was `pyproject.toml` + the `orchestrion` package + `GET /api/health` + the proxy
pin — all done; see `docs/progress/001_m0_scaffold.md`.)*

> **Endpoint path — `/api/health`, not `/health`.** The Vite dev proxy forwards `/api/*` **without a `rewrite`**, so the backend must own the `/api` prefix; a bare `/health` is shadowed by the `:5173` dev server and never reaches uvicorn. *(Decided 2026-07-16 — see `docs/progress/001_m0_scaffold.md` open item 5.)*

> **Live progress lives in the journal.** This section is the original plan of record; for what is actually done, read `docs/progress/000_INDEX.md` + the latest journal (Rule 3). As of 2026-07-16 `pyproject.toml` and the `/api/health` endpoint are **done**.
