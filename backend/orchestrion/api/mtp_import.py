"""Parse an uploaded MTP `.aml` for the import flow.

The M1 parser reads by file path (and uses the filename in its error messages), so an
uploaded byte payload is written to a short-lived temp file and parsed there — leaving
the M1 code untouched. A parse failure surfaces as `MtpError`, which the import
endpoint turns into a 400 the UI can highlight; a success returns the model `Pea`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from orchestrion.mtp.model import Pea
from orchestrion.mtp.parser import read_mtp


def parse_aml(content: bytes, filename: str) -> Pea:
    """Validate and parse MTP bytes into a model `Pea`, or raise `MtpError`.

    `filename` is only cosmetic — it is copied onto the temp file so any parser error
    names the file the user actually uploaded, not a random temp name.
    """
    suffix = Path(filename).suffix or ".aml"
    tmp: Path | None = None
    try:
        # delete=False + explicit close: on Windows the parser cannot open the file
        # while our write handle is still open, so the `with` must exit first.
        with tempfile.NamedTemporaryFile(
            prefix=Path(filename).stem + "_", suffix=suffix, delete=False
        ) as handle:
            handle.write(content)
            tmp = Path(handle.name)
        return read_mtp(tmp)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
