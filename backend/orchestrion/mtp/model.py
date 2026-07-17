"""The internal MTP model — VDI/VDE/NAMUR 2658.

Plain data, no XML: `caex.py` and `parser.py` read AutomationML and produce these;
everything above (OPC UA client, state manager, API) consumes only these. That
boundary is what lets a second manifest version be added later without touching
the domain.

Class *names* here are ours; the CAEX class *paths* they are parsed from are the
standard's and must match exactly — see ServiceProcedure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Access(IntEnum):
    """Access rights of a data item — [2658-1:2022] Table 13.

    The 2019 edition's Table 1 omitted 0 while its own Annex A example used it;
    the 2022 edition formalises 0.
    """

    NONE = 0
    READ = 1
    WRITE = 2
    READ_WRITE = 3


class IdentifierType(str, Enum):
    """How an OPC UA node identifier is encoded — [2658-1:2019] **Table 3**.

    The members' values are the standard's own: each is the literal
    `AttributeDataType` that the `Identifier` attribute carries, so the enum maps
    straight off the file with nothing invented in between. Needed to build the
    NodeId in M2.

    ⚠ Blatt 1:2019 contradicts itself here. **Table 3 (normative) says
    `xs:integer` and `xs:base64binary`**; its own Annex A example writes `xs:int`
    and `xs:Base64Binary`, and HC30 copies the Annex's wording. The standard
    decides — these are Table 3's spellings. Real files may carry the Annex's, and
    that has to be handled where Identifier is actually read (step 5+), not by
    quietly widening the enum here.

    (Blatt 5.1 v0.1.0 would replace this mechanism with an AttributeType derived
    from OPCUABaseNodeIDType; no real file does that yet — see 002 §6.4.)
    """

    STRING = "xs:string"
    """[Table 3] identification by character string."""

    NUMERIC = "xs:integer"
    """[Table 3] identification by enumeration in the OPC UA server."""

    BYTE_ARRAY = "xs:base64binary"
    """[Table 3] identification by byte array."""

    GUID = "xs:ID"
    """[Table 3] identification by GUID."""


@dataclass(frozen=True)
class OpcUaNode:
    """One OPC UA access point — [2658-1:2019] Tables 1–3; [2658-5.1] Table 33.

    Parsed from an ExternalInterface of MTPCommunicationICLib/DataItem/OPCUAItem.
    """

    namespace: str
    """The namespace the node lives in. A **URI** — resolved against the live
    server's index at connect time, never used as an index itself."""

    identifier: str
    """The node identifier, e.g. `"ProcessValues_DB"."MTPBinaryOut"[0]."VState1"`."""

    identifier_type: IdentifierType
    """[Table 3] how `identifier` is encoded; decides the NodeId built in M2."""

    access: Access


@dataclass(frozen=True)
class Endpoint:
    """A PEA data source — [2658-5.1] Table 32 (SUC OPCUAServer).

    In manifest 1.1.0 the concrete OPCUAServer is delegated to Blatt 5.1; the
    class path and `Endpoint` attribute are unchanged from [2658-1:2019].
    """

    name: str
    url: str
    """e.g. `opc.tcp://134.130.125.142:4840`."""


@dataclass(frozen=True)
class DataAssembly:
    """A data object — [2658-1:2022] Table 29; [2658-3:2020] Table 22.

    Lives in the CommunicationSet's InstanceList. Its attributes are either static
    (a literal value) or dynamic (an ID-link to a DataItem) — [2658-1:2022] §9.2.1
    and §9.2.2.
    """

    name: str
    ref_id: str
    """[Table 36 #4] the LinkedObject GUID. Elements sharing a ref_id are one and
    the same modelled entity — this is how an aspect reaches its data object."""

    class_path: str
    """The `RefBaseSystemUnitPath`, e.g.
    `MTPDataObjectSUCLib/DataAssembly/ServiceElement/ServiceControl`. Kept verbatim
    so the standards-facing identity of the object is never lost in translation."""

    tag_name: str | None
    """[Table 29] `TagName`. In 1.1.0 this is a multi-language attribute; this is
    the base value, not the per-language children."""

    tag_description: str | None

    nodes: dict[str, OpcUaNode]
    """Dynamic attributes: attribute name → its OPC UA access point. For a
    ServiceControl this is where `StateCur`, `CommandExt`, `ProcedureReq` … live."""

    constants: dict[str, str]
    """Static attributes: attribute name → literal value (§9.2.1)."""


@dataclass(frozen=True)
class ServiceProcedure:
    """A selectable variant of a service.

    **Naming:** the CAEX class is `MTPServiceSUCLib/Service/Procedure`
    ([2658-4:2022] Table 30) — *not* `ServiceProcedure`, which is MTPPy's
    v0.1.0-draft spelling and matches nothing in a conformant file. The Python name
    here is a free internal choice; the parsed path is not.
    """

    name: str
    ref_id: str

    procedure_id: int
    """[Table 30] `ProcedureID` (DWORD). Written to `ProcedureExt`/`ProcedureOp` to
    select this procedure, and read back via `ProcedureReq` before Start (M3)."""

    is_self_completing: bool
    """[Table 30] `IsSelfCompleting`. A self-completing procedure leaves EXECUTE on
    its own; a non-self-completing one needs an explicit `Complete`."""


@dataclass(frozen=True)
class Service:
    """A unit of PEA functionality — [2658-4:2022] Table 28.

    Derived from LinkedObject, so it carries a `ref_id` and reaches its control
    interface by matching GUIDs rather than by containment.
    """

    name: str
    ref_id: str

    procedures: tuple[ServiceProcedure, ...]
    """[2658-4:2022] §9.1.4: every service has at least one."""

    control: DataAssembly | None
    """The `ServiceControl` DataAssembly sharing this service's `ref_id`
    ([2658-4:2022] Table 13). `None` only if the file omits it — which a
    conformant 1.1.0 file does not, but MTPPy's draft-era output can."""


@dataclass(frozen=True)
class Pea:
    """A process equipment assembly, as described by one MTP.

    The manifest's entry point — [2658-1:2022] §8.2, Table 2.
    """

    type_name: str
    """[Table 36 #6] the ModuleTypePackage IE's Name. Vendors may leave this a
    placeholder ("No Information" in our HC30 fixture); the standard requires it
    filled, not meaningful."""

    mtp_version: str
    """[Table 36 #7a] the MTP *instance* version — the vendor's file revision.
    Not the manifest aspect model version (1.1.0)."""

    endpoints: tuple[Endpoint, ...]
    services: tuple[Service, ...]
