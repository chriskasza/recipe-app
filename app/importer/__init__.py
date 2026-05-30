"""Importer module: URL/structured-payload → canonical recipe draft.

Currently houses the draft writer (``draft.py``) behind ``recipes build-draft``. The
deterministic URL fetch + JSON-LD extraction half remains future work — for now an
agent does the extraction and feeds a JSON payload to the writer.
"""
