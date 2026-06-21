"""Tier C property-scope feature extractors.

Each module defines one extractor whose ``extract(ctx)`` reads the loaded
property page (via ``PropertyFeatureContext.page``) and returns a dict of
``PropertyFeatureRecord`` fields. All are best-effort and nullable: a missing or
lazy-loaded section yields no field rather than failing the record or the run.
"""
