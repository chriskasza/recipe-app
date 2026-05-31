"""Authentication: file-backed user store + password hashing.

Credentials live in a JSON file under ``DATA_DIR`` (not the SQLite mirror, which
is derived and wiped by ``recipes rebuild-index``). See ``app.auth.store``.
"""
