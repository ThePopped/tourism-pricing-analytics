# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A machine learning pipeline providing pricing analytics for a tourism business in Crete. It scrapes Booking.com daily to build a competitor dataset, then applies two models:
1. **Clustering** — identifies close competitors based on property features (price, location, amenities, beach/urban distance, room sizes, etc.)
2. **Hedonic pricing model** (regression) — estimates fair-market benchmark value and interprets which features drive price differences

The output feeds a daily dashboard for competitive pricing insights.

## Development Standards

- Random seeds: always `10001`
- Comments: use double-hash format `## This is an example`
- Document each meaningful change in `changes_applied.md`
- Follow MLOps best practices for all modeling and pipeline work

## Environment Setup

```powershell
# Activate virtual environment (Windows)
.\.venv\Scripts\Activate.ps1

# Install project in editable mode
pip install -e .
```

## Running the Scraper

The current main script is [notebooks/property_page_scraper.py](notebooks/property_page_scraper.py) (Playwright-based):

```powershell
python notebooks/property_page_scraper.py
```

Output is saved to `saved_dom/runs/<timestamp>/` — includes per-interaction HTML captures and a `scrape_debug.log`.

## Architecture

The pipeline is designed in stages (see [README.md](README.md) for the full Mermaid diagram):

```
Booking.com → Ingestion (scraper) → Raw Storage → Data Engineering
→ Feature Pipeline → [Competitor Clustering | Hedonic Model] → Serving → Dashboard
                                                                       ↑
                                                            Monitoring & Retraining
```

### Current Phase: Data Ingestion / Scraping

The scraper uses **Playwright** (sync API) with human-like behavior (random pauses, noisy scrolling, mouse movement variance). It detects newly-opened modals by diffing DOM snapshots before/after clicks.

**Two-loop scrape flow** (see [docs/scraping/scraper_design.md](docs/scraping/scraper_design.md)):

1. **Room type loop** (non-daily): hit each property page with no dates to capture all room types regardless of availability
2. **Price loop** (daily): for each `(property, room type, lead time, stay length)` tuple, set dates via URL params (`&checkin=YYYY-MM-DD&checkout=YYYY-MM-DD`) and capture discounted prices — normalize to price-per-night

Scale estimate: ~4,500 page requests (100 properties × 3 room types × 5 lead times × 3 stay lengths) ≈ 75 min synchronous.

### Key Selector Patterns (stable across sessions)

- Listing cards on search page: `class="bd77474a8e"`
- Facilities section: `class="f6b6d2a959"`
- Room type "Read More" triggers: `href^="#RD"`
- Modals/overlays: `[role="dialog"]`, `[aria-modal="true"]`
- Cookies banner: `id="onetrust-banner-sdk"` (must accept/reject on first run)

### Configuration

[config.py](config.py) defines root paths:
- `ROOT` — repo root
- `DATA_DIR` — `data/`
- `RAW_DIR` — `data/sample/raw_html/` (sample HTML for development)

### Planned Downstream Stages (not yet implemented)

- Data engineering: schema validation, deduplication, QA
- Feature pipeline: static and time-varying predictors
- Clustering model (scikit-learn) for competitor identification
- Hedonic regression model with experiment tracking and versioning
- Batch scoring + retraining orchestration
- Monitoring: data freshness, drift, model degradation
- Analytics dashboard
