# Process Orchestration Layers (POL) & the MTP Standard — Research Foundation

> **Purpose.** A verified, version-aware reference for designing a *new, modern open-source POL* — better HMI/UX, drag-and-drop recipe building, live PEA monitoring & control, and logging. This document is deliberately **standards-first**: it maps each relevant standard to *"what a conformant POL must therefore do."* Architecture is kept at reference depth (open-source scope), per the project brief.
>
> **Sourcing discipline.** Every non-trivial claim is tagged inline with its source using short keys (e.g. `[2658-1:2019]`, `[WG-2024]`). Full bibliography with access notes and *currency flags* is at the end (§12). Where a year/version could not be confirmed from a primary source, it is marked **⚠ unconfirmed** rather than guessed. Claims taken from the MTPPy open-source reference implementation (not the standard) are labelled `[MTPPy]` and treated as *illustrative, not authoritative*.
>
> **Version target.** This document centers on **MTP 1.1.0** — the latest *widely-implemented* baseline (what SIMATIC PCS neo 4.0, COPA-DATA zenon, etc. run today). **MTP 2.0** (officially published by PI on **2026-01-20**; summer 2025 was the missed target) is covered separately in §4.6 as *emerging — plan for it, don't build on it yet.*
>
> **⚠ Nuance, verified 2026-07-16 — do not read "1.1.0" as "released".** The MTP **manifest** aspect model
> **1.1.0** is specified by `[2658-1:2022-01]`, which is stamped **Entwurf/Draft** on every page; the only
> *released* Blatt 1 is **2019-10**, and it specifies manifest **1.0.0**. We nevertheless target 1.1.0, because
> (a) the **released** `[2658-4:2022]` service model presumes CAEX 3.0 (§4.1), and (b) real 2026 vendor exports
> are 1.1.0 (§4.1). So: **target 1.1.0 while its manifest spec is a draft** — a deliberate, evidenced choice, not
> an assumption. See `docs/progress/002_m1_mtp_parser.md` §2.
>
> _Compiled 2026-07-08._

---

## 1. TL;DR — the mental model

A modular process plant is built from **PEAs** (Process Equipment Assemblies = self-contained, PLC-automated skids/modules) that are orchestrated by a **POL** (Process Orchestration Layer = the superordinate control/operations system). The contract between them is the **MTP** (Module Type Package): a vendor-neutral file the PEA manufacturer ships, describing the module's **services, communication, HMI, data objects, diagnostics/history, and alarms**. `[2658-1:2019][WG-2024]`

- **PEA = OPC UA *server*** (exposes services + data). **POL = OPC UA *client*/orchestrator.** `[2658-1:2019]`
- The MTP file is **AutomationML** (`IEC 62714`) built on **CAEX** (`IEC 62424`) — an XML "manifest" that is a table of contents pointing at aspect models. `[2658-1:2019]`
- A **service** on a PEA behaves as a standardized **16-state state machine** (PackML-lineage, ISA-88-aligned). The POL drives it by writing **commands** (Start/Stop/Hold/…) and reading back the **current state**. `[2658-4:2022][WG-2024]`
- **Recipes** are expressed in **ISA-88 / IEC 61512** terms (procedures → operations → phases) and commonly serialized as **BatchML/B2MML**. The POL translates recipe steps into service commands on the right PEAs. `[WG-2024][RWTH-POL-2025]`

```
        ┌────────────────────────── ERP / MES  (ISA-95 / IEC 62264) ────────────────────────┐
        │                                                                                    │
        ▼                                                                                    │
  ┌───────────────────────────── PROCESS ORCHESTRATION LAYER (POL) ───────────────────────┐ │
  │  Recipe engine (ISA-88 / BatchML)  ·  Service/state manager  ·  HMI aggregation        │ │
  │  MTP import & model  ·  PEA registry  ·  OPC UA client mgr  ·  Alarms  ·  Historian/log │ │
  └───────▲───────────────────────▲───────────────────────────▲───────────────────────────┘ │
          │ OPC UA (IEC 62541)     │                           │        ▲ MTP files (AML/CAEX) │
   ┌──────┴──────┐          ┌──────┴──────┐             ┌──────┴──────┐  └─── ships with each ─┘
   │   PEA #1    │          │   PEA #2    │     ...     │   PEA #n    │       PEA (per module)
   │ (OPC UA srv)│          │ (OPC UA srv)│             │ (OPC UA srv)│
   └─────────────┘          └─────────────┘             └─────────────┘
```

---

## 2. Terminology (verified definitions)

| Term | Definition | Source |
|---|---|---|
| **MTP** — Module Type Package | "The central module description and data exchange format. The MTP describes the module interfaces and functions needed for the integration in the POL." Modelled on AutomationML (`IEC 62714`). ⚠ ~~*role classes are deliberately not used*~~ — **false, struck 2026-08-08**; see the note below. | `[2658-1:2019]` (§7, quoted) |
| **PEA** — Process Equipment Assembly | A self-contained, encapsulated process module ("skid"), automated by its own PLC; dependencies between modules are minimized so modules protect themselves and their surroundings. Called a "module." | `[2658-1:2019]` |
| **POL** — Process Orchestration Layer | The superordinate system that "reads and controls the individual PEAs"; spans automation + IT level for operating a modular plant. Integrates each module's objects into a single unambiguous namespace. | `[2658-1:2019][WG-2024]` |
| **PFE / Process control** | The higher-level process-control function into which modules are integrated (the POL is its realization for modular plants). | `[2658-1:2019]` |
| **Service** | The unit of PEA functionality the POL orchestrates. Logic runs *on the PEA controller*, designed in advance, independent of the POL. In ISA-88 terms it is an **Equipment Procedural Element**. | `[2658-4:2022][WG-2024]` |
| **Service Procedure** | A selectable operating mode/variant of a service (parameterization). | `[2658-4:2022]` |
| **DataAssembly** | Standardized data object (sensor value, actuator, setpoint, interlock, etc.) — the reusable building block of a service interface. | `[2658-3][2658-4:2022]` |
| **FEA** — Functional Equipment Assembly | Sub-module hierarchy level from VDI 2776; *no direct interaction with the batch system/POL.* | `[WG-2024]` |

> **⚠ "role classes are deliberately not used" is FALSE — struck 2026-08-08.** It survived here as part of a
> *quoted* definition long after **§4.1 disproved it on 2026-07-16**, which made this table contradict the
> body of its own document — and the table is the part most likely to be quoted onward.
>
> **MTP does define and use RoleClasses:** `[2658-4:2022]` **Table 21** defines **`MissedValueFlag`** as
> `Type: RoleClass` in **`MTPServiceRCLib`**, attached via `SupportedRoleClass` and carrying a
> `MissedValue` BOOL — a RoleClass **with semantics**. Blatt 4 also defines `MTPTextRCLib`, and
> `[2658-1:2022]` §8.1 says outright that optional description components **are** modelled as RoleClasses.
>
> **The actionable rule — unchanged, and a different statement:** identify types via
> **`RefBaseSystemUnitPath`** / **`RefBaseClassPath`** / **`RefAttributeType`**, *never* via RoleClasses and
> never via element name. "Do not key on RoleClasses" ≠ "MTP has none." Full account: §4.1;
> `POL_MVP_and_Architecture.md` §5 struck the same claim on 2026-07-17.

---

## 3. The standards constellation (version table)

This is the landscape a POL sits in. **Currency flags** matter — read them.

### 3.1 The MTP core — VDI/VDE/NAMUR 2658 series

| Sheet (Blatt) | Scope | Version / status | Flag |
|---|---|---|---|
| **2658-1** | General concept & interfaces (manifest, OPC UA, modelling rules) | **Released 2019-10** = manifest **1.0.0** · **Draft 2022-01** = manifest **1.1.0** + `AttachmentSet` 1.0.0 | ✅ released (1.0.0) / ⚠ draft (1.1.0) |
| **2658-2** | Modelling of Human-Machine Interfaces (HMI) | **Released 2019-11** (draft 2018-01) | ✅ stable |
| **2658-3** | Library for data objects (DataAssemblies: sensors, actuators, setpoints, interlocks) | **Released 2020-09** (superseded 2019-03 draft) | ✅ stable |
| **2658-4** | Modelling of module services (service interface + **state machine**) | **Released 2022-10** | ✅ stable |
| **2658-5** | Runtime & communication aspects — **generic** (server profiles, connection setup). Defines **no** OPC UA classes (`OPCUAServer`/`OPCUAItem`/`Endpoint` = 0 occurrences). | **Draft 2022-04** | ⚠ draft · M2 (connection) |
| **2658-5.1** | **The OPC UA sub-part** — defines SUC `OPCUAServer` (+`Endpoint`, Table 32) and IC `OPCUAItem` (+`Identifier`/`Namespace`, Table 33). **`[2658-1:2022]` §9.1 delegates the concrete `ServerAssembly`/`DataItem` derivations here** → **required**, not merely informational. | **Draft 2022-10**; its own aspect model `2658-5.1:CommunicationSet` is **v0.1.0** | ⚠⚠ draft **and v0.1.0** — see §4.4 |
| **2658-6** | Concept of modular alarm management | **2021-01** (draft) | ⚠ draft |
| **2658-7** | Modelling of alarms and events (alarm data model + visualization; builds on Blatt 1 + 6) | **2021-02** (draft) | ⚠ draft |
| **IEC 63280** | International standardization of MTP | **In development** (MTP parts restructured to fold in "practically unchanged") | ⚠ emerging, *not* a published mirror |

> **MTP manifest/spec versioning:** the manifest carries a version — **V1.0.0**, **V1.1.0**, **V2.0.0** are the observed values. **1.1.0 = current stable baseline**; 2.0.0 = the new 2026 spec (§4.6). `[MTP-versions]`

### 3.2 Modular plant engineering — VDI 2776 (your local PDFs)

| Standard | Scope | Version | Flag |
|---|---|---|---|
| **VDI 2776-1** | Fundamentals & planning of modular plants ("Grundlagen und Planung") | **2020-11** | ✅ **acquired** — light background only |
| **VDI 2776-2** | Design of modular plants ("Design modularer Anlagen") | 2024-01 | ❌ not needed (plant design) |
| **VDI 2776-3** | Safety of modular plants | 2024-01 | ❌ not needed (safety is PEA-side) |

> ⚠ **These are the *plant-engineering* side, not the automation/MTP side.** 2776 governs how modular plants are conceived/designed/kept safe; 2658 (above) governs the automation interface a POL actually consumes. Don't conflate them. **Only Blatt 1 is kept** (as terminology/hierarchy background); -2 and -3 are out of the POL code path entirely.

### 3.3 Recipes, batch & vertical integration

| Standard | Scope | Version | Flag |
|---|---|---|---|
| **ISA-88 / IEC 61512** | Batch control: procedural + physical + process models; the recipe model | **Normative = DIN EN 61512-1:2000-01** (= IEC 61512-1:1997, MOD ISA-88.01:1995) — build/cite against this. **DIN EN IEC 61512-1:2023-11 = Ed. 2.0 DRAFT** (German mirror of IEC 65A/1045/CD:2022; 277 pp; restructured clauses, new conformance section, new Annex D procedural-state reference model) — **no normative force**; companion only. | ✅ **acquired** (both) — recipe-engine phase |
| **ISA-95 / IEC 62264** | Enterprise–control integration (MES/ERP ↔ plant) | IEC 62264 series | ❌ **out of scope** — MVP has no MES/ERP northbound |
| **B2MML / BatchML** | MESA XML serialization of ISA-88/95 (recipes exchanged as XML) | **V0700 (Nov 2020)** — supports 2018/19 ISA-95/IEC 62264 editions; adds first B2MML-JSON schema | ✅ free — fetch from web |

### 3.4 Communication & file format

| Standard | Scope | Version | Flag |
|---|---|---|---|
| **OPC UA / IEC 62541** | Runtime communication backbone (PEA server ↔ POL client) | IEC 62541 series | ✅ |
| **AutomationML / IEC 62714** | The MTP file format (XML) | IEC 62714 | ✅ |
| **CAEX / IEC 62424** | Object model underneath AutomationML | **CAEX 2.15** (= IEC 62424:2008) for MTP 1.x — *no* default namespace. CAEX 3.0 (IEC 62424:2016) adds the `http://www.dke.de/CAEX` namespace | ✅ (see §4.1) |

### 3.5 NAMUR recommendations & adjacent architecture

| Doc | Scope | Version | Flag |
|---|---|---|---|
| **NE 148** | Automation requirements from modularization ("Industrie 4.0" context) — the *why* behind MTP | **2013-10-22** (no later revision found) | ✅ |
| **NE 175** | **NOA** — NAMUR Open Architecture (second channel for monitoring/optimization data) | **2020-07-09** | ✅ adjacent |
| **IDTA 02001-1-0** | Submodel: inclusion of MTP data into the **Asset Administration Shell** (digital twin) | **2022** | ✅ future-facing |

### 3.6 Standards acquisition status (as of 2026-07-08)

The full minimal standards set for a v1 POL is now settled. **Paid standards are provided locally** (TU Dresden access) in
`../standards/` (the workspace-root `standards/` folder, per the workspace layout); **free standards will be fetched from the web** (thorough search, primary sources).

**🔒 Paid — ACQUIRED (local `../standards/` folder), bilingual DE/EN unless noted:**

| Standard | Edition (file) | Folder | Priority to process |
|---|---|---|---|
| VDI/VDE/NAMUR 2658 **Blatt 1** | 2019-10 (**released** = manifest 1.0.0) | `../standards/VDI-2658/` | ✅ read (§7.3–§7.6, Table 4, Annex A) |
| VDI/VDE/NAMUR 2658 **Blatt 1** | **2022-01 (draft) = manifest 1.1.0** | `../standards/VDI-2658/` | ⭐⭐ **Critical — our build target.** ✅ read (§2, §5, §8, §9, **§12**, §13); **§10, §11 + Annex still unread** *(§12 was read at M1 step 8 — it settled the `Pea` identification fields; see `002` §11)* |
| 2658 **Blatt 2** (HMI) | 2019-11 | `../standards/VDI-2658/` | **High** (HMI/faceplates) |
| 2658 **Blatt 3** (data objects) | 2020-09 | `../standards/VDI-2658/` | ⭐ **Critical** (parser / DataAssemblies) |
| 2658 **Blatt 4** (services) | 2022-10 | `../standards/VDI-2658/` | ⭐⭐ **Critical, process first** (state machine + command encoding) |
| 2658 **Blatt 5** (generic comms) | 2022-04 (draft) | `../standards/VDI-2658/` | **M2** — server profiles / connection setup. Defines no OPC UA classes. |
| 2658 **Blatt 5.1** (OPC UA) | 2022-10 (draft; aspect model **v0.1.0**) | `../standards/VDI-2658/` | ⭐ **Required, not informational** — `[2658-1:2022]` §9.1 delegates `OPCUAServer`/`OPCUAItem` here. ✅ read (§4, Tables 32/33). **But see §4.4: real files do not implement its v0.1.0 `Identifier` mechanism yet.** |
| 2658 **Blatt 6** (alarm concept) | 2021-01 (draft) | `../standards/VDI-2658/` | Later (alarms = v2) |
| 2658 **Blatt 7** (alarms & events) | 2021-02 (draft) | `../standards/VDI-2658/` | Later (alarms = v2) |
| **IEC 61512-1** (ISA-88) | DIN EN IEC 61512-1 2023-11 (+ DIN EN 61512-1 2000-01 DE) | `../standards/ISA-88 (IEC-61512-1)/` | **Medium** (recipe-engine phase) |
| **VDI 2776 Blatt 1** | 2020-11 | `../standards/VDI-2776/` | Background only |

**✅ Free — TO FETCH from the web (thorough, primary sources):**

| Standard | Source | Use |
|---|---|---|
| **AutomationML / IEC 62714** + **CAEX schemas** (`CAEX_ClassModel_V2.15.xsd`, V3.0) | automationml.org (AutomationML e.V.) / reference.opcfoundation.org (OPC 30040) | MTP file format + parser |
| **OPC UA / IEC 62541** (+ nodesets) | reference.opcfoundation.org / OPC Foundation GitHub | comms backbone |
| **B2MML / BatchML** (B2MML V0700, BatchML V0600) | github.com/MESAInternational/B2MML-BatchML | recipe XML schemas |

**❌ NOT needed / dropped:**
- **ISA-95 / IEC 62264** — no MES/ERP northbound in scope.
- **VDI 2776-2 / -3** — plant design & safety (safety is PEA-side).
- **IEC 61508 / 61511, VDI/VDE 2180 / 2182** — safety-instrumented & security; PEA/plant responsibility, not the POL orchestrator.
- **NE 148 / NE 175** — context/rationale only, not implementation.
- **IEC 63280** — not published. **MTP 2.0 full doc set** — new (2026-01), v2 concern.

---

## 4. MTP deep dive (the part a POL must implement)

### 4.1 The MTP file: AutomationML manifest as a table of contents

- The MTP is an **AutomationML** file (`IEC 62714`), which sits on **CAEX** (`IEC 62424`). `[2658-1:2019]`
- **⚠ CAEX version depends on the MTP *manifest* version — corrected 2026-07-16.** There are **two manifest
  versions in the wild, and they are different formats**, not namespace variants:
  - **Manifest 1.0.0** — `[2658-1:2019-10]`, **released**. Uses **CAEX 2.15** (`IEC 62424:2008`); the example AML
    declares `<CAEXFile SchemaVersion="2.15" xsi:noNamespaceSchemaLocation="CAEX_ClassModel_V2.15.xsd" …>` —
    note `noNamespaceSchemaLocation`, i.e. **no default CAEX namespace**. `[2658-1:2019]` (example)
  - **Manifest 1.1.0** — `[2658-1:2022-01]`, **Entwurf/draft**. Normatively references **IEC 62714 Ed. 2.0**
    (AutomationML 2.x) and **never mentions CAEX** → **CAEX 3.0**, `xmlns="http://www.dke.de/CAEX"`.
  - **The move to CAEX 3.0 happened at 1.1.0 — not at MTP 2.0** (the earlier "unconfirmed / check at 2.0" note
    was wrong). **Root cause, verified from both schemas:** `AttributeTypeLib` exists **only in CAEX 3.0** (0
    occurrences in the 2.15 schema; it is 3.0's 5th pillar). 1.1.0's binding needs `MTPATLib`, an
    AttributeTypeLib — so **1.1.0 physically cannot be expressed in CAEX 2.15**. Conversely `[2658-4:2022]` §9
    defines three AttributeType libraries (`MTPServiceATLib`, `MTPProcessValueATLib`, `MTPTextATLib`), so **the
    released Blatt 4:2022 itself presumes CAEX 3.0.**
  - **The differences are structural, not cosmetic** — a namespace-agnostic parser alone is **not** sufficient:

    | | Manifest 1.0.0 | Manifest 1.1.0 |
    |---|---|---|
    | Aspect table-of-contents | `ExternalDataConnector` + `refURI` | IC **`AspectSetReference`** + **`AspectRef`** → IH's GUID |
    | Dynamic binding | `AttributeDataType="xs:IDREF"` | AT **`IDLinkAttributeType`** (`AttributeDataType` stays `xs:string`) |
    | Object IDs | CAEX-optional string | **mandatory GUID** (RFC 4122) |

    A 1.0.0-based parser finds **zero aspects** in a 1.1.0 file. *(Verified in our own artifacts: HC30 has
    `AspectSetReference` ×5 / `refURI` ×0; MTPPy has the reverse.)* `[project-notes]`
  - Recipol's CAEX-3.0-only behaviour is therefore **not simply a bug** — it targets 1.1.0. Its real defect is
    **failing on 2.15/1.0.0 files**, which remains our regression test. `[project-notes]`
- AutomationML organizes a model into **InstanceHierarchies (IH)**. Each *aspect* of the module (services, HMI, communication…) gets its own IH. `[2658-1:2019]`
- The **Manifest** is the single IH named **`ModuleTypePackage`**. It acts as a *table of contents*: it holds exactly one `InternalElement` of type `ModuleTypePackage`, which references the other aspect IHs. Aspects can be added later without touching existing ones (extensibility by design). `[2658-1:2019]` (quoted)
- **⚠ "MTP does not use RoleClasses" was wrong — corrected 2026-07-16.** MTP **does** define and use RoleClasses:
  `[2658-4:2022]` **Table 21** defines **`MissedValueFlag`** as `Type: RoleClass` in **`MTPServiceRCLib`**,
  attached via `SupportedRoleClass` and carrying a `MissedValue` BOOL — i.e. a RoleClass **with semantics**.
  Blatt 4 also defines `MTPTextRCLib`. `[2658-1:2022]` §8.1 makes it explicit: optional description components
  **are** modelled as RoleClasses, and it must be stated whether they are `SupportedRoleClasses` or
  `RoleRequirements`. Blatt 1:2019's Annex A likewise emits
  `<SupportedRoleClass RefRoleClassPath="AutomationMLBaseRoleClassLib/AutomationMLBaseRole"/>`.
  → **The actionable rule is different, and still holds:** **identify types via `RefBaseSystemUnitPath`
  (InternalElement) / `RefBaseClassPath` (ExternalInterface) / `RefAttributeType` (Attribute) — never via
  RoleClasses, and never via element *name*** (names are explicitly free; only `ModuleTypePackage` is fixed).
- The **`Services` IH** describes functionality: `InternalElement`s of predefined classes — class **`Service`**
  for module services, and — **⚠ corrected 2026-07-16** — class **`Procedure`**, *not* `ServiceProcedure`, for
  the operating-mode variants. `[2658-4:2022]` **Table 30** names the SUC **`Procedure`** with
  `Hierarchy: MTPServiceSUCLib/Service` → the path a parser must match is
  **`MTPServiceSUCLib/Service/Procedure`**. **Root cause of the old error:** MTPPy emits `ServiceProcedure`
  because it is built to a **2658-4 v0.1.0 pre-release draft**; the real vendor file (HC30, ServiceSet 1.0.0)
  emits `Service/Procedure` and matches the standard. This doc had absorbed the **peer's draft** — exactly what
  `[MTPPy]` is labelled *illustrative, not authoritative* to prevent. `[2658-4:2022][project-notes]`
  *(Internal Python class naming remains a free choice; the **matched CAEX path** must be the standard's.)*
- **HMI** is a normal aspect: its own IH, reached from the manifest ToC via an `HMISet` entry (`MTPHMISUCLib/`
  classes — `Picture`, `VisualObject`, `TopologyObject`, `PortObject`, `Connection/Pipe`), so the POL can
  auto-generate **the module's own faceplate**. `[2658-2:2019]` §1 · *(observed in HC30: `2658-2:HmiSet` v1.0.0,
  IH `Pictures`)*
  - **⚠ Correction 2026-07-16:** this bullet previously claimed screen descriptions ship as exchangeable
    **`hmi.graphml`** files in the MTP folder structure, cited to `[2658-1:2019][2658-2]`. **Neither source
    supports it** — `graphml` occurs **0×** in Blatt 1 (both editions), 2, 3, 4, 5 and 5.1, and **0×** in a real
    vendor MTP (HC30). Claim removed as unsourced.
  - **Blatt 2 covers only the *static* side**: *"The objects and structures for the **dynamization** of HMIs are
    specified in **Part 3**"* (`[2658-2:2019]` §1). Symbols reach live data through the **`RefID` → DataAssembly**
    link — *"the dynamic symbol uses this to reference the associated DataAssembly instance"*. **The HMI aspect
    is therefore structurally downstream of the data/binding layer** and cannot precede it.
  - Scope note: Blatt 2 is *"HMI **for process modules**"* — the **per-module mimic**. A **plant-wide overview of
    all PEAs is not in any MTP**; that is the POL's own HMI to design. `[2658-2:2019]` §1

> **POL requirement:** parse an AML/CAEX file; locate the `ModuleTypePackage` IH; follow it to the `Services`, `Communication`, `HMI`, data-object, diagnostics/history, and alarm aspects; and build an internal model *without* relying on RoleClasses.

### 4.2 The aspects a manifest carries

Per `[2658-1:2019]` (§7.1, quoted list) the service-oriented core is surrounded by: **operating displays (HMI)**, **diagnosis**, **history**, **state models**, plus communication and data-object libraries. Safety (functional safety → DIN EN 61508/61511, VDI/VDE 2180) and security (VDI/VDE 2182) aspects are referenced but delegated to those standards. `[2658-1:2019]` (§6.6–6.7)

### 4.3 The service model & state machine — **verified from primary source**

Source: **Figure 4 "MTP State machine for Services (version 2022)"**, reproduced in the 2024 NAMUR/ISA/PNO joint WG position paper `[WG-2024]`, which cites **VDI/VDE/NAMUR 2658-4:2022** as its basis. Transcribed directly from the diagram (not from implementation code):

**16 states**, organized into 5 priority **layers** (higher layer = higher priority; e.g. Abort overrides Stop overrides Hold):

| Layer | Transient states (dashed) | Stable states (non-transient) |
|---|---|---|
| **1 — Execute / Pause** | STARTING, PAUSING, RESUMING, COMPLETING | IDLE *(initial)*, **EXECUTE**\*, PAUSED |
| **2 — Completed** | — | COMPLETED |
| **3 — Hold** | HOLDING, UNHOLDING | HELD |
| **(Reset)** | RESETTING | — |
| **4 — Stop** | STOPPING | STOPPED |
| **5 — Abort** | ABORTING | ABORTED |

\* **EXECUTE** is *non-transient for a continuous procedure* but *transient (self-terminating) for a batch/self-completing procedure*. `[WG-2024]`

**Commands** (arrows the POL can trigger — or that fire PEA-internally): **Start, Restart, Pause, Resume, Hold, Unhold, Complete, Stop, Abort, Reset.** Automatic transitions out of transient states are marked **"SC"** = *state change that is not controllable; occurs as soon as the previous state's functionality is processed.* `[WG-2024]`

**Transition map (key edges):**
- `IDLE --Start--> STARTING --SC--> EXECUTE`
- `EXECUTE --Complete--> COMPLETING --SC--> COMPLETED` (or self-completes)
- `EXECUTE --Pause--> PAUSING --SC--> PAUSED --Resume--> RESUMING --SC--> EXECUTE`
- `EXECUTE --Restart--> STARTING`
- `(any) --Hold--> HOLDING --SC--> HELD --Unhold--> UNHOLDING --SC--> EXECUTE`
- `(any) --Stop--> STOPPING --SC--> STOPPED`
- `(any) --Abort--> ABORTING --SC--> ABORTED`
- `COMPLETED / STOPPED / ABORTED --Reset--> RESETTING --SC--> IDLE`

**ISA-88 ↔ MTP naming** (Table 1 of `[WG-2024]`):

| ISA-88 | MTP |
|---|---|
| RUNNING | EXECUTE |
| COMPLETE | COMPLETED |
| UnHold / Restart | Unhold |
| *Not Used* | Restart |
| *Not Used* | Complete |

**For maximum ISA-88 compatibility**, the WG recommends: disable `Restart`; disable `Complete` and make services **self-completing**; provide all execution/completion parameters *before* EXECUTE; make `UNHOLDING` reuse `STARTING` logic; and use the PAUSING loop (not ISA-88 SUSPENDING) for pausing. `[WG-2024]`

**Control/status word encoding — VERIFIED from the normative standard** (`[2658-4:2022]` **Table 14**, "Coding of the control and status words of a service", read directly). `StateCur` and `Command` are **32-bit, bitwise, with exactly one bit set** (`CommandEn` may set several = all currently-allowed transitions). Undefined commands are **ignored and reset by the PEA**.

| `StateCur` (state) | Int | | `Command` | Int | | `CommandEn` bit |
|---|---|---|---|---|---|---|
| stopped | 4 | | reset | 2 | | ResetEnabled |
| starting | 8 | | start | 4 | | StartEnabled |
| idle | 16 | | stop | 8 | | StopEnabled |
| paused | 32 | | hold | 16 | | HoldEnabled |
| execute | 64 | | unhold | 32 | | UnholdEnabled |
| stopping | 128 | | pause | 64 | | PauseEnabled |
| aborting | 256 | | resume | 128 | | ResumeEnabled |
| aborted | 512 | | abort | 256 | | AbortEnabled |
| holding | 1024 | | restart | 512 | | RestartEnabled |
| held | 2048 | | complete | 1024 | | CompleteEnabled |
| unholding | 4096 | | | | | |
| pausing | 8192 | | *(bits 0–1, 11–31 reserved/not used)* | | | |
| resuming | 16384 | | | | | |
| resetting | 32768 | | | | | |
| completing | 65536 | | | | | |
| completed | 131072 | | | | | |

> ✅ This **confirms MTPPy's `state_codes.py` / `command_codes.py` are exactly the standard encoding** — but the authority is now Table 14, not the code. The command node the POL writes is `CommandOp`/`CommandExt`; the state it reads is `StateCur`; `CommandEn` tells the POL which commands are currently legal (drive button enable/disable from it). `[2658-4:2022]`

> **POL requirement:** implement this 16-state model as the canonical service lifecycle; expose Start/Stop/Hold/Unhold/Pause/Resume/Reset/Abort/Complete to the operator and recipe engine; and respect layer priority.

#### 4.3.1 Runtime control handshake — mode + procedure, *before* any command

> **Verified directly from `[2658-4:2022]`** — §6.2.1 (concept), §8.2.2.2–§8.2.2.5 + **Table 13** (service interface), **Table 2** (ServiceOperationMode), **Table 3** (ServiceSourceMode). This is the sequence a real PEA enforces *around* the state machine of §4.3. **Getting it wrong is the #1 integration failure mode** — a PEA silently ignores commands sent on the wrong channel.

**(1) Operation mode & source mode — the two mode DataAssemblies.** A service's control channel is gated by two nested mode state machines (`[2658-4:2022]` §6.2.1):
- **`ServiceOperationMode`** — modes **Offline / Operator / Automatic** (`[2658-4:2022]` §6.2.1.1, **Table 2**). Interaction is split into two channels selected by **`StateChannel`** (`0` = operator switches `*Op`, `1` = automatic switches `*Aut`). POL requests a mode by writing **`StateOpOp` / `StateAutOp` / `StateOffOp`** (operator channel: `0→1` = request, PEA acks `1→0`) or the `*Aut` equivalents. **Readback = `StateOpAct` / `StateAutAct` / `StateOffAct`** (current mode). Priority **Offline > Operator > Automatic**; a service may enter **Offline only in Idle**; a mode change does **not** cause a state change (`[2658-4:2022]` §6.2.1, p.7–9).
- **`ServiceSourceMode`** — used **only in Automatic**, selects **Internal / External** (`[2658-4:2022]` §6.2.1.2, **Table 3**). Channel selector **`SrcChannel`**; POL requests via **`SrcIntOp` / `SrcExtOp`** (or `*Aut`); **readback = `SrcIntAct` / `SrcExtAct`**. Priority **Internal > External**. Source mode is retained when Automatic is exited and resumed on re-entry.

**(2) The gating rule — which command node is honored in which mode** (`[2658-4:2022]` §8.2.2.3 + **Table 13**, p.30). Three command channels, exactly one honored at a time depending on mode:

| Command node | Honored **only when** | Purpose |
|---|---|---|
| **`CommandOp`** | `StateOpAct = true` (**Operator** mode) | manual / HMI |
| **`CommandInt`** | `StateAutAct = true` **and** `SrcIntAct = true` (**Automatic-Internal**) | PEA-internal logic |
| **`CommandExt`** | `StateAutAct = true` **and** `SrcExtAct = true` (**Automatic-External**) | **the POL / recipe** |

> ⚠ **A PEA ignores `CommandExt` unless it is in Automatic mode *and* External source.** The POL must therefore drive the mode handshake to **Automatic + External** (or use `CommandOp` in **Operator** mode) **before** writing any command — otherwise the write is silently dropped. Each command is one bit; the PEA resets `CommandOp`/`CommandExt` to 0 after interpreting it; a word with >1 bit set is ignored and cleared. (`[2658-4:2022]` §8.2.2.3.)

**(3) Procedure selection — before Start (IDLE→STARTING).** Procedures are chosen on the *same* channel logic as commands (`[2658-4:2022]` §8.2.2.4–§8.2.2.5 + **Table 13**):
- POL writes the desired `ProcedureID` to **`ProcedureExt`** (Automatic-External) — or `ProcedureOp` (Operator) / `ProcedureInt` (Auto-Internal). `0→ProcedureID` = request; PEA acks `ProcedureID→0` **when the service enters Starting**.
- **Readback `ProcedureReq`** = the currently *requested* procedure that will run at the next Start/Restart. **The POL confirms selection by reading `ProcedureReq` back** — only valid, service-defined IDs are accepted; an invalid ID or `0` sets `ProcedureReq = 0` (and ID `0` = "nothing selected → cannot start").
- **`ProcedureCur`** = the currently *active* procedure ID (`0` if none). On entry to **Starting**, `ProcedureReq → ProcedureCur` and the PEA resets `ProcedureOp`/`ProcedureExt` to 0.
- **Sequencing rule:** a service must have a valid non-zero procedure selected (confirmed via `ProcedureReq`) **before** `Start` is issued from IDLE; the ID latched into `ProcedureCur` at STARTING is what actually runs (`[2658-4:2022]` §8.2.2.5, p.35–36).

**(4) Node-layout note — "classic" vs "split" (Polaris regression).** The *normative* content of `[2658-4:2022]` **Table 2/Table 3/Table 13** is the **split set of individual BOOL variables** (`StateOpAct`, `StateAutAct`, `SrcExtAct`, `StateChannel`, `SrcChannel`, `StateOpOp`, …) — there is **no single combined "OpMode"/"SourceMode" scalar node in the standard**. Some tooling/peers additionally accept a **"classic" combined `OpMode`/`SourceMode`** aggregate node from earlier conventions; **Polaris supports both** layouts (and historically failed when a split-boolean MTP had *no* `OpMode` node). **Normative = the split-boolean variable set (Table 2/3/13); the combined node is a non-normative compatibility shim.** Our parser/OPC-UA layer must resolve the mode from the individual `*Act` booleans and **not require** a combined `OpMode` node. (`[2658-4:2022]` Table 2/3/13; `[project-notes]` for the Polaris behavior.)

> **POL handshake sequence (per service, verified):** ① switch `ServiceOperationMode` → **Automatic** (or **Operator**) and confirm via `StateAutAct`/`StateOpAct`; ② if Automatic, switch `ServiceSourceMode` → **External** and confirm via `SrcExtAct`; ③ write `ProcedureExt = ProcedureID` and confirm via `ProcedureReq`; ④ **only now** write `Start` on `CommandExt` (or `CommandOp`); ⑤ observe `StateCur`/`ProcedureCur`, drive button-enable from `CommandEn`.

### 4.4 Communication: OPC UA

- Modules integrate into the POL **via OPC UA** (`IEC 62541`); the PEA is the server. `[2658-1:2019]` (Fig. 2 "Example architecture for the integration of modules in a POL by means of OPC UA")
- The POL must place every module's objects into its own namespace **unambiguously** — e.g. by namespacing per module. `[2658-1:2019]`
- Each data point in the MTP references an OPC UA node; the manifest's communication aspect binds the abstract DataAssembly to a concrete server node (namespace + identifier). `[2658-1:2019][2658-5.1(draft)]`

> **⚠ Which document defines `OPCUAServer` / `OPCUAItem`? Verified 2026-07-16 — the answer is version-dependent.**
> - `[2658-1:2019]` (manifest 1.0.0) defines them **itself**: SUC `MTPCommunicationSUCLib/ServerAssembly/OPCUAServer`
>   with attribute `Endpoint`; IC `MTPCommunicationICLib/DataItem/OPCUAItem` with `Identifier` + `Namespace`
>   (Table 2) + `Access` (Table 1). **The identifier's *type* is encoded in the attribute's `AttributeDataType`**
>   — `xs:string` / `xs:integer` / `xs:base64binary` / `xs:ID` (Table 3).
> - `[2658-1:2022]` (manifest 1.1.0) **delegates** them: §9.1 says the concrete `DataItem`/`ObjectItem`/
>   `MethodItem` ICs and `ServerAssembly` SUCs "are to be introduced in further standard parts of **Blatt 5** by
>   derivation". Its own `ServerAssembly` (Table 12) is **abstract, with no attributes**.
> - **It is `[2658-5.1:2022]`, not Blatt 5**, that defines them: Table 32 `OPCUAServer` (+`Endpoint`) and
>   Table 33 `OPCUAItem` (+`Identifier`, `Namespace`). Blatt 5 (2022-04) is the *generic* part — it contains
>   **zero** occurrences of `OPCUAServer`/`OPCUAItem`/`Endpoint`.
> - **But Blatt 5.1's aspect model is `2658-5.1:CommunicationSet` version `0.1.0`** — the same pre-release
>   generation that made MTPPy's service model wrong — and its §4 still cites *"Part 1, Section 7.2"* (the 2019
>   numbering). **Table 33 changes the identifier mechanism**: the type would come from *an AT derived from
>   `OPCUABaseNodeIDType`*, not from `AttributeDataType`.
> - **Real files have not followed it.** Our 1.1.0 vendor export (HC30) declares **no 2658-5.x version at all**,
>   and its `OPCUAItem/Identifier` carries **no `RefAttributeType`** — its own description reads
>   *"IdentifierType (depends on AttributeDataType)"*, i.e. the **2019** mechanism. Table 32's
>   `OPCUAServer`/`Endpoint`, by contrast, matches HC30 exactly.
>
> **Stance:** implement the OPC UA item per **`[2658-1:2019]` Tables 1–3** (`Identifier` + `Namespace` +
> `Access`; identifier type from `AttributeDataType`) — that is what conformant 1.1.0 files actually emit.
> **Track Blatt 5.1 as the forward path; do not build to its v0.1.0 `OPCUABaseNodeIDType` mechanism yet.**
> Blatt 5's server profiles become relevant at **M2** (connection setup). `[2658-1:2022][2658-5.1][project-notes]`

> **Practical note (from this project's own integration work):** conformant POLs resolve namespaces **by URI**, not by numeric index — the OPC UA server must *register* a namespace URI, and the MTP must carry that URI (not a bare index). A reference impl that hard-codes a numeric namespace and omits registration will fail to bind in a real POL. This is an *implementation* lesson, consistent with the standard's "unambiguous namespace" requirement. `[project-notes]`

### 4.5 How the pieces nest (AML view)

```
CAEXFile  (CAEX 2.15 @1.0.0 | CAEX 3.0 @1.1.0)   ← AutomationML container (IEC 62714)
 ├─ InstanceHierarchy "ModuleTypePackage"        ← THE MANIFEST (fixed name; all other IH names are FREE)
 │   └─ InternalElement : MTPSUCLib/ModuleTypePackage      ← named for the PEA type
 │       ├─ InternalElement : MTPSUCLib/CommunicationSet   ← MANDATORY, exactly once, NO AspectSetReference
 │       │   ├─ InternalElement : .../SourceList    → ServerAssembly/OPCUAServer (Endpoint)
 │       │   │                                        └─ ExternalInterface : DataItem/OPCUAItem
 │       │   │                                             (Identifier + Namespace + Access)
 │       │   └─ InternalElement : .../InstanceList  → DataAssembly-derived IEs (RefID + bound attributes)
 │       └─ InternalElement : «MTPSet-derived»      ← optional aspects (ServiceSet, HMISet, …)
 │             └─ ExternalInterface → 1.1.0: MTPICLib/AspectSetReference (AspectRef → IH's GUID)
 │                                    1.0.0: ExternalDataConnector (refURI)
 ├─ InstanceHierarchy  (Services aspect — name free)
 │   ├─ InternalElement : MTPServiceSUCLib/Service          ← one per module service
 │   │   └─ InternalElement : MTPServiceSUCLib/Service/Procedure   ← operating modes/variants
 │   └─ ... ServiceParameter / ProcedureParameter / ReportValue (RefID → DataAssembly)
 ├─ InstanceHierarchy  (HMI aspect — MTPHMISUCLib: Picture, VisualObject, …)
 └─ InstanceHierarchy  (ProcessValues / Texts / Diagnosis / Alarms aspects)
```

> **Cross-aspect linking is by `RefID`, not by containment** (`[2658-1:2022]` §8.5 / `[2658-1:2019]` §7.4.4):
> every `LinkedObject`-derived IE carries a `RefID` GUID, and **IEs sharing a RefID are the same modelled
> entity**. That is how a `Service` in the Services IH reaches its `ServiceControl` DataAssembly in the
> Communication aspect — verified in HC30 (`Stirring`: Service and ServiceControl share
> `eafec7c5-508c-4e3f-94ab-8c9b3ccc78c6`).

> **Class-path note.** Types are matched via **`RefBaseSystemUnitPath`** (InternalElement) /
> **`RefBaseClassPath`** (ExternalInterface) / **`RefAttributeType`** (Attribute) — **never via RoleClasses,
> never via element names.**

### 4.6 MTP 2.0 — *newly published, do not build on yet*

- The **MTP Specification 2.0** consolidated document set was **officially published by PI (with NAMUR + ZVEI) on 2026-01-20**. `[MTP2.0]`
  - ⚠ *Timeline note:* "summer 2025" was the **announced target**, and it slipped; the actual official release came ~6 months later (Jan 2026). As of this writing it is only ~6 months old and **not yet widely implemented** — the "don't build on it yet" stance holds.
- Goals: **harmonize** the previously scattered MTP 1.x docs; **restructure** so parts can be adopted into **IEC 63280** almost unchanged; introduce a **profile-based approach** (reduces implementation, certification, and integration complexity); and remain **backward-compatible with MTP 1.0** (existing PEAs keep working with 2.0-based POLs). Scope broadened to hybrid (food/beverage, pharma) and pure production-automation applications. `[MTP2.0]`
- First **V2.0 Plugfest** ran in **October 2025** (six providers: 5 POL + 6 PEA implementations); certification test specs/tools are being provided. `[MTP2.0]`

> **Design stance for the new POL:** build to **MTP 1.1.0** now; keep the *aspect parser and service model modular* so a **profile layer** and a 2.0 manifest reader can be added later without a rewrite. Watch IEC 63280.

---

## 5. Orchestration & recipes (ISA-88 / IEC 61512)

The recipe side is where a POL earns its name. The **ISA-88 Procedural Control Model** (Procedures → Unit Procedures → Operations → Phases) sequences the **Equipment Entity Model** (Process Cells → Units → Equipment Modules → Control Modules). MTP maps onto this: the **POL orchestrates services**, and a **PEA supplies capability** — a PEA is typically an Equipment Module / Unit, and a **service is an Equipment Procedural Element** (Phase / Operation / Unit Procedure). `[WG-2024]`

- **Recipes as BatchML/B2MML:** a master recipe references procedural elements; the POL binds each recipe step to a PEA **service procedure** and drives its state machine. A 2025 approach executes **ISA-88 master recipes in BatchML** on a POL, aligning recipe content to the MTP files and translating steps into per-PEA OPC UA commands. `[RWTH-POL-2025]`
- **Capabilities / skills:** research trend — describe PEA services as *capabilities/skills* (ontology) so recipes can be matched to modules by *what they can do* rather than by hard-wired IDs. Enables automatic service selection. `[RWTH-POL-2025][skill-ontology-2022]`

> **POL requirement:** a recipe engine that (a) imports/authors ISA-88-structured recipes (BatchML friendly), (b) resolves each step to a concrete PEA + service procedure, (c) sends commands + evaluates transition conditions against live report values, and (d) advances the sequence. *This is exactly what a drag-and-drop recipe builder must produce under the hood.*

---

## 6. POL reference architecture (simplified — open-source scope)

Deliberately kept light. Each component maps to a standard it must honor:

| # | Component | Responsibility | Governed by |
|---|---|---|---|
| 1 | **MTP import & model** | Parse AML/CAEX (2.15 **and** 3.0 — see §4.1); build in-memory model of services, procedures, comm bindings, HMI, alarms. **Identify types by `RefBaseSystemUnitPath`/`RefBaseClassPath`/`RefAttributeType` — never by RoleClass, never by element name.** *(Was "No RoleClasses" — wrong; corrected 2026-07-16, see §4.1.)* | 2658-1/-4 (+**-5.1**), IEC 62714/62424 |
| 2 | **PEA registry** | Track known modules, their MTP, endpoint, and online status; assign unambiguous namespaces. | 2658-1 |
| 3 | **OPC UA connection manager** | Client sessions per PEA; resolve namespace **by URI**; subscribe to state/report nodes; write command nodes. | IEC 62541, 2658-5 |
| 4 | **Service / state manager** | Canonical 16-state machine per service; enforce layer priority; expose commands. | 2658-4 |
| 5 | **Recipe engine** | Author/import ISA-88 recipes (BatchML); bind steps → services; evaluate transitions; sequence. | ISA-88 / IEC 61512, B2MML |
| 6 | **HMI aggregation** | Render auto-generated module faceplates + a plant overview; live state/values; operator command surface. | 2658-2 |
| 7 | **Alarm manager** | Aggregate PEA alarms; acknowledge/shelve; plant-wide view. | 2658-6 (draft) |
| 8 | **Historian / logging** | Time-series of values, state transitions, operator actions, recipe execution (audit trail). | (NOA/NE 175 for 2nd-channel data) |
| 9 | **Northbound (optional)** | Hand recipe/status/KPIs up to MES/ERP. | ISA-95 / IEC 62264 |

**Architecture trend worth stealing:** research proposes **micro-frontends** for the POL HMI so each module contributes its own UI fragment into a composed operator view — directly relevant to your "nicer, intuitive HMI" goal. `[microfrontend-2021]`

---

## 7. Standards → POL requirements checklist

A conformance-oriented punch list for the build:

- [ ] **Read MTP 1.1.0** AML/CAEX manifests; follow `ModuleTypePackage` IH to all aspects; tolerate absence of RoleClasses. `[2658-1]`
- [ ] Build **service + service-procedure** model from the `Services` IH. `[2658-4]`
- [ ] Implement the **16-state service state machine** with layer priority + the 10 commands. `[2658-4][WG-2024]`
- [ ] **OPC UA client**: resolve namespaces **by URI**, subscribe to state/report values, write commands. `[IEC 62541][2658-5]`
- [ ] **ISA-88 recipe engine** with **BatchML** import/export; bind steps to service procedures; transition conditions on live values. `[ISA-88][RWTH-POL-2025]`
- [ ] **Auto-generate HMI faceplates** from the HMI aspect — its own IH of `MTPHMISUCLib` classes (`Picture`,
  `VisualObject`, `TopologyObject`, `PortObject`, `Connection`), reached from the manifest ToC via an `HMISet`
  entry. Symbols bind to live data by **`RefID` → DataAssembly**, so this **cannot precede M1/M2**. `[2658-2:2019]` §1
  *(Corrected 2026-07-17: this line previously said "`Picture` + `hmi.graphml`". **No such file exists** —
  `graphml` occurs 0× in Blatt 1 (both editions), 2, 3, 4, 5, 5.1 and 0× in a real vendor MTP. It was the last
  surviving copy of that unsourced claim, and the most dangerous: a checklist entry would have had someone build
  a reader for a format no standard defines.)*
- [ ] **Alarm aggregation** (design against 2658-6 draft; keep it swappable). `[2658-6]`
- [ ] **Historian + audit log** of values, transitions, operator/recipe actions.
- [ ] **Extensibility seam** for MTP 2.0 profiles + IEC 63280. `[MTP2.0]`
- [ ] Optional **ISA-95** northbound + **NOA** second channel + **AAS** submodel (`IDTA 02001`). `[NE175][IDTA]`

---

## 8. The ecosystem (what "better" is measured against)

**Commercial POLs (the bar for UX/robustness):**
- **Siemens SIMATIC PCS neo** — web-based DCS; v4.0 supports all released MTP parts. `[ecosystem]`
- **COPA-DATA zenon** — MTP suite; imports MTP → "Smart Object Templates" into a zenon POL. `[ecosystem]`
- **Semodia** — MTPlatform (management/validation/commissioning) + MTP-ControlEngine (C++ SDK implementing 2658 behavior on Linux/Windows/BSD) + MTP-Box. `[ecosystem]`
- **ABB System 800xA**, **Yokogawa CI Server**, **Honeywell**, **Rockwell**, **Beckhoff**, **Phoenix Contact (MTP Designer, PEA side)**. `[ecosystem]`

**Open-source references (this project's peers — useful, NEVER authoritative).**
**⚠ Peer standing re-assessed 2026-07-16 by measuring the MTP version each one's shipped artifact declares.**
This ranks them **as artifact sources**; Rule 1 is unchanged — *their code is never a source of truth.*

| Peer | Its shipped `.aml` declares | Standing for this project |
|---|---|---|
| **Recipol** — Python/PyQt6 POL; consumes AML + BatchML; resolves namespace by URI; drives the service state machine | **CAEX 3.0 · manifest 1.1.0 · `2658-4:ServiceSet` 1.0.0** (`2026-05-18-HC30_Stirring_V8.aml`, a real SIMATIC S7-1500 export) | ⭐ **The reference to go to.** Ships the **only** artifact on the current manifest **and** the **released** Blatt 4 service model → **our M1 fixture**. |
| **MTPPy** (TU Dresden) — PEA-side MTP generator + OPC UA server; legacy `opcua` lib | CAEX 2.15 · manifest 1.0.0 · **`2658-4` v0.1.0 (pre-release draft)** | **Outdated — no longer serves the build.** Its service model predates Blatt 4:2022 (see below). Kept **only** as the 2.15/1.0.0 regression fixture, and still accessible if needed. |
| **Polaris** — Node.js/TS + Angular POL + mtp-converter (Docker); resolves nodes by ns URI; supports classic + split op-mode | CAEX 2.15 · manifest 1.0.0 · **`2658-2`/`-3`/`-4` ALL v0.1.0** | **Most outdated of the three.** Reference/access only. |

**Why MTPPy's output no longer matches the standard** (it is built to the 2658-4 **v0.1.0** draft — these are
*measured* deviations from released `[2658-4:2022]`, and they are why this document previously carried the
`ServiceProcedure` error):

| MTPPy emits | `[2658-4:2022]` requires |
|---|---|
| `MTPSUCLib/ServicesSet` | `MTPServiceSUCLib/ServiceSet` (wrong library **and** name) |
| `MTPServiceSUCLib/ServiceProcedure` | `MTPServiceSUCLib/Service/Procedure` (Table 30) |
| `MTPDataObjectSUCLib/DataAssembly/ServiceControl` | `.../DataAssembly/**ServiceElement**/ServiceControl` (Table 13) |
| `.../DataAssembly/OperationElement/DIntServParam` | `.../DataAssembly/ServiceElement/ParameterElement/…` (Table 20) |

> **`visionforge.aml`** (in Recipol's tree) is **MTPPy-generated** (manifest 1.0.0 + 2658-4 v0.1.0) **and
> malformed**: it declares `SchemaVersion="3.0"` + `xmlns="http://www.dke.de/CAEX"` while pointing
> `noNamespaceSchemaLocation` at `CAEX_ClassModel_V2.15.xsd` — a 2.15 file with the 3.0 namespace injected.
> **Not used as an M1 fixture.** `[project-notes]`

> **The gap your project targets:** commercial POLs are capable but heavyweight/closed; the open-source ones are thin and rough (dev-grade UIs, brittle parsers). A modern **open-source POL with commercial-grade HMI + drag-and-drop recipes + solid logging** is a genuine, unfilled niche.

---

## 9. Adjacent & future-facing standards

- **NOA (NE 175)** — a *second, read-mostly channel* alongside the core control path for monitoring/optimization; MTP-compatible; pairs with Ethernet-APL. Good fit for the historian/analytics side of a POL. `[NE175]`
- **Ethernet-APL** — two-wire Ethernet to the field device (physical layer); expands what data a PEA can surface. Adjacent, not POL-internal.
- **PA-DIM** (Process Automation Device Information Model) — vendor-neutral OPC UA device information; complements MTP at the device level.
- **Asset Administration Shell (AAS)** + **IDTA 02001** — carry MTP data inside a standardized digital-twin submodel; relevant if the POL participates in Industrie 4.0 asset ecosystems. `[IDTA]`
- **Capability/Skill ontologies** — map MTP services to machine-readable capabilities for automatic recipe-to-module matching. `[skill-ontology-2022]`

---

## 10. Open questions / where the ground is still moving

*(Most earlier ⚠ flags now resolved — see §3 tables. Remaining live items:)*

1. **2658-5 / -6 / -7** are still drafts — runtime/comms and alarm details will firm up (and are folded into MTP 2.0). Design against them loosely. ⚠
2. **IEC 63280 publication status** — **still not published** as of mid-2026; IEC work restarted toward publishing MTP as IEC 63280. Track it; it will become the international citation. ⚠
3. **MTP 2.0 profiles** — once tooling/certification matures, decide which profile(s) the new POL targets. ⚠

**Resolved** (now hard facts in §3–§4): 2658-2 = 2019-11, 2658-3 = 2020-09, 2658-6 = 2021-01, 2658-7 = 2021-02; NE 148 = 2013-10-22, NE 175 = 2020-07-09; B2MML = V0700; VDI 2776-2/-3 = 2024-01; MTP 2.0 = published 2026-01-20; **CAEX 2.15 for MTP 1.x** (§4.1); **command/state encoding = 2658-4 Table 14, read directly** (§4.3) — no longer "verify vs MTPPy."

---

## 11. Recommendations for the new POL (design stance, non-binding)

1. **Target MTP 1.1.0**; isolate the manifest parser behind an interface so a 2.0/profile reader slots in later.
2. **Model the 16-state machine as a first-class domain object** (not scattered booleans) — it's the spine of both control and HMI.
3. **Resolve OPC UA namespaces by URI** from day one (the #1 interop failure in the open-source peers).
4. **Recipe engine ISA-88-native, BatchML on the wire** — so drag-and-drop authoring produces standards-clean recipes.
5. **HMI: compose per-module faceplates** (micro-frontend style) from the MTP HMI aspect + a plant overview; make state + alarms first-class.
6. **Log everything** (values, transitions, operator actions, recipe steps) — this is both audit (pharma/GMP) and the NOA analytics channel.
7. **Keep architecture flat and open** — 9 components (§6), clean OPC UA + AML boundaries, no hidden vendor coupling.

---

## 12. Bibliography & source-quality notes

**Primary standards / official (authoritative):**
- `[2658-1:2019]` VDI/VDE/NAMUR 2658 Blatt 1 (2019-10), *General concept and interfaces* — **full text read** (bilingual DE/EN). vdi.de / dinmedia.de. ✅ primary.
- `[2658-4:2022]` VDI/VDE/NAMUR 2658 Blatt 4 (2022-10), *Modelling of module services*. vdi.de / dinmedia.de. ✅ primary (state machine basis).
- `[2658-2]` Blatt 2 (HMI), released 2019-11 (draft 2018-01); `[2658-3]` Blatt 3 (data objects), released 2020-09 (draft 2019-03) — vdi.de / dinmedia.de. ✅ primary.
- `[2658-5(draft)]` Blatt 5 (2022-04 draft) + 5.1 (2022-10 draft), *Runtime & communication with OPC UA*. ⚠ draft.
- `[2658-6]` Blatt 6 (2021-01 draft), *Concept of modular alarm management*; `[2658-7]` Blatt 7 (2021-02 draft), *Modelling of alarms and events* — ⚠ draft.
- **IEC 61512-1 (ISA-88)** — normative text = **DIN EN 61512-1:2000-01** (= IEC 61512-1:1997, MOD ISA-88.01:1995); cite this. **DIN EN IEC 61512-1:2023-11 = Ed. 2.0 draft** (mirror of IEC 65A/1045/CD:2022, 277 pp) — **no normative force**; use its clause 7 + Annex D state models as a *companion* to `[WG-2024]` when designing the state machine, never as the valid standard. Both ✅ acquired locally. OPC UA / IEC 62541; AutomationML / IEC 62714; CAEX / IEC 62424; B2MML/BatchML — free, to fetch. ISA-95 / IEC 62264 — out of scope.
- **All paywalled standards above are now held locally** in `../standards/` (see §3.6). ✅

**Working-group / consortium (high authority, near-primary):**
- `[WG-2024]` NAMUR WG POSITION "State Model Alignment of ISA 88 and Module Type Package", 2024-09-09 (WG 2.3/2.12/2.4.2 + ISA-88 WG2 + PNO JWG MTP; managed by TU Dresden Process-to-Order Lab). **Figures 3–4 read directly** → verified 16-state machine + ISA-88 mapping. atpinfo.de. ✅ **key source.**
- `[MTP2.0]` PI press release "Module Type Package Specification 2.0" — **officially published 2026-01-20** (target had been summer 2025); first V2.0 plugfest Oct 2025. profibus.com / profinews.com / kem.industrie.de. ✅ current-status.
- `[MTP-versions]` MTP manifest V1.0.0/1.1.0/2.0.0 usage — IDTA submodel + implementation docs. ✅.
- `[IDTA]` IDTA 02001-1-0 (2022) *Inclusion of MTP Data into the Asset Administration Shell*. industrialdigitaltwin.org. ✅.
- `[NE175]` NAMUR NE 175 (NOA), **2020-07-09**; `[NE148]` NE 148, **2013-10-22** (no later revision) — namur.net. ✅.

**Peer-reviewed / academic:**
- `[RWTH-POL-2025]` "A POL for Modular Plants using Capabilities in Master Recipes", IFAC PapersOnLine 59-25 (2025) 89–94 (RWTH Aachen). POL executing ISA-88 master recipes in BatchML. ✅ (abstract-level).
- `[microfrontend-2021]` "MicroFrontends as Opportunity for POL Architecture in Modular Process Plants" (2021). ✅.
- `[skill-ontology-2022]` "A Mapping Approach to Convert MTPs into a Capability and Skill Ontology", arXiv 2205.01382 (2022). ✅.
- "Orchestration Requirements for Modular Process Plants" (Wiley CEAT, 2019). ✅ context.

**Vendor / trade (context only — lower authority):**
- `[ecosystem]` Rockwell, Yokogawa, Beckhoff, Phoenix Contact, COPA-DATA, Semodia, Siemens PCS neo product/blog pages; profibus.com/technologies/mtp; profinews.com. ⚠ marketing — used only for ecosystem/landscape claims.

**Implementation (illustrative, NOT authoritative):**
- `[MTPPy]` MTPPy (TU Dresden) source — relatively old open-source reference impl. Used only to illustrate; every spec claim cross-checked against 2658/WG papers.
- `[project-notes]` This project's own POL↔PEA integration findings (Recipol/Polaris/VisionForge) — empirical, consistent with 2658-1 namespace rules.

---

### Local standards library (`../standards/`)
Curated, minimal set held locally (TU Dresden access) — see §3.6 for the full table + process order:
- `../standards/VDI-2658/` — **Blatt 1–7 (+ 5.1)**, bilingual DE/EN. The MTP core. **Process Blatt 4 first**, then 3, then 2.
- `../standards/ISA-88 (IEC-61512-1)/` — **DIN EN 61512-1:2000-01 = the normative text** (= IEC 61512-1:1997, MOD ISA-88.01:1995), cite this; **DIN EN IEC 61512-1:2023-11 = Ed. 2.0 draft**, companion only (no normative force). Recipe/procedural model, for the recipe-engine phase.
- `../standards/VDI-2776/` — Blatt 1 (2020-11) only. Terminology/hierarchy background.

Free specs (AutomationML/IEC 62714 + CAEX schemas, OPC UA/IEC 62541, B2MML/BatchML) to be fetched from the web on demand.
*(Older uncurated copies also exist in `D:\ProjectDAAD\Standard_Namour_Documentation\` — VDI 2776-1/-2/-3; superseded by the curated set above for POL work.)*
