"""Top-level API used by both the GUI and tests: load the analyzer once,
then de-identify one or many Word (.docx, .doc) or plain-text (.txt) files.
"""
from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .converters import convert_doc_to_docx
from .docx_processor import deidentify_docx_file
from .pii_engine import DeidResult
from .recognizers import build_analyzer_engine
from .text_processor import deidentify_txt_file

SUPPORTED_EXTENSIONS = (".docx", ".doc", ".txt")

_analyzer = None
_analyzer_lock = threading.Lock()


def get_analyzer():
    """Lazily builds the (expensive-to-load) AnalyzerEngine once per process."""
    global _analyzer
    if _analyzer is None:
        with _analyzer_lock:
            if _analyzer is None:
                _analyzer = build_analyzer_engine()
    return _analyzer


def default_output_path(input_path: str) -> str:
    """Same folder, "_deidentified" suffix. A .doc input gets a .docx output,
    since legacy .doc can only be converted to .docx on the way in - there's
    no way to write back to the original binary format.
    """
    p = Path(input_path)
    suffix = ".docx" if p.suffix.lower() == ".doc" else p.suffix
    return str(p.with_name(f"{p.stem}_deidentified{suffix}"))


def deidentify_file(input_path: str, output_path: Optional[str] = None) -> DeidResult:
    ext = Path(input_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise ValueError(f"Unsupported file type {ext or '(none)'!r}. Supported types: {supported}.")

    output_path = output_path or default_output_path(input_path)
    analyzer = get_analyzer()

    if ext == ".txt":
        return deidentify_txt_file(input_path, output_path, analyzer)

    if ext == ".docx":
        return deidentify_docx_file(input_path, output_path, analyzer)

    # ext == ".doc": convert to .docx in a scratch dir first, then run the
    # normal .docx pipeline against the converted copy.
    with tempfile.TemporaryDirectory(prefix="ndis_deid_doc_convert_") as tmp_dir:
        converted_path = convert_doc_to_docx(input_path, tmp_dir)
        return deidentify_docx_file(converted_path, output_path, analyzer)


@dataclass
class FileOutcome:
    input_path: str
    output_path: Optional[str]
    result: Optional[DeidResult]
    error: Optional[str]


def deidentify_files(
    input_paths: List[str],
    output_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[FileOutcome]:
    """Processes each file independently - one bad/corrupt file doesn't stop
    the batch. If `output_dir` is given, outputs go there (same filename with
    a `_deidentified` suffix); otherwise each output sits next to its input.
    """
    outcomes: List[FileOutcome] = []
    total = len(input_paths)
    for i, input_path in enumerate(input_paths, start=1):
        if progress_callback:
            progress_callback(i, total, input_path)
        try:
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                out_name = Path(default_output_path(input_path)).name
                output_path = str(Path(output_dir) / out_name)
            else:
                output_path = default_output_path(input_path)
            result = deidentify_file(input_path, output_path)
            outcomes.append(FileOutcome(input_path, output_path, result, None))
        except Exception as exc:  # noqa: BLE001 - surface any per-file failure to the GUI
            outcomes.append(FileOutcome(input_path, None, None, str(exc)))
    return outcomes
