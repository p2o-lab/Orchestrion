"""Tests for the manifest's table of contents — [2658-1:2022] §8.3, Table 36 #9–#11."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from orchestrion.mtp.caex import (
    COMMUNICATION_SET_CLASS,
    MtpStructureError,
    load_manifest,
    read_table_of_contents,
)

HC30 = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"


def _toc():
    manifest = load_manifest(HC30)
    # The root of the *same* tree the manifest element came from — parsing twice
    # would give two unrelated trees.
    root = manifest.element.getroottree().getroot()
    return read_table_of_contents(HC30, root, manifest.element)


def test_finds_hc30s_aspect_entries() -> None:
    by_class = {entry.class_path for entry in _toc()}

    # Found by derivation from MTPSet — not by matching these names. A vendor may
    # ship any subset plus aspects we have never heard of.
    assert by_class == {
        COMMUNICATION_SET_CLASS,
        "MTPServiceSUCLib/ServiceSet",
        "MTPHMISUCLib/HMISet",
        "MTPProcessValueSUCLib/ProcessValueSet",
        "MTPTextSUCLib/TextSet",
    }


def test_communication_set_has_no_hierarchy_to_resolve() -> None:
    # [§8.3, Figure 3] "CommunicationSet has no AspectSetReference" — it is modelled
    # inline under the ModuleTypePackage IE. Expecting an AspectRef here would
    # wrongly reject every conformant MTP.
    communication = next(
        e for e in _toc() if e.class_path == COMMUNICATION_SET_CLASS
    )

    assert communication.hierarchy is None


def test_optional_aspects_resolve_to_their_hierarchy() -> None:
    # [Table 36 #11] AspectRef holds the GUID of the IH implementing the aspect.
    services = next(e for e in _toc() if e.class_path == "MTPServiceSUCLib/ServiceSet")

    assert services.hierarchy is not None
    assert services.hierarchy.get("Name") == "Services"


def test_entry_names_are_free_and_not_matched_on() -> None:
    # [Table 36 #9] "The names of these IEs can be freely chosen." HC30 happens to
    # name them readably; MTPPy names hierarchies with raw GUIDs. Only the class and
    # the AspectRef carry meaning.
    entries = {e.class_path: e.name for e in _toc()}

    assert entries[COMMUNICATION_SET_CLASS] == "Communication"
    assert entries["MTPServiceSUCLib/ServiceSet"] == "Services"


def test_rejects_a_dangling_aspect_ref(tmp_path: Path) -> None:
    # An AspectRef pointing at no hierarchy is a broken MTP: fail, never skip.
    manifest = load_manifest(HC30)
    root = manifest.element.getroottree().getroot()

    ns = "{http://www.dke.de/CAEX}"
    for attribute in root.iter(f"{ns}Attribute"):
        if attribute.get("Name") == "AspectRef":
            attribute.find(f"{ns}Value").text = "00000000-0000-0000-0000-000000000000"
            break
    else:  # pragma: no cover - the fixture is known to contain AspectRefs
        pytest.fail("fixture has no AspectRef to break")

    with pytest.raises(MtpStructureError, match="Table 36 #11"):
        read_table_of_contents(tmp_path / "broken.aml", root, manifest.element)
