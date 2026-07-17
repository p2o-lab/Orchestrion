"""Walk an MTP's aspects and build the internal model — VDI/VDE/NAMUR 2658.

`caex.py` proves the file is a manifest 1.1.0 / CAEX 3.0 MTP and gives raw access;
this module turns its aspects into `model.py` objects. Nothing above this line sees
XML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from orchestrion.mtp import caex
from orchestrion.mtp.caex import INTERFACE_CLASS, MtpStructureError
from orchestrion.mtp.model import (
    Access,
    DataAssembly,
    Endpoint,
    IdentifierType,
    OpcUaNode,
    Pea,
    Service,
    ServiceProcedure,
)

# [2658-1:2022 Table 11 / Table 23] the CommunicationSet's two children.
SOURCE_LIST_CLASS = "MTPSUCLib/CommunicationSet/SourceList"
INSTANCE_LIST_CLASS = "MTPSUCLib/CommunicationSet/InstanceList"

# [2658-1:2022 Table 12] the abstract data source. Concrete ones are introduced by
# derivation in Blatt 5's sub-parts (Table 37 #14), so we match the *abstract* class
# and let the file's own library resolve the derivation.
SERVER_ASSEMBLY_CLASS = "MTPCommunicationSUCLib/ServerAssembly"

# [2658-1:2022 Table 14] the abstract information item; concrete ones likewise.
DATA_ITEM_CLASS = "MTPCommunicationICLib/DataItem"

# [2658-5.1 Table 32/33] the OPC UA derivations — the ones this POL speaks.
OPCUA_SERVER_CLASS = "MTPCommunicationSUCLib/ServerAssembly/OPCUAServer"
OPCUA_ITEM_CLASS = "MTPCommunicationICLib/DataItem/OPCUAItem"

# [2658-5.1 Table 32] the OPC UA server's endpoint URL.
ENDPOINT_ATTRIBUTE = "Endpoint"

# [2658-1:2019 Table 2] the OPC UA node's address; [Table 3] its type is carried by
# the Identifier attribute's AttributeDataType.
IDENTIFIER_ATTRIBUTE = "Identifier"
NAMESPACE_ATTRIBUTE = "Namespace"

# [2658-1:2022 Table 37 #16] a DataItem always carries Access; [Table 13] its values.
ACCESS_ATTRIBUTE = "Access"

# [2658-1:2022 Table 29] the abstract data object. Concrete data objects are IEs of
# classes *derived* from it ([Table 37 #19a]), and Blatt 3/4 supply those derivations
# (e.g. .../ServiceElement/ServiceControl), so this is matched by derivation.
DATA_ASSEMBLY_CLASS = "MTPDataObjectSUCLib/DataAssembly"

# ── The four attribute kinds a DataAssembly carries ───────────────────────────────
#
# Routing is on **RefAttributeType** — never on AttributeDataType (it is "xs:string"
# for *both* link kinds), never on "the value looks like a GUID" (both link kinds
# carry one). RefID and ID-link are indistinguishable by everything else and resolve
# in OPPOSITE directions, so the AT is the only honest discriminator.
#
# These rules name their AT ("has the AT X"), like [Table 36 #6]'s "of the SUC" — so
# they are matched **exactly**. Contrast [#9]/[#14]/[#15]'s "derived from", which are
# resolved through the class library by is_derived_from().

# [2658-1:2022 Table 8] every LinkedObject carries RefID — and [Table 29] makes
# DataAssembly derive from LinkedObject; [Table 9] is the AT that marks it.
# [Table 36 #4] IEs sharing a RefID GUID are one and the same modelled entity: this
# is a *shared identity*, NOT any element's ID. An ID-index lookup on it finds nothing.
REF_ID_ATTRIBUTE_TYPE = "MTPATLib/IDReferenceType/RefIDAttributeType"

# [2658-1:2022 §8.4 + Table 7 + Table 36 #3] the AT that marks an ID-link, whose
# value is the *ID of the referenced object*.
#
# ⚠ [Table 37 #19b/#19c] — the very rules this implements — call it
# "IDLinkReferenceType". **No such AttributeType is defined anywhere in the standard.**
# §8.4, Table 7 and Table 36 #3 all name IDLinkAttributeType, and conformant files
# emit it. Matching #19b's prose would bind ZERO nodes, silently.
ID_LINK_ATTRIBUTE_TYPE = "MTPATLib/IDReferenceType/IDLinkAttributeType"

# [2658-1:2022 Table 26] marks a multi-language string; [Table 29] gives DataAssembly
# exactly two of them.
MULTI_LANGUAGE_ATTRIBUTE_TYPE = "MTPATLib/MultiLanguageTextAttribute"
TAG_NAME_ATTRIBUTE = "TagName"
TAG_DESCRIPTION_ATTRIBUTE = "TagDescription"

# ── The service model — [2658-4:2022] ─────────────────────────────────────────────
#
# These classes are matched **exactly**, not by derivation, and that is the
# standard's own distinction: [2658-4:2022 Table 36] says "an IE **of the SUC**
# Service" (#2a) / "of the SUC Procedure" (#4a) / "of the SUC ServiceControl" (#2b),
# but says "an IE of a SUC **which is derived from** the SUC ParameterElement" where
# it means derivation (#3b/#5b/#6b). Blatt 4 uses both phrasings deliberately.

# [2658-4:2022 Table 27] the ServiceSet aspect's table-of-contents class. Optional:
# [2658-1:2022 Table 36 #9] makes only the CommunicationSet mandatory.
SERVICE_SET_CLASS = "MTPServiceSUCLib/ServiceSet"

# [2658-4:2022 Table 28] one per module service.
SERVICE_CLASS = "MTPServiceSUCLib/Service"

# [2658-4:2022 Table 30] the selectable variants of a service.
# The class is `Procedure` — *not* `ServiceProcedure`, which is MTPPy's v0.1.0-draft
# spelling and matches nothing in a conformant file. (Our Python class keeps the
# longer name; only this string has to be the standard's.)
PROCEDURE_CLASS = "MTPServiceSUCLib/Service/Procedure"

# [2658-4:2022 Table 13] the DataAssembly joined to each Service (Table 36 #2b);
# [Table 15] the one joined to each Procedure (Table 36 #4e).
SERVICE_CONTROL_CLASS = "MTPDataObjectSUCLib/DataAssembly/ServiceElement/ServiceControl"
PROCEDURE_HEALTH_VIEW_CLASS = (
    "MTPDataObjectSUCLib/DataAssembly/ServiceElement/ProcedureHealthView"
)

# [2658-4:2022 Table 30] the Procedure's own attributes.
PROCEDURE_ID_ATTRIBUTE = "ProcedureID"
IS_SELF_COMPLETING_ATTRIBUTE = "IsSelfCompleting"

# [2658-1:2022 Table 25] BOOL maps to xs:boolean, whose lexical space is exactly
# {true, false, 1, 0} — and is **case-sensitive**.
#
# ⚠ HC30 declares AttributeDataType="xs:boolean" and then writes "True"/"False",
# which are outside that space — the same vendor-casing deviation as Blatt 1:2019's
# Annex A writing "xs:Base64Binary" for Table 3's "xs:base64binary". We lower-case
# before lookup so real files can be read; anything not in this map still RAISES.
# Decision recorded in the open (user, 2026-07-17) — tolerated visibly, not silently.
#
# NEVER use bool(value) here: bool("False") is True, and the error would surface as a
# procedure that mysteriously self-completes.
_BOOLEAN = {"true": True, "1": True, "false": False, "0": False}

# [2658-4:2022 Table 30] ProcedureID is a DWORD → [2658-1:2022 Table 25] xs:unsignedInt.
_DWORD_MAX = 2**32 - 1


def read_mtp(path: Path) -> Pea:
    """Read an MTP `.aml` and return the PEA it describes.

    **The module's one public entry point.** Everything above (OPC UA client, state
    manager, API) takes a `Pea` and never sees XML, CAEX or a version.

    Raises `MtpVersionError` / `MtpStructureError` rather than returning a partial
    model: a silently tolerated non-conformant file is a guess, and a guess that
    happens to work is a defect (working agreement, Rule 1).
    """
    manifest = caex.load_manifest(path)
    root = manifest.element.getroottree().getroot()
    table_of_contents = caex.read_table_of_contents(path, root, manifest.element)

    # [2658-1:2022 Table 36 #9] the CommunicationSet is mandatory and exactly once —
    # read_table_of_contents has already enforced both, so this cannot be empty. It
    # is modelled inline, so its content is the entry's own element, not a hierarchy.
    communication = next(
        entry
        for entry in table_of_contents
        if entry.class_path == caex.COMMUNICATION_SET_CLASS
    )
    source_index = read_source_list(path, root, communication.element)
    assemblies = read_instance_list(path, root, communication.element, source_index)

    # [Table 36 #9] every other aspect is optional — a PEA that declares no services
    # is unusual but conformant, so an absent ServiceSet yields no services rather
    # than an error. Aspects are not stated to be unique either, so each contributes.
    services: list[Service] = []
    for entry in table_of_contents:
        if entry.class_path == SERVICE_SET_CLASS and entry.hierarchy is not None:
            services.extend(read_service_set(path, entry.hierarchy, assemblies))

    return Pea(
        type_name=manifest.pea_type_name,
        mtp_version=manifest.mtp_version,
        device_revision=manifest.device_revision,
        manufacturer_uri=manifest.manufacturer_uri,
        product_code=manifest.product_code,
        endpoints=source_index.endpoints,
        services=tuple(services),
    )


@dataclass(frozen=True)
class SourceIndex:
    """What the SourceList yields — [2658-1:2022] Table 37 #14–#16."""

    endpoints: tuple[Endpoint, ...]

    nodes: dict[str, OpcUaNode]
    """**ID → node**, the resolution target for every ID-link (Table 37 #19b): a
    DataAssembly attribute holds the *ID of the ExternalInterface*, and CAEX IDs are
    plain strings — no XML-native IDREF resolution exists, so this index is ours to
    build."""

    foreign_item_ids: frozenset[str]
    """IDs of DataItems belonging to communication technologies this POL does not
    speak.

    The standard anticipates several: [2658-1:2022] Table 37 #14 places concrete
    ServerAssemblies in "the communication-specific **sub-parts** of Blatt 5", and
    §9.1 makes DataItem/ObjectItem/MethodItem **abstract**, "introduced in further
    standard parts of Blatt 5 by derivation" — Blatt 5.1 being the OPC UA one.

    So a conformant PEA may expose a source this POL cannot speak. Tracking those
    items keeps a later ID-link to one recognisable as *not ours* (skip) rather than
    *dangling* (raise) — collapsing the two would reject a valid multi-protocol MTP.
    """


def read_source_list(
    path: Path, root: etree._Element, communication: etree._Element
) -> SourceIndex:
    """Read the CommunicationSet's SourceList."""
    source_list = _single_child_of_class(
        path, root, communication, SOURCE_LIST_CLASS, "SourceList"
    )

    endpoints: list[Endpoint] = []
    nodes: dict[str, OpcUaNode] = {}
    foreign: set[str] = set()

    for source in caex._children(source_list, "InternalElement"):
        class_path = source.get("RefBaseSystemUnitPath") or ""
        # [Table 37 #14] data sources are IEs derived from ServerAssembly.
        if not caex.is_derived_from(root, class_path, SERVER_ASSEMBLY_CLASS):
            continue

        # [Table 37 #14, §9.1] the standard admits several communication
        # technologies, each concretised in its own Blatt 5 sub-part. This POL is an
        # OPC UA client (plan §1), so other sources are skipped by design — they are
        # not malformed, just not ours. Strictness applies to conformance, not scope.
        is_opcua = caex.is_derived_from(root, class_path, OPCUA_SERVER_CLASS)
        if is_opcua:
            endpoints.append(_read_endpoint(path, source))
        _index_items(path, root, source, nodes, foreign, opcua=is_opcua)

    return SourceIndex(
        endpoints=tuple(endpoints), nodes=nodes, foreign_item_ids=frozenset(foreign)
    )


def _read_endpoint(path: Path, source: etree._Element) -> Endpoint:
    # [2658-5.1 Table 32] the OPCUAServer's Endpoint holds the URL the POL dials.
    url = caex.attribute_value(source, ENDPOINT_ATTRIBUTE)
    if not url:
        raise MtpStructureError(
            f"{path.name}: [2658-5.1 Table 32] OPC UA server "
            f"{source.get('Name')!r} has no {ENDPOINT_ATTRIBUTE!r} value"
        )
    return Endpoint(name=source.get("Name") or "", url=url)


def _index_items(
    path: Path,
    root: etree._Element,
    source: etree._Element,
    nodes: dict[str, OpcUaNode],
    foreign: set[str],
    *,
    opcua: bool,
) -> None:
    for interface in caex._children(source, "ExternalInterface"):
        class_path = interface.get("RefBaseClassPath") or ""
        # [Table 37 #15] information items are ExternalInterfaces derived from
        # the IC DataItem.
        if not caex.is_derived_from(root, class_path, DATA_ITEM_CLASS, INTERFACE_CLASS):
            continue

        item_id = interface.get("ID")
        if not item_id:
            # Without an ID nothing can ID-link to it (Table 37 #19b), so the item
            # is unreachable — a broken file, not a tolerable quirk.
            raise MtpStructureError(
                f"{path.name}: [2658-1:2022 Table 36 #1] data item "
                f"{interface.get('Name')!r} has no ID"
            )
        if item_id in nodes or item_id in foreign:
            raise MtpStructureError(
                f"{path.name}: duplicate ID {item_id!r} — ID-links (Table 37 #19b) "
                "would be ambiguous"
            )

        if opcua and caex.is_derived_from(
            root, class_path, OPCUA_ITEM_CLASS, INTERFACE_CLASS
        ):
            nodes[item_id] = _read_opcua_node(path, interface)
        else:
            foreign.add(item_id)


def _read_opcua_node(path: Path, interface: etree._Element) -> OpcUaNode:
    name = interface.get("Name")

    identifier_attribute = caex.find_attribute(interface, IDENTIFIER_ATTRIBUTE)
    if identifier_attribute is None:
        raise MtpStructureError(
            f"{path.name}: [2658-5.1 Table 33] OPC UA item {name!r} has no "
            f"{IDENTIFIER_ATTRIBUTE!r} attribute"
        )

    identifier = caex.attribute_value(interface, IDENTIFIER_ATTRIBUTE)
    if not identifier:
        raise MtpStructureError(
            f"{path.name}: [2658-5.1 Table 33] OPC UA item {name!r} has no "
            f"{IDENTIFIER_ATTRIBUTE!r} value"
        )

    # [2658-1:2019 Table 3] the identifier's *type* is the attribute's data type.
    # Unknown spellings raise rather than defaulting: guessing how to build a
    # NodeId would surface as an unresolvable node at M2, far from the cause.
    raw_type = identifier_attribute.get("AttributeDataType")
    try:
        identifier_type = IdentifierType(raw_type)
    except ValueError:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2019 Table 3] OPC UA item {name!r} declares "
            f"{IDENTIFIER_ATTRIBUTE} AttributeDataType={raw_type!r}, which is not one of "
            f"{[t.value for t in IdentifierType]}"
        ) from None

    namespace = caex.attribute_value(interface, NAMESPACE_ATTRIBUTE)
    if not namespace:
        raise MtpStructureError(
            f"{path.name}: [2658-5.1 Table 33] OPC UA item {name!r} has no "
            f"{NAMESPACE_ATTRIBUTE!r} value"
        )

    # [Table 37 #16] "a DataItem always carries Access"; [Table 13] its values.
    raw_access = caex.attribute_value(interface, ACCESS_ATTRIBUTE)
    if raw_access is None:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 37 #16] OPC UA item {name!r} has no "
            f"{ACCESS_ATTRIBUTE!r} attribute"
        )
    try:
        access = Access(int(raw_access))
    except ValueError:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 13] OPC UA item {name!r} declares "
            f"{ACCESS_ATTRIBUTE}={raw_access!r}, expected one of {[int(a) for a in Access]}"
        ) from None

    return OpcUaNode(
        namespace=namespace,
        identifier=identifier,
        identifier_type=identifier_type,
        access=access,
    )


def read_instance_list(
    path: Path,
    root: etree._Element,
    communication: etree._Element,
    source_index: SourceIndex,
) -> dict[str, DataAssembly]:
    """Read the CommunicationSet's InstanceList — [2658-1:2022] Table 37 #19a–#19f.

    Returns the data objects **keyed by RefID**: that is the identity other aspects
    join on ([Table 36 #4]), so it is how a Service will reach its ServiceControl.
    """
    # [Table 37 #13] the CommunicationSet has *exactly two* IEs. read_source_list()
    # enforces "exactly one SourceList" and _single_child_of_class below enforces
    # "exactly one InstanceList"; the "exactly two" bound can only be checked once
    # both are known, so it is checked here — the last of the two to be read.
    children = caex._children(communication, "InternalElement")
    if len(children) != 2:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 37 #13] the CommunicationSet must have exactly "
            f"two InternalElements (one SourceList, one InstanceList), found {len(children)}"
        )

    instance_list = _single_child_of_class(
        path, root, communication, INSTANCE_LIST_CLASS, "InstanceList"
    )

    assemblies: dict[str, DataAssembly] = {}
    for element in caex._children(instance_list, "InternalElement"):
        class_path = element.get("RefBaseSystemUnitPath") or ""
        # [#19a] data objects are IEs of a SUC derived from DataAssembly. Anything
        # else is not a data object — filtered, not rejected.
        if not caex.is_derived_from(root, class_path, DATA_ASSEMBLY_CLASS):
            continue

        assembly = _read_data_assembly(path, element, class_path, source_index)
        if assembly.ref_id in assemblies:
            # The result is keyed by RefID; a collision would silently drop a data
            # object. [Table 36 #4] would also make these one entity modelled twice.
            raise MtpStructureError(
                f"{path.name}: [2658-1:2022 Table 36 #4] duplicate RefID "
                f"{assembly.ref_id!r} in the InstanceList ({assembly.name!r})"
            )
        assemblies[assembly.ref_id] = assembly

    _check_tag_names_unique(path, assemblies)
    return assemblies


def _read_data_assembly(
    path: Path,
    element: etree._Element,
    class_path: str,
    source_index: SourceIndex,
) -> DataAssembly:
    """Turn one DataAssembly IE into the model object, routing on RefAttributeType."""
    name = element.get("Name") or ""

    ref_id: str | None = None
    tag_name: str | None = None
    tag_description: str | None = None
    nodes: dict[str, OpcUaNode] = {}
    constants: dict[str, str] = {}

    for attribute in caex._children(element, "Attribute"):
        attribute_name = attribute.get("Name") or ""
        attribute_type = attribute.get("RefAttributeType")
        values = caex._children(attribute, "Value")
        value = values[0].text if values else None

        if attribute_type == REF_ID_ATTRIBUTE_TYPE:
            # [Table 8 / Table 36 #4] the LinkedObject identity. Table 29 gives a
            # DataAssembly exactly one, so a second is ambiguous.
            if ref_id is not None:
                raise MtpStructureError(
                    f"{path.name}: [2658-1:2022 Table 8] data object {name!r} has more than "
                    "one RefID attribute — its identity would be ambiguous"
                )
            ref_id = value

        elif attribute_type == ID_LINK_ATTRIBUTE_TYPE:
            # [#19b] the value is the *ID* of a DataItem ExternalInterface.
            node = _resolve_id_link(path, name, attribute_name, value, source_index)
            if node is not None:
                nodes[attribute_name] = node

        elif attribute_type == MULTI_LANGUAGE_ATTRIBUTE_TYPE:
            # [#19f, Table 29] the base <Value> is the language-neutral text; the
            # per-language texts live in aml-lang={LangCode} children (Table 38 #20).
            if attribute_name == TAG_NAME_ATTRIBUTE:
                tag_name = value
            elif attribute_name == TAG_DESCRIPTION_ATTRIBUTE:
                tag_description = value

        elif attribute_type is None:
            # [#19e] no AT + a Value = a static value set in the MTP itself.
            # (An attribute with neither is not a value at all — e.g. Table 36 #8b's
            # empty WebServerUrl — so it is skipped rather than invented.)
            if value is not None:
                constants[attribute_name] = value

        # else: [#19a] "can be extended as required" — a vendor AT we do not model.
        # Skipped, never raised: an extension is conformant, just not ours.

    if not ref_id:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 8 / Table 36 #4] data object {name!r} "
            f"({class_path}) has no RefID — no aspect could reference it"
        )

    return DataAssembly(
        name=name,
        ref_id=ref_id,
        class_path=class_path,
        tag_name=tag_name,
        tag_description=tag_description,
        nodes=nodes,
        constants=constants,
    )


def _resolve_id_link(
    path: Path,
    assembly_name: str,
    attribute_name: str,
    value: str | None,
    source_index: SourceIndex,
) -> OpcUaNode | None:
    """Resolve an ID-link to its OPC UA node — [2658-1:2022] Table 37 #19b.

    Returns None when the link targets a communication technology this POL does not
    speak; raises when it targets nothing at all. Collapsing those two would reject
    valid multi-protocol MTPs (Table 37 #14, §9.1).
    """
    if not value:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 37 #19b] {assembly_name!r}.{attribute_name} "
            "is an ID-link with no value"
        )

    node = source_index.nodes.get(value)
    if node is not None:
        return node

    if value in source_index.foreign_item_ids:
        # A DataItem of another technology — not ours to read (plan §1).
        return None

    raise MtpStructureError(
        f"{path.name}: [2658-1:2022 Table 37 #19b] {assembly_name!r}.{attribute_name} "
        f"ID-links to {value!r}, which is no data item in the SourceList"
    )


def _check_tag_names_unique(path: Path, assemblies: dict[str, DataAssembly]) -> None:
    """[2658-1:2022 Table 37 #19f] TagName is unique within the InstanceList."""
    seen: dict[str, str] = {}
    for assembly in assemblies.values():
        if assembly.tag_name is None:
            continue
        if assembly.tag_name in seen:
            raise MtpStructureError(
                f"{path.name}: [2658-1:2022 Table 37 #19f] TagName {assembly.tag_name!r} is "
                f"not unique in the InstanceList ({seen[assembly.tag_name]!r} and "
                f"{assembly.name!r})"
            )
        seen[assembly.tag_name] = assembly.name


def read_service_set(
    path: Path,
    hierarchy: etree._Element,
    assemblies: dict[str, DataAssembly],
) -> tuple[Service, ...]:
    """Read the ServiceSet aspect — [2658-4:2022] Table 36.

    `hierarchy` is the InstanceHierarchy the manifest's ServiceSet entry points at
    (via its AspectRef); `assemblies` is the InstanceList keyed by RefID. The two are
    joined by the **LinkedObject concept** — a Service and its ServiceControl share a
    RefID while their element IDs differ ([2658-1:2022] Table 36 #4).

    Deliberately out of scope (Rule 4 — the M1 spine is services, procedures and
    comm bindings): ConfigurationParameters (#3), ProcedureParameters (#5),
    ReportValues (#6), ProcessValues (#7) and `Classification`/IRDI (#4d).
    """
    # [Table 36 #2a] within the IH, an IE of the SUC Service per service.
    return tuple(
        _read_service(path, element, assemblies)
        for element in caex._children(hierarchy, "InternalElement")
        if element.get("RefBaseSystemUnitPath") == SERVICE_CLASS
    )


def _read_service(
    path: Path, element: etree._Element, assemblies: dict[str, DataAssembly]
) -> Service:
    ref_id = _read_ref_id(path, element, "service")

    # [Table 36 #2b] a ServiceControl DataAssembly is attached to each Service by the
    # LinkedObject concept — i.e. it is the one sharing this RefID.
    control = _join_data_assembly(
        path, ref_id, assemblies, SERVICE_CONTROL_CLASS, "service", "#2b"
    )

    # [Table 36 #2c] "The name of the service corresponds to the TagName of the
    # referenced DataAssembly" — NOT the IE's own Name.
    if not control.tag_name:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 #2c] the ServiceControl of service "
            f"{element.get('Name')!r} has no TagName, which is the service's name"
        )

    # [Table 36 #4a] procedures are IEs of the SUC Procedure below the Service IE.
    procedures = tuple(
        _read_procedure(path, child, assemblies, control.tag_name)
        for child in caex._children(element, "InternalElement")
        if child.get("RefBaseSystemUnitPath") == PROCEDURE_CLASS
    )

    # [Table 36 #4g / §9.1.4] each service has at least one procedure.
    if not procedures:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 #4g] service {control.tag_name!r} has no "
            f"Procedure ({PROCEDURE_CLASS}); every service has at least one"
        )

    # [Table 36 #4c] the ProcedureID "shall be assigned uniquely within the service".
    seen: dict[int, str] = {}
    for procedure in procedures:
        if procedure.procedure_id in seen:
            raise MtpStructureError(
                f"{path.name}: [2658-4:2022 Table 36 #4c] ProcedureID "
                f"{procedure.procedure_id} is not unique within service "
                f"{control.tag_name!r} ({seen[procedure.procedure_id]!r} and "
                f"{procedure.name!r})"
            )
        seen[procedure.procedure_id] = procedure.name

    return Service(
        name=control.tag_name,
        ref_id=ref_id,
        procedures=procedures,
        control=control,
    )


def _read_procedure(
    path: Path,
    element: etree._Element,
    assemblies: dict[str, DataAssembly],
    service_name: str,
) -> ServiceProcedure:
    ref_id = _read_ref_id(path, element, "procedure")

    # [Table 36 #4e / §9.1.4] a ProcedureHealthView DataAssembly is attached to each
    # procedure by the LinkedObject concept.
    health_view = _join_data_assembly(
        path, ref_id, assemblies, PROCEDURE_HEALTH_VIEW_CLASS, "procedure", "#4e"
    )

    # [Table 36 #4f] the procedure's name is that DataAssembly's TagName.
    if not health_view.tag_name:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 #4f] the ProcedureHealthView of a procedure "
            f"of service {service_name!r} has no TagName, which is the procedure's name"
        )
    name = health_view.tag_name

    # [Table 36 #4c] "assigned uniquely within the service as a natural number in
    # decimal notation. The ID 0 may not be assigned. The largest possible ProcedureID
    # corresponds to the maximum value of a DWORD."
    raw_id = caex.attribute_value(element, PROCEDURE_ID_ATTRIBUTE)
    if raw_id is None:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 30] procedure {name!r} has no "
            f"{PROCEDURE_ID_ATTRIBUTE!r} value"
        )
    try:
        procedure_id = int(raw_id)
    except ValueError:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 #4c] procedure {name!r} has "
            f"{PROCEDURE_ID_ATTRIBUTE}={raw_id!r}, which is not a decimal natural number"
        ) from None
    if not 1 <= procedure_id <= _DWORD_MAX:
        # 0 is reserved: [2658-4:2022 §8.2.2.5] a ProcedureReq of 0 means "nothing
        # selected → cannot start", so a procedure with ID 0 could never be run.
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 #4c] procedure {name!r} has "
            f"{PROCEDURE_ID_ATTRIBUTE}={procedure_id}; it must be 1..{_DWORD_MAX} "
            "(0 may not be assigned)"
        )

    # [Table 36 #4b / Table 30] IsSelfCompleting — "true" if the service terminates
    # itself after successful execution. See _BOOLEAN for the casing divergence.
    raw_flag = caex.attribute_value(element, IS_SELF_COMPLETING_ATTRIBUTE)
    if raw_flag is None:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 30] procedure {name!r} has no "
            f"{IS_SELF_COMPLETING_ATTRIBUTE!r} value"
        )
    flag = _BOOLEAN.get(raw_flag.strip().lower())
    if flag is None:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 25] procedure {name!r} has "
            f"{IS_SELF_COMPLETING_ATTRIBUTE}={raw_flag!r}; BOOL maps to xs:boolean, "
            f"whose values are {sorted(_BOOLEAN)}"
        )

    return ServiceProcedure(
        name=name,
        ref_id=ref_id,
        procedure_id=procedure_id,
        is_self_completing=flag,
    )


def _join_data_assembly(
    path: Path,
    ref_id: str,
    assemblies: dict[str, DataAssembly],
    class_path: str,
    label: str,
    rule: str,
) -> DataAssembly:
    """Follow a LinkedObject RefID to its DataAssembly — [2658-1:2022] Table 36 #4.

    A **shared identity**, not an ID-link: the RefID is no element's ID, so this is a
    lookup in the RefID-keyed InstanceList and never in the SourceList's ID index.
    """
    assembly = assemblies.get(ref_id)
    if assembly is None:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 {rule}] the {label} with RefID {ref_id!r} "
            f"has no DataAssembly sharing that RefID in the InstanceList"
        )
    if assembly.class_path != class_path:
        raise MtpStructureError(
            f"{path.name}: [2658-4:2022 Table 36 {rule}] the {label} with RefID {ref_id!r} "
            f"joins a DataAssembly of {assembly.class_path!r}, expected {class_path!r}"
        )
    return assembly


def _read_ref_id(path: Path, element: etree._Element, label: str) -> str:
    """[2658-1:2022 Table 8 / Table 36 #4] a LinkedObject's shared-identity GUID."""
    for attribute in caex._children(element, "Attribute"):
        if attribute.get("RefAttributeType") != REF_ID_ATTRIBUTE_TYPE:
            continue
        values = caex._children(attribute, "Value")
        value = values[0].text if values else None
        if value:
            return value
    raise MtpStructureError(
        f"{path.name}: [2658-1:2022 Table 8] the {label} {element.get('Name')!r} has no "
        "RefID — it could not be joined to its DataAssembly"
    )


def _single_child_of_class(
    path: Path,
    root: etree._Element,
    parent: etree._Element,
    class_path: str,
    label: str,
) -> etree._Element:
    """[2658-1:2022 Table 37 #13] the CommunicationSet has exactly these two IEs."""
    matches = [
        ie
        for ie in caex._children(parent, "InternalElement")
        if caex.is_derived_from(root, ie.get("RefBaseSystemUnitPath") or "", class_path)
    ]
    if len(matches) != 1:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 37 #13] the CommunicationSet must have exactly "
            f"one {label} ({class_path}), found {len(matches)}"
        )
    return matches[0]
