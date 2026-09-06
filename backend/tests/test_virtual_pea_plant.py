"""The plant launcher's manifest bookkeeping — `virtual_pea/plant.py`.

The part worth pinning is the **rewrite**, because its failure mode is silent: a manifest
whose endpoint did not actually get replaced still parses cleanly and still connects — to
the *wrong server*. You would see N modules in the UI that all mirror each other and blame
the recipe engine. So every test here checks the endpoint a generated file **declares**,
read back through `read_mtp`, never the filename we chose for it.

Serving is not exercised here (it starts real OPC UA servers and then blocks); the
multi-instance path it uses is already covered by `test_recipe_engine_live.py`, which runs
several VirtualPEAs in one loop.
"""

from __future__ import annotations

import pytest

from orchestrion.mtp.parser import read_mtp
from virtual_pea.plant import (
    PlantError,
    endpoint_for,
    ensure,
    manifest_name,
    scan,
)


def _ports(manifests) -> list[int]:
    return [m.port for m in manifests]


def test_creates_the_requested_count_from_an_empty_folder(tmp_path):
    to_serve, idle = ensure(tmp_path, count=3, base_port=48050)

    assert _ports(to_serve) == [48050, 48051, 48052]
    assert idle == []
    assert sorted(p.name for p in tmp_path.glob("*.aml")) == [
        "HC30_48050.aml",
        "HC30_48051.aml",
        "HC30_48052.aml",
    ]


def test_each_generated_manifest_declares_its_own_endpoint(tmp_path):
    """The core guarantee: the rewrite happened, and the result is still a valid MTP.

    Read back through the POL's own parser, because that is what will read it at import —
    if `read_mtp` cannot reach the endpoint, neither can the POL.
    """
    to_serve, _ = ensure(tmp_path, count=3, base_port=48050)

    for manifest in to_serve:
        pea = read_mtp(manifest.path)
        assert pea.endpoints[0].url == endpoint_for(manifest.port)
        assert pea.endpoints[0].url == manifest.endpoint
        # and the module behind it is intact — one service, two procedures
        assert [s.name for s in pea.services] == ["Stirring"]
        assert len(pea.services[0].procedures) == 2

    urls = {read_mtp(m.path).endpoints[0].url for m in to_serve}
    assert len(urls) == 3, "every manifest must point at a different server"


def test_running_again_with_the_same_count_reuses_and_creates_nothing(tmp_path):
    first, _ = ensure(tmp_path, count=3, base_port=48050)
    stamps = {p.name: p.stat().st_mtime_ns for p in tmp_path.glob("*.aml")}

    second, idle = ensure(tmp_path, count=3, base_port=48050)

    assert _ports(second) == _ports(first)
    assert idle == []
    assert {p.name: p.stat().st_mtime_ns for p in tmp_path.glob("*.aml")} == stamps


def test_growing_keeps_what_exists_and_adds_only_the_shortfall(tmp_path):
    ensure(tmp_path, count=2, base_port=48050)

    to_serve, idle = ensure(tmp_path, count=3, base_port=48050)

    assert _ports(to_serve) == [48050, 48051, 48052]
    assert idle == []
    assert len(list(tmp_path.glob("*.aml"))) == 3


def test_a_gap_is_filled_rather_than_appended(tmp_path):
    """48050 + 48052 present, three wanted -> 48051, not 48053. Ports stay dense."""
    ensure(tmp_path, count=1, base_port=48050)
    # A second call asking for *two* from 48052 keeps the one it found and adds 48052 —
    # asking for one more from 48052 would (correctly) have reused 48050 and created
    # nothing, which is the reuse rule doing its job.
    ensure(tmp_path, count=2, base_port=48052)
    assert _ports(scan(tmp_path)) == [48050, 48052]

    to_serve, _ = ensure(tmp_path, count=3, base_port=48050)

    assert _ports(to_serve) == [48050, 48051, 48052]


def test_more_manifests_than_asked_serves_the_lowest_and_deletes_nothing(tmp_path):
    """The 5-present, 3-wanted case: serve the lowest three, report the rest, keep all."""
    ensure(tmp_path, count=5, base_port=48050)

    to_serve, idle = ensure(tmp_path, count=3, base_port=48050)

    assert _ports(to_serve) == [48050, 48051, 48052]
    assert _ports(idle) == [48053, 48054]
    assert len(list(tmp_path.glob("*.aml"))) == 5, "nothing may be deleted"


def test_serve_all_ignores_the_count(tmp_path):
    ensure(tmp_path, count=4, base_port=48050)

    to_serve, idle = ensure(tmp_path, count=1, base_port=48050, serve_all=True)

    assert _ports(to_serve) == [48050, 48051, 48052, 48053]
    assert idle == []


def test_two_manifests_on_one_endpoint_are_rejected_by_name(tmp_path):
    """The folder's one invariant. A hand-copied manifest is the way this happens."""
    ensure(tmp_path, count=1, base_port=48050)
    clone = tmp_path / manifest_name(49999)
    clone.write_text((tmp_path / manifest_name(48050)).read_text(encoding="utf-8"),
                     encoding="utf-8")

    with pytest.raises(PlantError) as exc:
        scan(tmp_path)

    message = str(exc.value)
    assert manifest_name(48050) in message and clone.name in message
    assert endpoint_for(48050) in message


def test_the_endpoint_is_read_from_the_file_not_from_its_name(tmp_path):
    """A misnamed manifest is reported by what it *declares*, never by what it is called."""
    ensure(tmp_path, count=1, base_port=48050)
    (tmp_path / manifest_name(48050)).rename(tmp_path / "totally_unrelated.aml")

    found = scan(tmp_path)

    assert _ports(found) == [48050]
    assert found[0].path.name == "totally_unrelated.aml"


def test_a_file_that_is_not_an_mtp_fails_loudly(tmp_path):
    ensure(tmp_path, count=1, base_port=48050)
    (tmp_path / "broken.aml").write_text("<CAEXFile/>", encoding="utf-8")

    with pytest.raises(PlantError, match="broken.aml"):
        scan(tmp_path)


def test_an_empty_folder_scans_to_nothing(tmp_path):
    assert scan(tmp_path) == []
    assert scan(tmp_path / "does-not-exist") == []


def test_a_count_below_one_is_refused(tmp_path):
    with pytest.raises(PlantError, match="at least 1"):
        ensure(tmp_path, count=0)
