"""Scrape-time feature extraction (Layer 1).

A registry of small, isolated extractors that read already-loaded DOM and return
lightly-normalized fields. Encoding, seasonality, joins, and modelling prep live
in the separate, browser-free feature-derivation layer (Layer 2).
"""
