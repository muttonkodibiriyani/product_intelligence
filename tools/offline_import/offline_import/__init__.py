"""Offline import of partner catalogue feeds (CSV, XLSX, JSON) into the pi_db fact store.

A column-mapping config (``mapping.ImportMapping``) says which feed column holds which field.
``validate`` checks every row and builds a report without touching the database; ``load`` writes
the accepted rows as one crawl_run with one evidence row for the file (fetch_method
``offline_import``, rung 0). Re-importing the same file (same sha256) is a no-op.
"""

__version__ = "0.1.0"
