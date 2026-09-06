"""CAEX/AutomationML access for MTP files — VDI/VDE/NAMUR 2658.

Scope: **manifest 1.1.0 / CAEX 3.0 only**. Anything else is rejected rather than
parsed on a best effort: a silently tolerated non-conformant file yields a guess,
and a guess that happens to work is a defect.

Note the schema permits more than the MTP does — e.g. CAEX makes
``RefBaseSystemUnitPath`` optional while [2658-1:2022] Table 36 requires the types.
A file can therefore be schema-valid and still not be an MTP. Every rule enforced
here cites the clause it comes from, so anyone holding the standards can follow the
implementation back to the text it was written from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

# [2658-1:2022 Table 36 #1] "all IDs of AutomationML objects are to be implemented
# in the form of a GUID according to RFC4122" — RFC 4122 §3's canonical string
# representation, i.e. 8-4-4-4-12 hex digits.
_GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# [2658-1:2022 §5 Table 1] the manifest aspect model this parser implements.
MANIFEST_DOCUMENT_ID = "VDI/VDE/NAMUR 2658-1:Manifest"
MANIFEST_VERSION = "1.1.0"

# Manifest 1.1.0 is modelled on AutomationML per IEC 62714 Ed. 2.0, i.e. CAEX 3.0.
# [CAEX_ClassModel_V.3.0.xsd] CAEXFile/@SchemaVersion is required.
CAEX_SCHEMA_VERSION = "3.0"

# [2658-1:2022 Table 36 #5] the manifest IH always carries this name. Every other
# InstanceHierarchy name is free (§8.1), so this is the only name worth matching.
MANIFEST_IH_NAME = "ModuleTypePackage"

# [2658-1:2022 Table 36 #6, Table 2] the single entry-point IE's SystemUnitClass.
MODULE_TYPE_PACKAGE_CLASS = "MTPSUCLib/ModuleTypePackage"

# [2658-1:2022 Table 36 #7a] The four offline attributes required on that IE for
# type/version conformity verification. All xs:string; Version and DeviceRevision
# are Major.Minor.Patch.
#
# The standard contradicts itself on one spelling: rule #7a's prose says
# "ManufacturerURI", while Table 2 — the model definition that actually declares
# the class's attributes — says "ManufacturerUri". Table 2 governs the attribute
# name (and the real vendor file follows it), so that is what is matched.
VERSION_ATTRIBUTE = "Version"
DEVICE_REVISION_ATTRIBUTE = "DeviceRevision"
MANUFACTURER_URI_ATTRIBUTE = "ManufacturerUri"
PRODUCT_CODE_ATTRIBUTE = "ProductCode"

IDENTIFICATION_ATTRIBUTES = (
    VERSION_ATTRIBUTE,
    DEVICE_REVISION_ATTRIBUTE,
    MANUFACTURER_URI_ATTRIBUTE,
    PRODUCT_CODE_ATTRIBUTE,
)

# [2658-1:2022 Table 3] the abstract parent of every table-of-contents entry.
MTP_SET_CLASS = "MTPSUCLib/MTPSet"

# [2658-1:2022 Table 10] mandatory, exactly once, and modelled inline — it is the
# one MTPSet-derived entry that carries no AspectSetReference (§8.3, Figure 3).
COMMUNICATION_SET_CLASS = "MTPSUCLib/CommunicationSet"

# [2658-1:2022 Table 4] the IC on an optional aspect entry, and its attribute,
# whose value is the GUID of the InstanceHierarchy implementing that aspect.
ASPECT_SET_REFERENCE_CLASS = "MTPICLib/AspectSetReference"
ASPECT_REF_ATTRIBUTE = "AspectRef"


class MtpError(Exception):
    """The file is not an MTP this parser can read."""


class MtpVersionError(MtpError):
    """The file is not manifest 1.1.0 / CAEX 3.0."""


class MtpStructureError(MtpError):
    """The file violates a modelling rule of [2658-1:2022]."""


def _children(element: etree._Element, local_name: str) -> list[etree._Element]:
    """Child elements with this local name, ignoring XML namespace.

    CAEX 2.15 declares no namespace; CAEX 3.0 declares http://www.dke.de/CAEX.
    Matching on local-name() reads both, so a namespace change never silently
    yields an empty result.
    """
    return element.xpath("./*[local-name()=$n]", n=local_name)


def _descendants(element: etree._Element, local_name: str) -> list[etree._Element]:
    return element.xpath(".//*[local-name()=$n]", n=local_name)


def find_attribute(element: etree._Element, name: str) -> etree._Element | None:
    """The CAEX <Attribute Name="..."> child itself.

    Callers need the element rather than its text because an attribute's *meaning*
    is carried by its `RefAttributeType` (whether it is an ID-link, a RefID, a
    multi-language text, or a static value) and its data type by
    `AttributeDataType` — neither of which is visible in <Value>.
    """
    for attribute in _children(element, "Attribute"):
        if attribute.get("Name") == name:
            return attribute
    return None


def attribute_value(element: etree._Element, name: str) -> str | None:
    """Text of the CAEX <Attribute Name="..."><Value>…</Value></Attribute>."""
    attribute = find_attribute(element, name)
    if attribute is None:
        return None
    values = _children(attribute, "Value")
    return values[0].text if values else None


# Kept as a private alias: this module's own call sites read better unqualified.
_attribute_value = attribute_value


# CAEX declares SystemUnitClasses and InterfaceClasses in parallel libraries with
# identical shape: a *Lib element containing nested *Class elements, each pointing
# at its parent with RefBaseClassPath. The rules use both — Table 36 #9 asks about
# SUC derivation ("derived from MTPSet"), Table 37 #15 about IC derivation
# ("derived from the IC DataItem") — so the resolver is parameterised, not copied.
SYSTEM_UNIT_CLASS = ("SystemUnitClassLib", "SystemUnitClass")
INTERFACE_CLASS = ("InterfaceClassLib", "InterfaceClass")

ClassKind = tuple[str, str]


def find_class(
    root: etree._Element, class_path: str, kind: ClassKind = SYSTEM_UNIT_CLASS
) -> etree._Element | None:
    """Locate a class by its library path.

    Paths address a library then a nesting of classes, e.g.
    ``MTPSUCLib/CommunicationSet/SourceList`` — SourceList is declared *inside*
    CommunicationSet, so the path is walked segment by segment rather than matched
    as a string. The same holds for ICs: ``MTPCommunicationICLib/DataItem/OPCUAItem``.
    """
    library_tag, class_tag = kind
    library_name, *class_names = class_path.split("/")

    libraries = [
        lib for lib in _children(root, library_tag) if lib.get("Name") == library_name
    ]
    if not libraries:
        return None

    node = libraries[0]
    for name in class_names:
        matches = [c for c in _children(node, class_tag) if c.get("Name") == name]
        if not matches:
            return None
        node = matches[0]
    return node


def class_ancestry(
    root: etree._Element, class_path: str, kind: ClassKind = SYSTEM_UNIT_CLASS
) -> list[str]:
    """The derivation chain of a class, nearest first, including itself.

    e.g. ``MTPServiceSUCLib/ServiceSet`` → ``[MTPServiceSUCLib/ServiceSet,
    MTPSUCLib/MTPSet]``, by following each class's ``RefBaseClassPath``.

    [2658-1:2022 §8.1] every aspect declares its own libraries in the file, so
    derivation is answerable from the file itself — no knowledge of which aspects
    exist has to be hardcoded. The chain simply stops at a class the file does not
    declare.
    """
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = class_path

    while current and current not in seen:
        seen.add(current)
        chain.append(current)
        element = find_class(root, current, kind)
        if element is None:
            break
        current = element.get("RefBaseClassPath")

    return chain


def is_derived_from(
    root: etree._Element,
    class_path: str,
    ancestor: str,
    kind: ClassKind = SYSTEM_UNIT_CLASS,
) -> bool:
    """Whether `class_path` is `ancestor` or derives from it.

    This answers the standard's "derived from" rules — Table 36 #9 (SUCs derived
    from MTPSet), Table 37 #14/#15 (SUCs derived from ServerAssembly, ICs derived
    from DataItem). Those rules are deliberately open-ended — concrete classes are
    introduced by *other* parts of the standard (Blatt 5.1 adds OPCUAServer and
    OPCUAItem by derivation) — so matching a fixed list of known class names would
    silently drop what the file legitimately declares.
    """
    return ancestor in class_ancestry(root, class_path, kind)


@dataclass(frozen=True)
class Manifest:
    """The manifest's entry point — [2658-1:2022] §8.2."""

    pea_type_name: str
    """[Table 36 #6] the IE's Name, which carries the name of the PEA type."""

    mtp_version: str
    """[Table 36 #7a] the MTP instance version, Major.Minor.Patch."""

    device_revision: str
    """[Table 36 #7a] Major.Minor.Patch."""

    manufacturer_uri: str
    """[Table 36 #7a / Table 2] — Table 2's spelling; see IDENTIFICATION_ATTRIBUTES."""

    product_code: str
    """[Table 36 #7a]."""

    element: etree._Element
    """The ModuleTypePackage IE — the root the aspect walk starts from."""


def load_manifest(path: Path) -> Manifest:
    """Open an MTP `.aml` and return its manifest entry point.

    Raises MtpVersionError / MtpStructureError rather than returning a partial
    result: callers may assume a returned Manifest is conformant to the rules
    checked here.
    """
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        raise MtpStructureError(f"{path.name}: not well-formed XML: {exc}") from exc

    root = tree.getroot()
    if etree.QName(root).localname != "CAEXFile":
        raise MtpStructureError(
            f"{path.name}: root element is {etree.QName(root).localname!r}, expected 'CAEXFile'"
        )

    _check_versions(path, root)
    _check_ids_are_guids(path, root)
    module = _find_module_type_package(path, root)

    # [Table 36 #7a] all four are required, not just Version.
    #
    # #7a imposes a SECOND requirement we deliberately do NOT enforce: "Version
    # and DeviceRevision shall be specified in the format Major.Minor.Patch"
    # (restated in Table 2). Our HC30 fixture violates it — DeviceRevision is the
    # literal "No Information" — so enforcing it would reject the only conformant
    # 1.1.0 artifact we have.
    #
    # This is a conscious, recorded exception to the fail-hard rule, not an
    # oversight. Note it does NOT follow
    # from the "#6 requires a Name, not a meaningful one" argument: #6 imposes no
    # format, #7a imposes a checkable one, so "No Information" is format-violating
    # rather than merely lazy. Revisit if a fixture with conformant values appears;
    # §12 PEA verification cannot work against this file either way.
    identification: dict[str, str] = {}
    for name in IDENTIFICATION_ATTRIBUTES:
        value = _attribute_value(module, name)
        if value is None:
            raise MtpStructureError(
                f"{path.name}: [2658-1:2022 Table 36 #7a] the ModuleTypePackage element has no "
                f"{name!r} attribute. All four of {list(IDENTIFICATION_ATTRIBUTES)} are required."
            )
        identification[name] = value

    pea_type_name = module.get("Name")
    if not pea_type_name:
        # CAEX requires Name on every CAEXObject; Table 36 #6 gives it meaning.
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #6] the ModuleTypePackage element has no Name "
            "(it must carry the PEA type name)"
        )

    return Manifest(
        pea_type_name=pea_type_name,
        mtp_version=identification[VERSION_ATTRIBUTE],
        device_revision=identification[DEVICE_REVISION_ATTRIBUTE],
        manufacturer_uri=identification[MANUFACTURER_URI_ATTRIBUTE],
        product_code=identification[PRODUCT_CODE_ATTRIBUTE],
        element=module,
    )


@dataclass(frozen=True)
class AspectEntry:
    """One entry in the manifest's table of contents — [2658-1:2022] §8.3.

    An IE under ModuleTypePackage whose class derives from MTPSet. Its *name* is
    free (Table 36 #9); its class and its AspectRef carry the meaning.
    """

    name: str
    class_path: str

    element: etree._Element
    """The table-of-contents IE itself.

    For the CommunicationSet this *is* the content — it is modelled inline (§8.3), so
    there is no hierarchy to follow and the walk starts here. For every other aspect
    the entry is only a pointer and the content lives in `hierarchy`.
    """

    hierarchy: etree._Element | None
    """The InstanceHierarchy implementing this aspect, resolved from AspectRef.

    `None` for the CommunicationSet only: it is modelled inline under the
    ModuleTypePackage IE and has no AspectSetReference (§8.3, Figure 3).
    """


def read_table_of_contents(
    path: Path, root: etree._Element, module: etree._Element
) -> list[AspectEntry]:
    """Read the manifest's table of contents — [2658-1:2022] Table 36 #9–#11.

    Entries are found by **derivation from MTPSet**, not by a list of known aspect
    names: the rule is open-ended by design ("for each aspect … a new directory
    class derived from MTPSet"), and 1.1.0 already adds AttachmentSet.
    """
    entries: list[AspectEntry] = []

    for element in _children(module, "InternalElement"):
        class_path = element.get("RefBaseSystemUnitPath")
        if not class_path or not is_derived_from(root, class_path, MTP_SET_CLASS):
            # Not a table-of-contents entry. The ModuleTypePackage IE also holds
            # non-aspect children, so this is a filter, not an error.
            continue

        name = element.get("Name") or ""
        if class_path == COMMUNICATION_SET_CLASS:
            # [§8.3, Figure 3] "CommunicationSet has no AspectSetReference" — it is
            # modelled inline, so there is no hierarchy to resolve.
            entries.append(
                AspectEntry(
                    name=name,
                    class_path=class_path,
                    element=element,
                    hierarchy=None,
                )
            )
            continue

        entries.append(
            AspectEntry(
                name=name,
                class_path=class_path,
                element=element,
                hierarchy=_resolve_aspect_hierarchy(path, root, element, class_path),
            )
        )

    # [Table 36 #9] the CommunicationSet is mandatory and exists exactly once.
    communication = [e for e in entries if e.class_path == COMMUNICATION_SET_CLASS]
    if len(communication) != 1:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #9] expected exactly one "
            f"{COMMUNICATION_SET_CLASS!r} entry, found {len(communication)}"
        )

    return entries


def _resolve_aspect_hierarchy(
    path: Path, root: etree._Element, entry: etree._Element, class_path: str
) -> etree._Element:
    """Follow an optional aspect's AspectRef to its InstanceHierarchy."""
    # [Table 36 #10] exactly one ExternalInterface of the IC AspectSetReference.
    references = [
        ei
        for ei in _children(entry, "ExternalInterface")
        if ei.get("RefBaseClassPath") == ASPECT_SET_REFERENCE_CLASS
    ]
    if len(references) != 1:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #10] aspect entry {class_path!r} must have "
            f"exactly one ExternalInterface of {ASPECT_SET_REFERENCE_CLASS!r}, "
            f"found {len(references)}"
        )

    # [Table 36 #11] AspectRef holds the ID (a GUID) of the aspect's hierarchy.
    aspect_ref = _attribute_value(references[0], ASPECT_REF_ATTRIBUTE)
    if not aspect_ref:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #11] aspect entry {class_path!r} has no "
            f"{ASPECT_REF_ATTRIBUTE!r} value"
        )

    hierarchies = [
        ih for ih in _children(root, "InstanceHierarchy") if ih.get("ID") == aspect_ref
    ]
    if len(hierarchies) != 1:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #11] {ASPECT_REF_ATTRIBUTE}={aspect_ref!r} "
            f"of {class_path!r} resolves to {len(hierarchies)} InstanceHierarchy, expected 1"
        )
    return hierarchies[0]


def _check_ids_are_guids(path: Path, root: etree._Element) -> None:
    """[2658-1:2022 Table 36 #1] every AutomationML object ID is an RFC 4122 GUID.

    Checked because the whole reference mechanism rests on it: AspectRef (#11),
    ID-links (#3) and RefID (#4) all address objects *by ID*. A file with ad-hoc
    IDs is not the format this parser reads — manifest 1.0.0 files, for instance,
    routinely use short tokens.
    """
    offenders = [
        element.get("ID")
        for element in root.iter()
        if element.get("ID") and not _GUID_PATTERN.match(element.get("ID"))
    ]
    if offenders:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #1] all AutomationML object IDs must be "
            f"RFC 4122 GUIDs; {len(offenders)} are not, e.g. {offenders[:3]}"
        )


def _check_versions(path: Path, root: etree._Element) -> None:
    """Reject anything that is not CAEX 3.0 + manifest 1.1.0.

    Detection is by declared version, never by namespace sniffing: the namespace is
    a consequence of the CAEX version, not the statement of it.
    """
    schema_version = root.get("SchemaVersion")
    if schema_version != CAEX_SCHEMA_VERSION:
        raise MtpVersionError(
            f"{path.name}: CAEXFile/@SchemaVersion is {schema_version!r}, expected "
            f"{CAEX_SCHEMA_VERSION!r}. Manifest 1.1.0 is CAEX 3.0 (IEC 62714 Ed. 2.0); "
            "CAEX 2.15 / manifest 1.0.0 files are not supported yet."
        )

    # [2658-1:2022 Table 36 #2] every aspect model in the file is declared as
    # AdditionalInformation → Document(DocumentIdentifier, Version).
    declared = {
        document.get("DocumentIdentifier"): document.get("Version")
        for document in _descendants(root, "Document")
    }
    if MANIFEST_DOCUMENT_ID not in declared:
        raise MtpVersionError(
            f"{path.name}: [2658-1:2022 Table 36 #2] no {MANIFEST_DOCUMENT_ID!r} document "
            f"declaration found. Declared: {sorted(k for k in declared if k)}"
        )

    version = declared[MANIFEST_DOCUMENT_ID]
    if version != MANIFEST_VERSION:
        raise MtpVersionError(
            f"{path.name}: manifest aspect model is version {version!r}, expected "
            f"{MANIFEST_VERSION!r}."
        )


def _find_module_type_package(path: Path, root: etree._Element) -> etree._Element:
    """Locate the one ModuleTypePackage IE under the manifest IH."""
    hierarchies = [
        ih
        for ih in _children(root, "InstanceHierarchy")
        if ih.get("Name") == MANIFEST_IH_NAME
    ]
    if len(hierarchies) != 1:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #5] expected exactly one InstanceHierarchy "
            f"named {MANIFEST_IH_NAME!r}, found {len(hierarchies)}"
        )

    # [Table 36 #6] exactly one IE *of the SUC* ModuleTypePackage — matched exactly.
    # Note the standard distinguishes: #6 says "of the SUC ModuleTypePackage" (this
    # class), while #9 says aspect entries are "derived from MTPSet" (a derivation,
    # resolved via is_derived_from). Only #9 is open-ended.
    modules = [
        ie
        for ie in _children(hierarchies[0], "InternalElement")
        if ie.get("RefBaseSystemUnitPath") == MODULE_TYPE_PACKAGE_CLASS
    ]
    if len(modules) != 1:
        raise MtpStructureError(
            f"{path.name}: [2658-1:2022 Table 36 #6] expected exactly one InternalElement of "
            f"{MODULE_TYPE_PACKAGE_CLASS!r} under the {MANIFEST_IH_NAME!r} hierarchy, "
            f"found {len(modules)}"
        )
    return modules[0]
