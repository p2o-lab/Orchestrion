"""`read_mtp()` — the parser's public entry point.

M1's "done when": a real vendor `.aml` becomes a `Pea` carrying the endpoint, the
services, their procedures, and the OPC UA nodes M2/M3 drive — with no XML above it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrion.mtp.caex import MtpVersionError
from orchestrion.mtp.model import Pea
from orchestrion.mtp.parser import read_mtp

ARTIFACT = Path(__file__).parent / "artifacts" / "2026-05-18-HC30_Stirring_V8.aml"

# MTPPy-generated and malformed: it declares SchemaVersion="3.0" while pointing
# noNamespaceSchemaLocation at the 2.15 schema. Dropped as a
# fixture; used here only to prove the version gate holds end-to-end.
VISIONFORGE = Path(
    "D:/ProjectDAAD/Orchestrion/reference/Recipol/Recipol/src/artifacts/visionforge.aml"
)


@pytest.fixture(scope="module")
def pea() -> Pea:
    return read_mtp(ARTIFACT)


def test_reads_the_pea(pea):
    assert isinstance(pea, Pea)
    assert pea.mtp_version == "0.0.1"
    # [Table 36 #6] a Name is required; a *meaningful* one cannot be (002 step 1).
    assert pea.type_name == "No Information"


def test_carries_the_section_12_identification(pea):
    """[§12.1/§12.3] the MTP side of PEA verification, for M2 to compare."""
    assert pea.manufacturer_uri == "No Information"
    assert pea.product_code == "No Information"
    assert pea.device_revision == "No Information"


def test_endpoint_is_the_url_m2_dials(pea):
    assert len(pea.endpoints) == 1
    assert pea.endpoints[0].url == "opc.tcp://134.130.125.142:4840"


def test_services_and_procedures(pea):
    assert len(pea.services) == 1
    service = pea.services[0]
    assert service.name == "Stirring"
    assert {p.procedure_id for p in service.procedures} == {1, 2}


def test_the_m3_handshake_chain_is_bound_and_writable(pea):
    """The whole point of M1: M3's chain resolved to real, writable nodes.

    research §4.3.1: the POL must reach Automatic + External and select a procedure
    *before* any command, or the PEA silently drops it.
    """
    control = pea.services[0].control
    assert control is not None

    for variable in ("StateAutOp", "SrcExtOp", "ProcedureExt", "CommandExt"):
        node = control.nodes[variable]
        assert node.access.name == "READ_WRITE", f"{variable} is not writable"

    # And the ones M2 subscribes to.
    for variable in ("StateCur", "CommandEn", "ProcedureReq", "ProcedureCur"):
        assert variable in control.nodes


def test_namespaces_are_uris_not_indices(pea):
    """research §4.4: the #1 interop failure in the open-source peers."""
    control = pea.services[0].control
    for node in control.nodes.values():
        assert node.namespace.startswith("http"), node.namespace


def test_model_is_immutable(pea):
    """A parsed MTP describes a delivered PEA — nothing downstream may edit it."""
    with pytest.raises(Exception):
        pea.type_name = "changed"


@pytest.mark.skipif(not VISIONFORGE.exists(), reason="reference clone not present")
def test_rejects_a_manifest_1_0_0_file():
    """The version seam, end-to-end.

    visionforge.aml *claims* SchemaVersion="3.0", so the CAEX gate alone passes — it
    is the aspect-model declaration (Table 36 #2) that catches it. This is why the
    version check reads both, and never sniffs namespaces.
    """
    with pytest.raises(MtpVersionError, match="2658-1:Manifest"):
        read_mtp(VISIONFORGE)
