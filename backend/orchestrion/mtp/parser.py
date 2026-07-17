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
from orchestrion.mtp.model import Access, Endpoint, IdentifierType, OpcUaNode

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
