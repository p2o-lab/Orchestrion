"""Tests for the CommunicationSet's SourceList walk — [2658-1:2022] Table 37 #13–#16."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrion.mtp.caex import (
    COMMUNICATION_SET_CLASS,
    load_manifest,
    read_table_of_contents,
)
from orchestrion.mtp.model import Access, IdentifierType
from orchestrion.mtp.parser import read_source_list

HC30 = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"


def _source_list():
    manifest = load_manifest(HC30)
    root = manifest.element.getroottree().getroot()
    toc = read_table_of_contents(HC30, root, manifest.element)
    communication = next(e for e in toc if e.class_path == COMMUNICATION_SET_CLASS)
    # The CommunicationSet is modelled inline, so its IE is the ToC entry itself.
    element = next(
        ie
        for ie in manifest.element.iterchildren()
        if ie.get("RefBaseSystemUnitPath") == COMMUNICATION_SET_CLASS
    )
    assert communication.hierarchy is None
    return read_source_list(HC30, root, element)


def test_reads_the_pea_endpoint() -> None:
    # [2658-5.1 Table 32] the OPCUAServer's Endpoint is the URL M2 will dial.
    endpoints = _source_list().endpoints

    assert len(endpoints) == 1
    assert endpoints[0].url == "opc.tcp://134.130.125.142:4840"


def test_indexes_every_opcua_item_by_id() -> None:
    # The index is the resolution target for ID-links (Table 37 #19b). CAEX IDs are
    # plain strings, so no XML-native IDREF resolution exists — we build this.
    nodes = _source_list().nodes

    # 158 *instances*. The file contains 159 Identifier attributes: the 159th
    # belongs to the <InterfaceClass Name="OPCUAItem"> declaration in the library,
    # which declares the attribute rather than carrying a node address. Walking the
    # SourceList reaches instances only, which is the distinction that matters.
    assert len(nodes) == 158
    assert all(len(node_id) == 36 for node_id in nodes)  # RFC 4122, Table 36 #1


def test_a_node_carries_its_namespace_identifier_and_access() -> None:
    nodes = _source_list().nodes

    node = nodes["fb3679a5-f6fb-4998-a726-5868112e084e"]

    # [Table 3] the identifier's type comes from the attribute's data type.
    assert node.identifier_type is IdentifierType.STRING
    assert node.identifier == '"ProcessValues_DB"."MTPBinaryOut"[0]."VState1"'
    # Resolved by URI against the live server at M2 — never used as an index.
    assert node.namespace == "http://www.siemens.com/simatic-s7-opcua"
    assert node.access is Access.READ


def test_every_namespace_is_a_uri() -> None:
    # [research §4.4] namespaces resolve by URI, not by index — the #1 interop
    # failure in the open-source peers.
    nodes = _source_list().nodes

    assert {node.namespace for node in nodes.values()} == {
        "http://www.siemens.com/simatic-s7-opcua"
    }


def test_access_values_seen_are_all_from_table_13() -> None:
    nodes = _source_list().nodes

    assert {node.access for node in nodes.values()} <= set(Access)


def test_hc30_instantiates_only_opcua_items() -> None:
    # [Table 37 #14, §9.1] the standard admits several communication technologies,
    # each concretised in its own Blatt 5 sub-part — so foreign items are a case the
    # parser must handle. This fixture does not exercise it: HC30 *declares* four IEC
    # telegram InterfaceClasses and instantiates none of them.
    #
    # Declaring a class is not using it. The class libraries say what *could* appear;
    # the InstanceHierarchy says what *does*. Conflating the two is what made an
    # earlier reading of this file claim it "ships IEC items" — it does not.
    index = _source_list()

    assert len(index.endpoints) == 1
    assert len(index.nodes) == 158
    assert index.foreign_item_ids == frozenset()
