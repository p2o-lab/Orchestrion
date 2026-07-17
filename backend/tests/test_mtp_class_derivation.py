"""Tests for SystemUnitClass derivation resolved from the file's own libraries.

[2658-1:2022 Table 36 #9] identifies aspect entries as "IEs of SUCs derived from
MTPSet". Derivation is declared in the SystemUnitClassLib, not on the instance, so
answering that question means walking the file's class library.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from orchestrion.mtp.caex import (
    INTERFACE_CLASS,
    class_ancestry,
    find_class,
    is_derived_from,
)

HC30 = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"


def _root() -> etree._Element:
    return etree.parse(str(HC30)).getroot()


def test_finds_a_class_in_its_library() -> None:
    element = find_class(_root(), "MTPServiceSUCLib/ServiceSet")

    assert element is not None
    assert element.get("Name") == "ServiceSet"


def test_finds_a_nested_class() -> None:
    # SourceList is declared *inside* CommunicationSet, so the path is a nesting,
    # not a flat name.
    element = find_class(_root(), "MTPSUCLib/CommunicationSet/SourceList")

    assert element is not None
    assert element.get("Name") == "SourceList"


def test_unknown_class_is_not_found() -> None:
    assert find_class(_root(), "MTPSUCLib/NoSuchClass") is None
    assert find_class(_root(), "NoSuchLib/Whatever") is None


def test_ancestry_reaches_mtpset() -> None:
    # ServiceSet --RefBaseClassPath--> MTPSet, which is a root (no parent).
    assert class_ancestry(_root(), "MTPServiceSUCLib/ServiceSet") == [
        "MTPServiceSUCLib/ServiceSet",
        "MTPSUCLib/MTPSet",
    ]


def test_the_aspect_sets_in_hc30_all_derive_from_mtpset() -> None:
    # The point of Table 36 #9: these are found by derivation, not by a hardcoded
    # list of aspect names. CommunicationSet is mandatory; the rest are optional
    # aspects this vendor happened to ship.
    root = _root()

    for class_path in (
        "MTPSUCLib/CommunicationSet",
        "MTPServiceSUCLib/ServiceSet",
        "MTPHMISUCLib/HMISet",
        "MTPProcessValueSUCLib/ProcessValueSet",
        "MTPTextSUCLib/TextSet",
    ):
        assert is_derived_from(root, class_path, "MTPSUCLib/MTPSet"), class_path


def test_a_non_aspect_class_does_not_derive_from_mtpset() -> None:
    root = _root()

    # Service derives from LinkedObject, not MTPSet — it is content *inside* an
    # aspect, not an entry in the table of contents.
    assert not is_derived_from(root, "MTPServiceSUCLib/Service", "MTPSUCLib/MTPSet")
    assert is_derived_from(root, "MTPServiceSUCLib/Service", "MTPSUCLib/LinkedObject")


def test_interface_classes_resolve_in_their_own_library() -> None:
    # [Table 37 #15] information items are "ExternalInterface of an IC *derived
    # from* the IC DataItem". ICs live in InterfaceClassLib, in parallel to the
    # SUCs — same nesting, same RefBaseClassPath, different container.
    root = _root()

    assert is_derived_from(
        root,
        "MTPCommunicationICLib/DataItem/OPCUAItem",
        "MTPCommunicationICLib/DataItem",
        INTERFACE_CLASS,
    )
    # Blatt 5.1 introduces OPCUAItem by derivation from Blatt 1's abstract DataItem;
    # this is why the concrete class is not hardcoded.
    assert class_ancestry(
        root, "MTPCommunicationICLib/DataItem/OPCUAItem", INTERFACE_CLASS
    ) == [
        "MTPCommunicationICLib/DataItem/OPCUAItem",
        "MTPCommunicationICLib/DataItem",
    ]


def test_an_interface_class_is_not_found_among_system_unit_classes() -> None:
    # The two libraries are separate; searching the wrong one must not half-work.
    assert find_class(_root(), "MTPCommunicationICLib/DataItem") is None


def test_ancestry_of_an_undeclared_class_stops_cleanly() -> None:
    # A class the file does not declare yields just itself — no crash, no invention.
    assert class_ancestry(_root(), "MysteryLib/MysteryClass") == ["MysteryLib/MysteryClass"]
