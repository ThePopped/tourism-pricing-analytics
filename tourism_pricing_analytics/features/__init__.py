"""Layer 2 — browser-free feature derivation and encoding.

These modules read the JSONL streams persisted by the scraper and turn them into
a modelling table for the downstream price regression. Nothing here touches a
browser or Playwright: every function is pure over already-persisted records, so
the whole layer is fast to run and unit test, and the raw scrape artifact never
changes when encoding rules evolve.
"""
