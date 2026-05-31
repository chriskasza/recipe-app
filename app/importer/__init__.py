"""Importer module: URL/structured-payload → canonical recipe file.

Currently houses the recipe writer (``save.py``) behind ``recipes save-recipe``. The
deterministic URL fetch + JSON-LD extraction half remains future work — for now an
agent does the extraction and feeds a JSON payload to the writer.
"""
