"""Converts legacy .doc files to .docx via a locally installed LibreOffice,
so the same de-identification pipeline used for .docx can run on them.

Legacy .doc is a binary (OLE compound file) format with no reliable
pure-Python reader and no pure-Python writer at all - so even a from-scratch
parser could only ever be a one-way, lossy read. For a PII redaction tool,
a parser that silently mis-reads or skips text is worse than not supporting
the format at all (undetected text means undetected, unredacted PII). Rather
than risk that, this shells out to a real, well-tested converter that's
either already on the machine or a quick free install: LibreOffice.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_CANDIDATE_NAMES = ("soffice", "libreoffice")

# Common install locations that aren't necessarily on PATH.
_CANDIDATE_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/opt/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
]

_CONVERT_TIMEOUT_SECONDS = 120


class DocConversionError(RuntimeError):
    """Raised when a .doc file can't be converted to .docx."""


def find_soffice() -> Optional[str]:
    for name in _CANDIDATE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in _CANDIDATE_PATHS:
        if Path(path).is_file():
            return path
    return None


def convert_doc_to_docx(input_path: str, out_dir: str) -> str:
    """Converts `input_path` (.doc) to .docx inside `out_dir` using
    LibreOffice's headless mode. Returns the path to the resulting .docx.
    """
    soffice = find_soffice()
    if soffice is None:
        raise DocConversionError(
            "Legacy .doc files need LibreOffice installed to convert them to "
            ".docx first (free: https://www.libreoffice.org/download/). "
            "Alternatively, open the file in Word, use \"Save As\" to save it "
            "as .docx, and drop that file in instead."
        )

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    # Run against a throwaway user profile so this never collides with a
    # LibreOffice instance the user already has open (a shared profile lock
    # is a common cause of headless conversions silently hanging or failing).
    profile_dir = tempfile.mkdtemp(prefix="ndis_deid_soffice_profile_")
    try:
        try:
            proc = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation={Path(profile_dir).as_uri()}",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(out_dir_path),
                    str(input_path),
                ],
                capture_output=True,
                text=True,
                timeout=_CONVERT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocConversionError(
                f"Converting {Path(input_path).name} to .docx timed out after "
                f"{_CONVERT_TIMEOUT_SECONDS}s."
            ) from exc
        except OSError as exc:
            raise DocConversionError(
                f"Failed to launch LibreOffice ({soffice}) to convert "
                f"{Path(input_path).name}: {exc}"
            ) from exc
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    expected = out_dir_path / f"{Path(input_path).stem}.docx"
    if proc.returncode != 0 or not expected.exists():
        detail = (proc.stderr or proc.stdout or "").strip()
        raise DocConversionError(
            f"Failed to convert {Path(input_path).name} to .docx via LibreOffice"
            + (f": {detail}" if detail else ".")
        )
    return str(expected)
