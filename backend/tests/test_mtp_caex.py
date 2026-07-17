"""Tests for the CAEX/manifest entry point against a real vendor MTP.

Fixture: 2026-05-18-HC30_Stirring_V8.aml — a SIMATIC S7-1500 export shipping with
Recipol. CAEX 3.0 / manifest 1.1.0 / ServiceSet 1.0.0, the only artifact we hold on
the current manifest *and* the released Blatt 4 service model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrion.mtp.caex import (
    MtpStructureError,
    MtpVersionError,
    load_manifest,
)

ARTIFACTS = Path(__file__).parent / "artifacts"
HC30 = ARTIFACTS / "2026-05-18-HC30_Stirring_V8.aml"


def test_loads_the_hc30_manifest() -> None:
    manifest = load_manifest(HC30)

    # [2658-1:2022 Table 36 #6] the IE's Name carries the PEA type name — but this
    # vendor left it unpopulated, so the file says the literal "No Information"
    # rather than "HC30". That is still conformant: the rule requires a Name, and
    # cannot require a meaningful one. We report what the file says.
    assert manifest.pea_type_name == "No Information"
    # [2658-1:2022 Table 36 #7a] Major.Minor.Patch. This is the MTP *instance*
    # version (the vendor's file revision) — not the 1.1.0 manifest aspect version.
    assert manifest.mtp_version == "0.0.1"


def test_reads_all_four_identification_attributes() -> None:
    # [2658-1:2022 Table 36 #7a] all four are required — not just Version. This
    # vendor filled only Version; the rest are placeholders, which is conformant
    # (the rule requires them present, not meaningful).
    manifest = load_manifest(HC30)

    assert manifest.device_revision == "No Information"
    assert manifest.manufacturer_uri == "No Information"
    assert manifest.product_code == "No Information"


def test_rejects_a_missing_identification_attribute(tmp_path: Path) -> None:
    # [Table 36 #7a] Version alone is not enough.
    aml = tmp_path / "partial.aml"
    aml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CAEXFile FileName="partial.aml" SchemaVersion="3.0" xmlns="http://www.dke.de/CAEX">'
        "<AdditionalInformation>"
        '<Document DocumentIdentifier="VDI/VDE/NAMUR 2658-1:Manifest" Version="1.1.0"/>'
        "</AdditionalInformation>"
        '<InstanceHierarchy Name="ModuleTypePackage">'
        '<InternalElement Name="X" ID="d734baf2-ff1f-49b8-b225-8bc27ea1882d" '
        'RefBaseSystemUnitPath="MTPSUCLib/ModuleTypePackage">'
        '<Attribute Name="Version"><Value>0.0.1</Value></Attribute>'
        "</InternalElement></InstanceHierarchy></CAEXFile>",
        encoding="utf-8",
    )

    with pytest.raises(MtpStructureError, match="Table 36 #7a"):
        load_manifest(aml)


def test_rejects_non_guid_ids(tmp_path: Path) -> None:
    # [Table 36 #1] every AutomationML object ID is an RFC 4122 GUID. The whole
    # reference mechanism (AspectRef, ID-links, RefID) addresses objects by ID.
    aml = tmp_path / "shortids.aml"
    aml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CAEXFile FileName="shortids.aml" SchemaVersion="3.0" xmlns="http://www.dke.de/CAEX">'
        "<AdditionalInformation>"
        '<Document DocumentIdentifier="VDI/VDE/NAMUR 2658-1:Manifest" Version="1.1.0"/>'
        "</AdditionalInformation>"
        '<InstanceHierarchy Name="ModuleTypePackage" ID="LdTU-ZqDm-VsTp-Vf8R-gyTm"/>'
        "</CAEXFile>",
        encoding="utf-8",
    )

    with pytest.raises(MtpStructureError, match="Table 36 #1"):
        load_manifest(aml)


def test_manifest_element_is_the_module_type_package() -> None:
    manifest = load_manifest(HC30)

    assert manifest.element.get("RefBaseSystemUnitPath").endswith(
        "MTPSUCLib/ModuleTypePackage"
    )


def test_rejects_caex_215(tmp_path: Path) -> None:
    # A manifest 1.0.0 / CAEX 2.15 file must be refused outright, not half-parsed:
    # its table of contents and binding mechanism are different formats entirely.
    aml = tmp_path / "old.aml"
    aml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CAEXFile FileName="old.aml" SchemaVersion="2.15">'
        '<AdditionalInformation>'
        '<Document DocumentIdentifier="VDI/VDE/NAMUR 2658-1" Version="1.0.0"/>'
        "</AdditionalInformation>"
        '<InstanceHierarchy Name="ModuleTypePackage"/>'
        "</CAEXFile>",
        encoding="utf-8",
    )

    with pytest.raises(MtpVersionError, match="SchemaVersion"):
        load_manifest(aml)


def test_rejects_missing_manifest_declaration(tmp_path: Path) -> None:
    aml = tmp_path / "undeclared.aml"
    aml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CAEXFile FileName="undeclared.aml" SchemaVersion="3.0" '
        'xmlns="http://www.dke.de/CAEX">'
        '<InstanceHierarchy Name="ModuleTypePackage"/>'
        "</CAEXFile>",
        encoding="utf-8",
    )

    with pytest.raises(MtpVersionError, match="Table 36 #2"):
        load_manifest(aml)


def test_rejects_missing_manifest_hierarchy(tmp_path: Path) -> None:
    # [Table 36 #5] the entry IH must be named ModuleTypePackage. Every other IH
    # name is free, so a file naming this one differently is unreadable, not lenient.
    aml = tmp_path / "noih.aml"
    aml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CAEXFile FileName="noih.aml" SchemaVersion="3.0" xmlns="http://www.dke.de/CAEX">'
        '<AdditionalInformation>'
        '<Document DocumentIdentifier="VDI/VDE/NAMUR 2658-1:Manifest" Version="1.1.0"/>'
        "</AdditionalInformation>"
        '<InstanceHierarchy Name="SomethingElse"/>'
        "</CAEXFile>",
        encoding="utf-8",
    )

    with pytest.raises(MtpStructureError, match="Table 36 #5"):
        load_manifest(aml)


def test_rejects_not_well_formed_xml(tmp_path: Path) -> None:
    aml = tmp_path / "broken.aml"
    aml.write_text("<CAEXFile SchemaVersion='3.0'><oops>", encoding="utf-8")

    with pytest.raises(MtpStructureError, match="not well-formed"):
        load_manifest(aml)
