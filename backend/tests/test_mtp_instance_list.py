"""The InstanceList walk — [2658-1:2022] Table 37 #19a–#19f.

The routing rules are the point of these tests: RefID and ID-link are both
`xs:string`, both carry a GUID, and they resolve in *opposite* directions. A parser
that confuses them binds nothing and looks like it has a data problem.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from lxml import etree

from orchestrion.mtp import caex, parser
from orchestrion.mtp.caex import MtpStructureError

ARTIFACT = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"

SERVICE_CONTROL_CLASS = (
    "MTPDataObjectSUCLib/DataAssembly/ServiceElement/ServiceControl"
)


@pytest.fixture
def hc30():
    """The manifest, its root, its CommunicationSet IE and the SourceList index."""
    manifest = caex.load_manifest(ARTIFACT)
    root = manifest.element.getroottree().getroot()
    communication = _communication_set(manifest.element)
    index = parser.read_source_list(ARTIFACT, root, communication)
    return manifest, root, communication, index


def _communication_set(module: etree._Element) -> etree._Element:
    return [
        ie
        for ie in caex._children(module, "InternalElement")
        if ie.get("RefBaseSystemUnitPath") == caex.COMMUNICATION_SET_CLASS
    ][0]


def test_reads_every_data_assembly(hc30):
    """[#19a] the InstanceList's data objects, keyed by RefID [Table 36 #4]."""
    _, root, communication, index = hc30
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    assert len(assemblies) == 10
    # Keyed by RefID — so every key is the value of that object's RefID attribute.
    for ref_id, assembly in assemblies.items():
        assert assembly.ref_id == ref_id


def test_service_control_is_present_and_bound(hc30):
    """The ServiceControl [2658-4:2022 Table 13] is what M2 subscribes to."""
    _, root, communication, index = hc30
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    controls = [
        a for a in assemblies.values() if a.class_path == SERVICE_CONTROL_CLASS
    ]
    assert len(controls) == 1

    control = controls[0]
    # The nodes M2/M3 actually drive — proof the ID-links resolved.
    for variable in ("StateCur", "CommandExt", "CommandEn", "ProcedureReq"):
        assert variable in control.nodes, f"{variable} not bound"

    assert control.nodes["StateCur"].namespace.startswith("http")


def test_ref_id_is_not_resolved_through_the_id_index(hc30):
    """[Table 36 #4] a RefID is a shared identity, NOT any element's ID.

    This is the trap: routing RefID through the ID index would find nothing. The
    fixture proves the two spaces are disjoint.
    """
    _, root, communication, index = hc30
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    for ref_id in assemblies:
        assert ref_id not in index.nodes, (
            f"RefID {ref_id} is also a data item ID — the two ID spaces would be "
            "ambiguous and the routing rule untestable"
        )


def test_id_links_resolve_to_opcua_nodes(hc30):
    """[#19b] every ID-link binds to a node from the SourceList index."""
    _, root, communication, index = hc30
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    bound = sum(len(a.nodes) for a in assemblies.values())
    # 158 IDLinkAttributeType attributes across the 10 data objects, all OPC UA.
    assert bound == 158
    assert all(
        node in index.nodes.values()
        for assembly in assemblies.values()
        for node in assembly.nodes.values()
    )


def test_tag_names_are_read_and_unique(hc30):
    """[#19f] TagName is unique within the InstanceList."""
    _, root, communication, index = hc30
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    tag_names = [a.tag_name for a in assemblies.values()]
    assert all(tag_names), "every data object carries a TagName"
    assert len(set(tag_names)) == len(tag_names)


def test_pea_information_label_is_reached_by_id_link_not_ref_id(hc30):
    """[Table 36 #7b] PeaInformation is an **ID-link**, against Table 2's wording.

    Table 2 declares the attribute `RefIDAttributeType` ("DataAssembly-RefID"); rule
    #7b says it holds the object's *ID* via the ID-link concept. The file settles it:
    the value is the PeaInformationLabel's element ID, and that object's own RefID is
    a different GUID. Resolving it Table 2's way finds nothing (journal 002 §9.3b).
    """
    manifest, root, communication, index = hc30
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    pea_information = caex.attribute_value(manifest.element, "PeaInformation")
    label = [
        a for a in assemblies.values() if a.class_path.endswith("PeaInformationLabel")
    ]
    assert len(label) == 1

    # The manifest's value is the element's ID — NOT its RefID.
    assert pea_information != label[0].ref_id
    assert pea_information not in assemblies


def test_dangling_id_link_raises(hc30):
    """[#19b] an ID-link to nothing is a broken file, not a tolerable quirk."""
    manifest, _, _, index = hc30
    tree = copy.deepcopy(manifest.element.getroottree())
    root = tree.getroot()
    module = [
        ie
        for ie in root.iter()
        if ie.get("RefBaseSystemUnitPath") == caex.MODULE_TYPE_PACKAGE_CLASS
    ][0]
    communication = _communication_set(module)

    # Scoped to the CommunicationSet on purpose: the *first* ID-link in document
    # order is the manifest's PeaInformation, which this walk never reads.
    link = [
        a
        for a in communication.iter("{*}Attribute")
        if a.get("RefAttributeType") == parser.ID_LINK_ATTRIBUTE_TYPE
    ][0]
    caex._children(link, "Value")[0].text = "ffffffff-ffff-ffff-ffff-ffffffffffff"

    with pytest.raises(MtpStructureError, match="no data item in the SourceList"):
        parser.read_instance_list(ARTIFACT, root, communication, index)


def test_communication_set_with_extra_child_raises(hc30):
    """[#13] the CommunicationSet has exactly two IEs — no more."""
    manifest, _, _, index = hc30
    tree = copy.deepcopy(manifest.element.getroottree())
    root = tree.getroot()
    module = [
        ie
        for ie in root.iter()
        if ie.get("RefBaseSystemUnitPath") == caex.MODULE_TYPE_PACKAGE_CLASS
    ][0]
    communication = _communication_set(module)
    etree.SubElement(communication, "{*}InternalElement", Name="Extra")

    with pytest.raises(MtpStructureError, match="Table 37 #13"):
        parser.read_instance_list(ARTIFACT, root, communication, index)
