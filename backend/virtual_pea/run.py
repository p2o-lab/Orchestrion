"""Run the VirtualPEA as a standalone OPC UA server.

    cd backendw
    .venv/Scripts/python -m virtual_pea.run                 # default :48050
    .venv/Scripts/python -m virtual_pea.run --endpoint opc.tcp://0.0.0.0:48055

Drive it from UaExpert or the POL: resolve the namespace URI (do NOT hardcode the
index), then to run the Stirring service:
  1. StateAutOp   = True   (-> StateAutAct True: Automatic mode)
  2. SrcExtOp     = True   (-> SrcExtAct  True: External source)
  3. ProcedureExt = 1      (-> ProcedureReq 1: procedure confirmed)
  4. CommandExt   = 4      (START -> StateCur 8 STARTING -> 64 EXECUTE)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from virtual_pea.server import VirtualPEA

# The VirtualPEA's own copy of the HC30 MTP, with the endpoint localised to
# opc.tcp://127.0.0.1:48050. This is the file the POL will also read — one source of
# truth for both sides. (The pristine vendor copy stays in tests/artifacts as the M1
# parser fixture and keeps HC30's real 134.130.125.142 endpoint.)
DEFAULT_MTP = Path(__file__).resolve().parent / "HC30_Stirring_V8_local.aml"


async def _serve(mtp: Path, endpoint: str | None) -> None:
    pea = VirtualPEA(mtp, endpoint=endpoint)
    await pea.build()
    await pea.start()
    print(f"VirtualPEA running at {pea.endpoint} (Ctrl+C to stop)")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await pea.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the VirtualPEA OPC UA server.")
    ap.add_argument("--mtp", type=Path, default=DEFAULT_MTP, help="MTP .aml to serve")
    ap.add_argument(
        "--endpoint", default=None,
        help="OPC UA endpoint URL (default: the endpoint declared in the .aml)",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(_serve(args.mtp, args.endpoint))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
