"""The ServiceSet walk — [2658-4:2022] Table 36.

The rules under test are the ones that cannot be guessed from the shape of the file:
a service is named by its **ServiceControl's TagName** (#2c), not by its own IE Name;
a procedure by its **ProcedureHealthView's TagName** (#4f); and both are reached by a
*shared RefID*, never by containment or by an ID lookup.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from lxml import etree

from orchestrion.mtp import caex, parser
from orchestrion.mtp.caex import MtpStructureError

ARTIFACT = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"


@pytest.fixture
def hc30():
    """The ServiceSet's hierarchy plus the InstanceList it joins against."""
    manifest = caex.load_manifest(ARTIFACT)
    root = manifest.element.getroottree().getroot()
    return _prepare(manifest, root)


def _prepare(manifest, root):
    communication = [
        ie
        for ie in caex._children(manifest.element, "InternalElement")
        if ie.get("RefBaseSystemUnitPath") == caex.COMMUNICATION_SET_CLASS
    ][0]
    index = parser.read_source_list(ARTIFACT, root, communication)
    assemblies = parser.read_instance_list(ARTIFACT, root, communication, index)

    toc = caex.read_table_of_contents(ARTIFACT, root, manifest.element)
    hierarchy = [e for e in toc if e.class_path.endswith("ServiceSet")][0].hierarchy
    return root, hierarchy, assemblies


def _mutable_hc30():
    """A deep copy, so a test can break the file without touching the fixture."""
    manifest = caex.load_manifest(ARTIFACT)
    tree = copy.deepcopy(manifest.element.getroottree())
    root = tree.getroot()
    module = [
        ie
        for ie in root.iter()
        if ie.get("RefBaseSystemUnitPath") == caex.MODULE_TYPE_PACKAGE_CLASS
    ][0]

    class _M:
        element = module

    return _prepare(_M, root)


def test_reads_the_service(hc30):
    """[#2a] one IE of the SUC Service per service."""
    root, hierarchy, assemblies = hc30
    services = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)

    assert len(services) == 1
    assert services[0].ref_id == "eafec7c5-508c-4e3f-94ab-8c9b3ccc78c6"


def test_service_is_named_by_its_service_controls_tag_name(hc30):
    """[#2c] the name comes from the referenced DataAssembly, not the IE's Name."""
    root, hierarchy, assemblies = hc30
    service = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)[0]

    assert service.name == "Stirring"
    assert service.control is not None
    assert service.name == service.control.tag_name


def test_service_joins_its_control_by_shared_ref_id(hc30):
    """[Table 36 #4 / #2b] shared identity — the element IDs differ."""
    root, hierarchy, assemblies = hc30
    service = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)[0]

    assert service.control.class_path.endswith("ServiceElement/ServiceControl")
    assert service.control.ref_id == service.ref_id
    # The join is what makes M2/M3 possible at all.
    for variable in ("StateCur", "CommandExt", "CommandEn", "ProcedureReq"):
        assert variable in service.control.nodes


def test_procedures_are_read_with_ids_and_self_completing(hc30):
    """[#4a, #4b, #4c, #4g] — and 'False' must not become True."""
    root, hierarchy, assemblies = hc30
    service = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)[0]

    assert len(service.procedures) == 2  # matches the 2 ProcedureHealthViews

    by_name = {p.name: p for p in service.procedures}
    assert by_name["HC30_Stirring_Duration"].procedure_id == 2
    assert by_name["HC30_Stirring_Duration"].is_self_completing is True

    # The file says "False" — the bool("False") == True trap.
    assert by_name["HC30_Stirring_Continous"].procedure_id == 1
    assert by_name["HC30_Stirring_Continous"].is_self_completing is False


def test_procedure_is_named_by_its_health_views_tag_name(hc30):
    """[#4f] the name comes from the referenced DataAssembly."""
    root, hierarchy, assemblies = hc30
    service = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)[0]

    for procedure in service.procedures:
        health_view = assemblies[procedure.ref_id]
        assert health_view.class_path.endswith("ServiceElement/ProcedureHealthView")
        assert procedure.name == health_view.tag_name


def test_procedure_parameters_are_parsed(hc30):
    """[Table 36 #5] ProcedureParameter joined to its AnaServParam DataAssembly."""
    root, hierarchy, assemblies = hc30
    service = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)[0]
    by_id = {p.procedure_id: p for p in service.procedures}

    # #5: the Duration procedure has one parameter (the stir duration); Continous none.
    duration = by_id[2]
    assert len(duration.parameters) == 1
    assert len(by_id[1].parameters) == 0

    param = duration.parameters[0]
    assert param.name == "HC30_Duration_Stirring_Durration"          # #5c
    assert param.data.class_path.endswith("ParameterElement/AnaServParam")
    # the value channels the POL needs for controlled value assignment (§8.1.3)
    for channel in ("VExt", "VOut", "VReq", "VMin", "VMax", "VUnit", "ApplyExt"):
        assert channel in param.data.nodes


def test_procedure_ids_are_unique_and_non_zero(hc30):
    """[#4c] unique within the service; the ID 0 may not be assigned."""
    root, hierarchy, assemblies = hc30
    service = parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)[0]

    ids = [p.procedure_id for p in service.procedures]
    assert len(set(ids)) == len(ids)
    assert all(i >= 1 for i in ids)


def _procedure_attribute(hierarchy, name):
    return [
        a
        for a in hierarchy.iter("{*}Attribute")
        if a.get("Name") == name
    ][0]


def test_procedure_id_zero_raises(hc30):
    """[#4c] 0 means 'nothing selected' at runtime — it can never be a procedure."""
    root, hierarchy, assemblies = _mutable_hc30()
    attribute = _procedure_attribute(hierarchy, "ProcedureID")
    caex._children(attribute, "Value")[0].text = "0"

    with pytest.raises(MtpStructureError, match="0 may not be assigned"):
        parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)


def test_duplicate_procedure_id_raises(hc30):
    """[#4c] 'assigned uniquely within the service'."""
    root, hierarchy, assemblies = _mutable_hc30()
    ids = [a for a in hierarchy.iter("{*}Attribute") if a.get("Name") == "ProcedureID"]
    caex._children(ids[1], "Value")[0].text = caex._children(ids[0], "Value")[0].text

    with pytest.raises(MtpStructureError, match="not unique within service"):
        parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)


def test_unparsable_self_completing_raises(hc30):
    """[Table 25] BOOL is xs:boolean — 'yes' is not one of its values.

    The casing tolerance is deliberate and bounded: True/False are read, garbage is
    not silently coerced (which bool() would do).
    """
    root, hierarchy, assemblies = _mutable_hc30()
    attribute = _procedure_attribute(hierarchy, "IsSelfCompleting")
    caex._children(attribute, "Value")[0].text = "yes"

    with pytest.raises(MtpStructureError, match="xs:boolean"):
        parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)


def test_service_without_procedures_raises(hc30):
    """[#4g] every service has at least one procedure."""
    root, hierarchy, assemblies = _mutable_hc30()
    service = [
        ie
        for ie in caex._children(hierarchy, "InternalElement")
        if ie.get("RefBaseSystemUnitPath") == parser.SERVICE_CLASS
    ][0]
    for procedure in caex._children(service, "InternalElement"):
        service.remove(procedure)

    with pytest.raises(MtpStructureError, match="#4g"):
        parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)


def test_service_whose_ref_id_joins_nothing_raises(hc30):
    """[#2b] a Service with no ServiceControl cannot be driven at all."""
    root, hierarchy, assemblies = _mutable_hc30()
    service = [
        ie
        for ie in caex._children(hierarchy, "InternalElement")
        if ie.get("RefBaseSystemUnitPath") == parser.SERVICE_CLASS
    ][0]
    ref_id = [
        a
        for a in caex._children(service, "Attribute")
        if a.get("RefAttributeType") == parser.REF_ID_ATTRIBUTE_TYPE
    ][0]
    caex._children(ref_id, "Value")[0].text = "ffffffff-ffff-ffff-ffff-ffffffffffff"

    with pytest.raises(MtpStructureError, match="no DataAssembly sharing that RefID"):
        parser.read_service_set(ARTIFACT, root, hierarchy, assemblies)
