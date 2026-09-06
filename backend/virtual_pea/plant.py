"""Serve a **plant** of VirtualPEA instances — several modules, one command.

    cd backend
    .venv/Scripts/python -m virtual_pea.plant                 # 3 PEAs: 48050 48051 48052
    .venv/Scripts/python -m virtual_pea.plant --count 5       # keeps the 3, adds 2
    .venv/Scripts/python -m virtual_pea.plant --all           # every manifest in the folder

Why this exists, and why it is not just a loop around `run.py`:

**HC30 declares one service.** A single VirtualPEA is therefore a one-service plant, and
orchestration means sequencing services *across modules* — so there is nothing to watch a
recipe do until several PEAs exist. We get them by running the **same conformant server
more than once**, which is what a modular plant is; we never add fake capabilities to the
VirtualPEA, because it mirrors HC30 exactly on purpose.

**The endpoint lives inside the `.aml`.** `VirtualPEA` binds to the URL its own MTP
declares, and the POL dials the URL the *stored* MTP declares (`PeaConnection` reads
`pea.endpoints[0].url`). That is deliberate — one file, one source of truth, no PEA/POL
endpoint drift — but it means N instances need N manifests, each declaring its own port.
Importing one file three times would produce three PEA rows all pointing at the same
server. So this module writes the manifests as well as serving them.

The manifests live in `virtual_pea/manifests/`, are named after their port, and are
**generated artifacts** — gitignored, and reproducible from `HC30_Stirring_V8_local.aml` at
any time. Deleting the folder costs nothing but the seconds it takes to write it again.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from orchestrion.mtp.caex import MtpError
from orchestrion.mtp.parser import read_mtp
from virtual_pea.server import VirtualPEA

logger = logging.getLogger("virtual_pea.plant")

HOST = "127.0.0.1"
"""Everything is served on the loopback IPv4 address, matching the source manifest.

Not `localhost`: this repo has already paid for that once (journal `001`) — Node resolves
`localhost` to `::1` while a service bound to `127.0.0.1` is not there, and the failure is a
bare ECONNREFUSED. A literal address skips name resolution entirely.
"""

SOURCE = Path(__file__).resolve().parent / "HC30_Stirring_V8_local.aml"
"""The VirtualPEA's own copy of the HC30 MTP — the one every manifest is derived from.

(The pristine vendor file stays in `tests/artifacts/` as the M1 parser fixture, keeping
HC30's real `134.130.125.142` endpoint. It is never written to.)
"""

SOURCE_ENDPOINT = "opc.tcp://127.0.0.1:48050"
"""The endpoint `SOURCE` declares, and the only occurrence of a port in that file.

Verified rather than assumed: `grep -c 48050` over the source is **1**, at the
`OPCUAServer`'s `Endpoint` value. So deriving a manifest is one string replacement, and
`_create` asserts the replacement actually happened rather than trusting it.
"""

MANIFESTS = Path(__file__).resolve().parent / "manifests"
DEFAULT_BASE_PORT = 48050
DEFAULT_COUNT = 3

MIN_PORT, MAX_PORT = 1, 65535
"""The TCP port range. Enforced because nothing else does, and going past it is silent:
`endpoint_for(65536)` produces a perfectly well-formed-looking URL, the manifest is written,
and only the *next* run discovers that `urlparse().port` refuses to parse it — by which time
the folder cannot be read at all."""


class PlantError(RuntimeError):
    """The manifest folder cannot be served as a plant."""


@dataclass(frozen=True)
class Manifest:
    """One generated MTP and the module it describes."""

    path: Path
    endpoint: str
    port: int


def endpoint_for(port: int) -> str:
    return f"opc.tcp://{HOST}:{port}"


def manifest_name(port: int) -> str:
    """Named after the port, so the folder is self-describing in a file picker."""
    return f"HC30_{port}.aml"


def scan(folder: Path) -> list[Manifest]:
    """Every manifest in `folder`, sorted by port.

    The endpoint is read from **the file's own content**, never inferred from its name: a
    name is a convention we chose, the declared endpoint is what the server binds to and
    what the POL dials. If someone edits one by hand, the file wins and the disagreement
    shows up here rather than as two modules that mysteriously mirror each other.

    Parsing each manifest also validates it — a corrupt one is caught at launch instead of
    at import. Enforces the folder's one invariant: **no two manifests share an endpoint.**
    """
    if not folder.is_dir():
        return []

    found: list[Manifest] = []
    seen: dict[str, Path] = {}
    for path in sorted(folder.glob("*.aml")):
        try:
            pea = read_mtp(path)
        except MtpError as exc:
            raise PlantError(
                f"{path.name} is in {folder.name}/ but is not a readable MTP: {exc}"
            ) from exc
        if not pea.endpoints:
            raise PlantError(f"{path.name} declares no OPC UA endpoint")

        endpoint = pea.endpoints[0].url
        key = endpoint.strip().rstrip("/").lower()
        if key in seen:
            raise PlantError(
                f"two manifests declare the same endpoint {endpoint}: "
                f"{seen[key].name} and {path.name}. Every manifest in {folder.name}/ must "
                "have its own port — delete or repoint one of them."
            )
        seen[key] = path

        try:
            port = urlparse(endpoint).port
        except ValueError as exc:
            # `urlparse` **raises** for a port outside 0-65535 rather than returning None.
            # Left bare, one bad manifest poisoned the entire folder: every later command
            # died here with "Port out of range 0-65535" and no file name, so there was
            # nothing to act on and no way back except deleting files by guesswork.
            raise PlantError(
                f"{path.name}: endpoint {endpoint} has an impossible port — {exc}. "
                "Delete or repoint that manifest."
            ) from exc
        if port is None:
            raise PlantError(f"{path.name}: endpoint {endpoint} carries no port")
        found.append(Manifest(path=path, endpoint=endpoint, port=port))

    return sorted(found, key=lambda m: m.port)


def _create(folder: Path, port: int) -> Manifest:
    """Write one manifest for `port`, derived from `SOURCE` by a single replacement."""
    folder.mkdir(parents=True, exist_ok=True)
    endpoint = endpoint_for(port)
    text = SOURCE.read_text(encoding="utf-8")
    if SOURCE_ENDPOINT not in text:
        # The source's endpoint is the one thing this module rewrites. If it ever stops
        # matching, silently writing an unchanged copy would produce N manifests that all
        # point at one server — the exact failure this module exists to prevent.
        raise PlantError(
            f"{SOURCE.name} no longer declares {SOURCE_ENDPOINT}; the manifest generator "
            "must be updated to match it."
        )
    path = folder / manifest_name(port)
    if path.exists():
        # **Never overwrite.** A file named for one port may declare another — rename or
        # repoint one by hand and the two disagree — and this used to clobber it: the
        # original manifest was lost, `ensure` returned more entries than there were files,
        # and two of them pointed at the same path, which `serve` would then try to bind
        # twice. `ensure` avoids reaching here; this is the second line, because a function
        # that can destroy data on a caller's mistake is a defect waiting for one.
        raise PlantError(
            f"{path.name} already exists — refusing to overwrite it. If it is stale, "
            "delete it; the plant regenerates whatever it needs."
        )
    path.write_text(text.replace(SOURCE_ENDPOINT, endpoint), encoding="utf-8")
    return Manifest(path=path, endpoint=endpoint, port=port)


def ensure(
    folder: Path = MANIFESTS,
    count: int = DEFAULT_COUNT,
    base_port: int = DEFAULT_BASE_PORT,
    *,
    serve_all: bool = False,
) -> tuple[list[Manifest], list[Manifest]]:
    """Bring the folder to at least `count` manifests; return `(to_serve, idle)`.

    Both directions, and neither ever deletes a file:

    * **fewer than asked** — the existing ones are kept and only the shortfall is created,
      at the lowest free ports from `base_port`. So `48050` + `48052` present with
      `count=3` fills `48051` rather than adding `48053`, and ports stay dense.
    * **more than asked** — the **lowest `count`** are served and the rest are returned as
      `idle` for the caller to name. Lowest-N is deterministic, so a project whose PEAs were
      imported from `48050`-`48052` keeps working across restarts; picking arbitrarily would
      leave yesterday's modules pointing at servers that are not running today.

    `serve_all` ignores `count` and serves everything present (creating nothing).
    """
    if count < 1:
        raise PlantError(f"--count must be at least 1, got {count}")
    if not MIN_PORT <= base_port <= MAX_PORT:
        raise PlantError(f"--base-port must be {MIN_PORT}-{MAX_PORT}, got {base_port}")

    existing = scan(folder)
    if serve_all:
        return existing, []

    if len(existing) >= count:
        return existing[:count], existing[count:]

    used = {m.port for m in existing}
    created: list[Manifest] = []
    port = base_port
    while len(existing) + len(created) < count:
        if port > MAX_PORT:
            raise PlantError(
                f"ran out of ports: asked for {count} manifests from {base_port}, and "
                f"there are not that many free below {MAX_PORT}."
            )
        # A port is available only if **no manifest declares it AND no file is named for
        # it**. Those two can disagree — a manifest renamed or repointed by hand — and
        # trusting the declared set alone is what let `_create` overwrite a file it had not
        # counted, losing that manifest and returning two entries for one path.
        taken = port in used or (folder / manifest_name(port)).exists()
        if not taken:
            created.append(_create(folder, port))
            used.add(port)
        port += 1

    return sorted(existing + created, key=lambda m: m.port), []


def _port_is_free(port: int) -> bool:
    """Whether `port` can still be bound on `HOST`.

    Checked before starting anything so the common mistake — a plant already running in
    another terminal — is reported by name instead of as an asyncua traceback halfway
    through bringing the plant up, with some servers already started.
    """
    if not MIN_PORT <= port <= MAX_PORT:
        return False  # not bindable, and `bind` would raise OverflowError, not OSError
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except (OSError, OverflowError):
            return False
    return True


async def serve(manifests: list[Manifest], idle: list[Manifest] | None = None) -> None:
    """Run every manifest as a VirtualPEA until interrupted.

    All of them share **one event loop**, exactly as the live tests do, so one Ctrl+C stops
    the whole plant and there are no orphaned children to hunt afterwards (journal `001`:
    killing a launcher does not kill the server it spawned).
    """
    taken = [m for m in manifests if not _port_is_free(m.port)]
    if taken:
        raise PlantError(
            "these ports are already in use: "
            + ", ".join(str(m.port) for m in taken)
            + ". Another plant is probably still running — stop it, or choose other ports."
        )

    servers: list[VirtualPEA] = []
    try:
        for manifest in manifests:
            server = VirtualPEA(manifest.path)
            await server.build()
            await server.start()
            servers.append(server)

        # ⚠ `flush=True` on every line of the summary, and it is not tidiness. Python
        # line-buffers stdout only when it is a terminal; redirect the plant to a file or a
        # pipe and the whole summary sits in the buffer **for as long as the plant runs** —
        # which is for ever. The one thing this tool must always manage to say is which
        # modules it is serving.
        say = lambda line: print(line, flush=True)  # noqa: E731
        say(f"\nserving {len(manifests)} PEA{'' if len(manifests) == 1 else 's'}:")
        for manifest in manifests:
            say(f"  {manifest.endpoint}   {manifest.path}")
        if idle:
            # Named because these will sit disconnected in the UI if they were imported
            # earlier, and an unexplained offline module is a phantom to chase.
            say("\nidle (present but not served): " + ", ".join(str(m.port) for m in idle))
        say("\nImport these files as separate PEAs, then Connect each. Ctrl+C to stop.\n")

        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for server in servers:
            await server.stop()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Serve a plant of VirtualPEA instances (one manifest per module)."
    )
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT,
                    help=f"how many PEAs to serve (default {DEFAULT_COUNT})")
    ap.add_argument("--all", action="store_true", dest="serve_all",
                    help="serve every manifest in the folder, ignoring --count")
    ap.add_argument("--base-port", type=int, default=DEFAULT_BASE_PORT,
                    help=f"lowest port to allocate from (default {DEFAULT_BASE_PORT})")
    ap.add_argument("--dir", type=Path, default=MANIFESTS,
                    help="where the manifests live (default virtual_pea/manifests)")
    ap.add_argument("--verbose", action="store_true",
                    help="show asyncua's own INFO logging (very noisy)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)
    if not args.verbose:
        # asyncua logs ~1,100 INFO lines **per server** while building an address space, so
        # a 5-PEA plant scrolls 5,000+ lines past before the summary appears — burying the
        # one output that matters. Our own logger stays at INFO; theirs is raised unless
        # `--verbose` asks for it.
        for noisy in ("asyncua", "opcua"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        to_serve, idle = ensure(
            args.dir, args.count, args.base_port, serve_all=args.serve_all
        )
        if not to_serve:
            raise PlantError(f"no manifests in {args.dir} and none requested")
        asyncio.run(serve(to_serve, idle))
    except PlantError as exc:
        raise SystemExit(f"plant: {exc}") from exc
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
