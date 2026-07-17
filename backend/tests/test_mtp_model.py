"""Tests for the internal MTP model.

These pin the standards-driven parts — the enum codings and the immutability the
rest of the system relies on. Construction itself is dataclass machinery and is not
worth testing.
"""

from __future__ import annotations

import dataclasses

import pytest

from orchestrion.mtp.model import (
    Access,
    DataAssembly,
    IdentifierType,
    OpcUaNode,
    Pea,
    Service,
    ServiceProcedure,
)


def test_access_codes_match_the_standard() -> None:
    # [2658-1:2022] Table 13. The 2019 edition's Table 1 omitted 0 while its own
    # Annex A example used it; a wrong value here silently mis-reads every DataItem.
    assert (Access.NONE, Access.READ, Access.WRITE, Access.READ_WRITE) == (0, 1, 2, 3)


def test_identifier_types_are_table_3s_own_values() -> None:
    # [2658-1:2019] Table 3 — the four ways an OPC UA node may be identified. The
    # values are the standard's literal AttributeDataType spellings, so the enum
    # maps straight off the file. Table 3 is normative; Blatt 1:2019's own Annex A
    # writes xs:int / xs:Base64Binary instead, and the standard wins.
    assert {t.value for t in IdentifierType} == {
        "xs:string",
        "xs:integer",
        "xs:base64binary",
        "xs:ID",
    }
    assert IdentifierType("xs:ID") is IdentifierType.GUID


def test_model_objects_are_immutable() -> None:
    # A parsed MTP describes a delivered PEA; nothing downstream may edit it.
    procedure = ServiceProcedure(
        name="Stir", ref_id="a", procedure_id=1, is_self_completing=False
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        procedure.procedure_id = 2  # type: ignore[misc]


def test_a_service_reaches_its_control_by_shared_ref_id() -> None:
    # [2658-1:2022 Table 36 #4] IEs sharing a RefID GUID are one and the same
    # modelled entity. This is the join the parser will implement, so the model has
    # to be able to express it.
    ref_id = "eafec7c5-508c-4e3f-94ab-8c9b3ccc78c6"
    control = DataAssembly(
        name="Stirring",
        ref_id=ref_id,
        class_path="MTPDataObjectSUCLib/DataAssembly/ServiceElement/ServiceControl",
        tag_name="Stirring",
        tag_description=None,
        nodes={
            "StateCur": OpcUaNode(
                namespace="http://www.siemens.com/simatic-s7-opcua",
                identifier='"Services_DB"."Stirring"."StateCur"',
                identifier_type=IdentifierType.STRING,
                access=Access.READ,
            )
        },
        constants={},
    )
    service = Service(
        name="Stirring",
        ref_id=ref_id,
        procedures=(
            ServiceProcedure(
                name="Continuous", ref_id="p1", procedure_id=1, is_self_completing=False
            ),
        ),
        control=control,
    )

    assert service.ref_id == service.control.ref_id
    # M2 subscribes to exactly this node.
    assert service.control.nodes["StateCur"].namespace.startswith("http")


def test_pea_holds_services_and_endpoints() -> None:
    pea = Pea(type_name="No Information", mtp_version="0.0.1", endpoints=(), services=())

    assert pea.services == ()
    assert pea.mtp_version == "0.0.1"
