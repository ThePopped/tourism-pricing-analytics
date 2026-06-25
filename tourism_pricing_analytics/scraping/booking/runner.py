import logging
import random
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from tourism_pricing_analytics.scraping.booking.browser import (
    ensure_page,
    ensure_property_facilities_loaded,
    navigate_to_page,
)
from tourism_pricing_analytics.scraping.booking.config import load_scraper_config
from tourism_pricing_analytics.scraping.booking.failures import (
    PageFailureClassification,
    classify_playwright_page_failure,
)
from tourism_pricing_analytics.scraping.booking.features.extract import extract_room_features
from tourism_pricing_analytics.scraping.booking.features.extract_property import (
    extract_property_features,
)
from tourism_pricing_analytics.scraping.booking.io import (
    append_property_failures,
    create_property_output_dir,
    create_run_dir,
    save_full_page_dom,
    save_jsonl_file,
    save_property_failures,
    save_property_features,
    save_property_price_rows,
    save_property_room_features,
    save_property_room_inventory,
    save_validation_report,
    resolve_run_search_base_date,
    setup_logging,
)
from tourism_pricing_analytics.scraping.booking.models import (
    FailureCategory,
    PriceRowRecord,
    PropertyTarget,
    PropertyFeatureRecord,
    RoomFeatureRecord,
    RoomInventoryRecord,
    ScrapeFailureRecord,
    ScrapeStage,
    ScraperConfig,
)
from tourism_pricing_analytics.scraping.booking.parsing import (
    extract_price_rows,
    extract_room_inventory,
)
from tourism_pricing_analytics.scraping.booking.retry import (
    backoff_delay_ms,
    should_retry,
)
from tourism_pricing_analytics.scraping.booking.sharding import (
    aggregate_run_artifacts,
    indexed_targets,
    pending_indexed_targets,
    select_indexed_targets,
)
from tourism_pricing_analytics.scraping.booking.urls import (
    build_date_window,
    build_dated_url,
    build_room_inventory_url,
)
from tourism_pricing_analytics.scraping.booking.validation import (
    validate_run_directory,
)


ROOM_INVENTORY_SELECTOR = '[href^="#RD"]'
ROOM_INVENTORY_FALLBACK_SELECTORS = [
    ".hprt-table",
    "#hprt-table",
    "[data-room-id]",
    "#availability_target",
    ".hp_availability",
]
PRICE_ROW_SELECTOR = "tr.js-rt-block-row"
PRICE_ROW_FALLBACK_SELECTORS = [
    ".hprt-table",
    "#hprt-table",
    ".bui-price-display__value",
    "select.hprt-nos-select",
    "[data-block-id]",
]


def classify_current_page_failure(
    page: Page | None,
    *,
    requested_url: str,
    expected_selector: str,
    fallback_selectors: list[str],
    status_code: int | None,
    default_category: FailureCategory,
    default_reason: str,
) -> PageFailureClassification:
    if page is not None and not page.is_closed():
        try:
            classification = classify_playwright_page_failure(
                page,
                requested_url=requested_url,
                expected_selector=expected_selector,
                fallback_selectors=fallback_selectors,
                status_code=status_code,
            )
            if classification is not None:
                return classification
        except Exception:
            logging.debug("Unable to classify current page content", exc_info=True)

    return PageFailureClassification(
        category=default_category,
        reason=default_reason,
    )


def save_failure_snapshot(
    page: Page | None,
    output_dir: Path,
    filename: str,
) -> str | None:
    if page is None or page.is_closed():
        return None

    try:
        save_full_page_dom(page, output_dir, filename=filename)
        return filename
    except Exception:
        logging.debug("Unable to save failure snapshot %s", filename, exc_info=True)
        return None


def get_page_url(page: Page | None) -> str | None:
    if page is None or page.is_closed():
        return None

    try:
        return page.url
    except Exception:
        logging.debug("Unable to read current page URL", exc_info=True)
        return None


def build_failure_record(
    *,
    target_name: str,
    target_url: str,
    scrape_stage: ScrapeStage,
    classification: PageFailureClassification,
    requested_url: str,
    final_url: str | None,
    captured_at: str,
    status_code: int | None,
    snapshot_filename: str | None,
    checkin: str | None = None,
    checkout: str | None = None,
    lead_time_days: int | None = None,
    stay_length_days: int | None = None,
    exception: Exception | None = None,
) -> ScrapeFailureRecord:
    return ScrapeFailureRecord(
        property_name=target_name,
        property_url=target_url,
        scrape_stage=scrape_stage,
        category=classification.category,
        reason=classification.reason,
        requested_url=requested_url,
        final_url=final_url,
        checkin=checkin,
        checkout=checkout,
        lead_time_days=lead_time_days,
        stay_length_days=stay_length_days,
        status_code=status_code,
        snapshot_filename=snapshot_filename,
        exception_type=type(exception).__name__ if exception is not None else None,
        exception_message=str(exception) if exception is not None else None,
        captured_at=captured_at,
    )


def wait_before_retry(page: Page | None, scraper_config: ScraperConfig, attempt: int) -> int:
    delay_ms = backoff_delay_ms(
        attempt,
        base_backoff_ms=scraper_config.retry.base_backoff_ms,
        max_backoff_ms=scraper_config.retry.max_backoff_ms,
        jitter_ms=scraper_config.retry.jitter_ms,
    )
    if delay_ms <= 0:
        return delay_ms

    if page is not None and not page.is_closed() and hasattr(page, "wait_for_timeout"):
        page.wait_for_timeout(delay_ms)
    return delay_ms


def run_room_inventory_loop(
    context: BrowserContext,
    page: Page,
    scraper_config: ScraperConfig,
    property_output_dirs: dict[str, Path],
) -> tuple[
    Page | None,
    list[RoomInventoryRecord],
    list[PropertyFeatureRecord],
    list[ScrapeFailureRecord],
]:
    records: list[RoomInventoryRecord] = []
    property_feature_records: list[PropertyFeatureRecord] = []
    failure_records: list[ScrapeFailureRecord] = []

    for target in scraper_config.properties:
        property_url = build_room_inventory_url(target.url)
        output_dir = property_output_dirs[target.url]
        property_failure_records: list[ScrapeFailureRecord] = []
        property_records: list[RoomInventoryRecord] = []
        captured_at = datetime.now().isoformat(timespec="seconds")

        for attempt in range(1, scraper_config.retry.max_attempts + 1):
            page = ensure_page(context, page)
            status_code: int | None = None
            navigation_completed = False

            try:
                status_code = navigate_to_page(
                    page,
                    property_url,
                    scraper_config,
                    scroll_page=True,
                )
                navigation_completed = True
                captured_at = datetime.now().isoformat(timespec="seconds")
                property_records = extract_room_inventory(
                    page,
                    target,
                    property_url,
                    captured_at,
                )
            except Exception as exc:
                captured_at = datetime.now().isoformat(timespec="seconds")
                classification = classify_current_page_failure(
                    page,
                    requested_url=property_url,
                    expected_selector=ROOM_INVENTORY_SELECTOR,
                    fallback_selectors=ROOM_INVENTORY_FALLBACK_SELECTORS,
                    status_code=status_code,
                    default_category="extraction_error"
                    if navigation_completed
                    else "navigation_error",
                    default_reason="Room inventory navigation or extraction raised an exception.",
                )
                if should_retry(
                    classification.category,
                    attempt,
                    scraper_config.retry.max_attempts,
                ):
                    delay_ms = wait_before_retry(page, scraper_config, attempt)
                    logging.warning(
                        "Retrying room inventory for %s after %s on attempt %d/%d; backoff_ms=%d",
                        target.name,
                        classification.category,
                        attempt,
                        scraper_config.retry.max_attempts,
                        delay_ms,
                    )
                    page = None
                    continue

                logging.exception("Room inventory extraction failed for %s", target.name)
                filename = f"room_inventory_{classification.category}.html"
                snapshot_filename = save_failure_snapshot(page, output_dir, filename)
                failure_record = build_failure_record(
                    target_name=target.name,
                    target_url=target.url,
                    scrape_stage="room_inventory",
                    classification=classification,
                    requested_url=property_url,
                    final_url=get_page_url(page),
                    captured_at=captured_at,
                    status_code=status_code,
                    snapshot_filename=snapshot_filename,
                    exception=exc,
                )
                failure_records.append(failure_record)
                property_failure_records.append(failure_record)
                append_property_failures(property_failure_records, output_dir)
                page = None
                break

            if property_records:
                records.extend(property_records)
                break

            classification = classify_current_page_failure(
                page,
                requested_url=property_url,
                expected_selector=ROOM_INVENTORY_SELECTOR,
                fallback_selectors=ROOM_INVENTORY_FALLBACK_SELECTORS,
                status_code=status_code,
                default_category="selector_drift",
                default_reason="No room inventory records were extracted.",
            )
            if should_retry(
                classification.category,
                attempt,
                scraper_config.retry.max_attempts,
            ):
                delay_ms = wait_before_retry(page, scraper_config, attempt)
                logging.warning(
                    "Retrying room inventory for %s after empty %s result on attempt %d/%d; backoff_ms=%d",
                    target.name,
                    classification.category,
                    attempt,
                    scraper_config.retry.max_attempts,
                    delay_ms,
                )
                page = None
                continue

            logging.warning(
                "No room inventory extracted for %s; category=%s",
                target.name,
                classification.category,
            )
            filename = f"room_inventory_{classification.category}.html"
            snapshot_filename = save_failure_snapshot(page, output_dir, filename)
            failure_record = build_failure_record(
                target_name=target.name,
                target_url=target.url,
                scrape_stage="room_inventory",
                classification=classification,
                requested_url=property_url,
                final_url=get_page_url(page),
                captured_at=captured_at,
                status_code=status_code,
                snapshot_filename=snapshot_filename,
            )
            failure_records.append(failure_record)
            property_failure_records.append(failure_record)
            append_property_failures(property_failure_records, output_dir)
            break

        if not property_records:
            continue

        # The undated property page is already scrolled here, so its subscores /
        # surroundings sections are loaded. The whole-property facilities section
        # (with the nested languages group) is lazy-loaded lower down, so bring it
        # into view explicitly before collecting the date-stable property features.
        # Isolated so an extraction error never disrupts the inventory scrape.
        try:
            ensure_property_facilities_loaded(page)
            property_feature = extract_property_features(
                page,
                property_name=target.name,
                property_url=target.url,
                captured_at=captured_at,
            )
            property_feature_records.append(property_feature)
            save_property_features([property_feature], output_dir)
        except Exception:
            logging.exception("Property feature extraction failed for %s", target.name)

        save_property_room_inventory(property_records, output_dir)
        logging.info(
            "Saved %d room inventory records for %s",
            len(property_records),
            target.name,
        )

    return page, records, property_feature_records, failure_records


def run_price_loop(
    context: BrowserContext,
    page: Page | None,
    scraper_config: ScraperConfig,
    property_output_dirs: dict[str, Path],
    search_base_date: date | None = None,
) -> tuple[Page | None, list[PriceRowRecord], list[RoomFeatureRecord], list[ScrapeFailureRecord]]:
    records: list[PriceRowRecord] = []
    room_feature_records: list[RoomFeatureRecord] = []
    failure_records: list[ScrapeFailureRecord] = []

    for target in scraper_config.properties:
        output_dir = property_output_dirs[target.url]
        property_records: list[PriceRowRecord] = []
        property_failure_records: list[ScrapeFailureRecord] = []
        # Room features are date-stable, so collect each room once across all
        # date windows, keyed by room_id, to maximise coverage if availability
        # differs between windows.
        room_features_by_id: dict[str, RoomFeatureRecord] = {}

        for lead_time_days in scraper_config.lead_times:
            for stay_length_days in scraper_config.stay_lengths:
                checkin, checkout = build_date_window(
                    lead_time_days,
                    stay_length_days,
                    base_date=search_base_date,
                )
                dated_url = build_dated_url(
                    target.url,
                    checkin=checkin,
                    checkout=checkout,
                    default_search=scraper_config.default_search,
                )
                price_rows: list[PriceRowRecord] = []
                captured_at = datetime.now().isoformat(timespec="seconds")

                for attempt in range(1, scraper_config.retry.max_attempts + 1):
                    page = ensure_page(context, page)
                    status_code: int | None = None
                    navigation_completed = False

                    try:
                        status_code = navigate_to_page(
                            page,
                            dated_url,
                            scraper_config,
                            scroll_page=False,
                        )
                        navigation_completed = True
                        captured_at = datetime.now().isoformat(timespec="seconds")
                        price_rows = extract_price_rows(
                            page,
                            target=target,
                            checkin=checkin,
                            checkout=checkout,
                            lead_time_days=lead_time_days,
                            stay_length_days=stay_length_days,
                            captured_at=captured_at,
                        )
                    except Exception as exc:
                        captured_at = datetime.now().isoformat(timespec="seconds")
                        classification = classify_current_page_failure(
                            page,
                            requested_url=dated_url,
                            expected_selector=PRICE_ROW_SELECTOR,
                            fallback_selectors=PRICE_ROW_FALLBACK_SELECTORS,
                            status_code=status_code,
                            default_category="extraction_error"
                            if navigation_completed
                            else "navigation_error",
                            default_reason="Price navigation or extraction raised an exception.",
                        )
                        if should_retry(
                            classification.category,
                            attempt,
                            scraper_config.retry.max_attempts,
                        ):
                            delay_ms = wait_before_retry(page, scraper_config, attempt)
                            logging.warning(
                                "Retrying price rows for %s, lead_time=%d, stay_length=%d after %s on attempt %d/%d; backoff_ms=%d",
                                target.name,
                                lead_time_days,
                                stay_length_days,
                                classification.category,
                                attempt,
                                scraper_config.retry.max_attempts,
                                delay_ms,
                            )
                            page = None
                            continue

                        logging.exception(
                            "Price extraction failed for %s, lead_time=%d, stay_length=%d",
                            target.name,
                            lead_time_days,
                            stay_length_days,
                        )
                        filename = (
                            f"price_rows_{classification.category}_lead_{lead_time_days:03d}"
                            f"_stay_{stay_length_days:03d}.html"
                        )
                        snapshot_filename = save_failure_snapshot(page, output_dir, filename)
                        failure_record = build_failure_record(
                            target_name=target.name,
                            target_url=target.url,
                            scrape_stage="price_rows",
                            classification=classification,
                            requested_url=dated_url,
                            final_url=get_page_url(page),
                            checkin=checkin.isoformat(),
                            checkout=checkout.isoformat(),
                            lead_time_days=lead_time_days,
                            stay_length_days=stay_length_days,
                            captured_at=captured_at,
                            status_code=status_code,
                            snapshot_filename=snapshot_filename,
                            exception=exc,
                        )
                        failure_records.append(failure_record)
                        property_failure_records.append(failure_record)
                        page = None
                        break

                    if price_rows:
                        records.extend(price_rows)
                        property_records.extend(price_rows)
                        break

                    classification = classify_current_page_failure(
                        page,
                        requested_url=dated_url,
                        expected_selector=PRICE_ROW_SELECTOR,
                        fallback_selectors=PRICE_ROW_FALLBACK_SELECTORS,
                        status_code=status_code,
                        default_category="selector_drift",
                        default_reason="No price rows were extracted.",
                    )
                    if should_retry(
                        classification.category,
                        attempt,
                        scraper_config.retry.max_attempts,
                    ):
                        delay_ms = wait_before_retry(page, scraper_config, attempt)
                        logging.warning(
                            "Retrying price rows for %s, lead_time=%d, stay_length=%d after empty %s result on attempt %d/%d; backoff_ms=%d",
                            target.name,
                            lead_time_days,
                            stay_length_days,
                            classification.category,
                            attempt,
                            scraper_config.retry.max_attempts,
                            delay_ms,
                        )
                        page = None
                        continue

                    logging.warning(
                        "No price rows extracted for %s, lead_time=%d, stay_length=%d; category=%s",
                        target.name,
                        lead_time_days,
                        stay_length_days,
                        classification.category,
                    )
                    filename = (
                        f"price_rows_{classification.category}_lead_{lead_time_days:03d}"
                        f"_stay_{stay_length_days:03d}.html"
                    )
                    snapshot_filename = save_failure_snapshot(page, output_dir, filename)
                    failure_record = build_failure_record(
                        target_name=target.name,
                        target_url=target.url,
                        scrape_stage="price_rows",
                        classification=classification,
                        requested_url=dated_url,
                        final_url=get_page_url(page),
                        checkin=checkin.isoformat(),
                        checkout=checkout.isoformat(),
                        lead_time_days=lead_time_days,
                        stay_length_days=stay_length_days,
                        captured_at=captured_at,
                        status_code=status_code,
                        snapshot_filename=snapshot_filename,
                    )
                    failure_records.append(failure_record)
                    property_failure_records.append(failure_record)
                    break

                if not price_rows:
                    continue

                # Collect date-stable room features from the loaded page. Isolated
                # so a feature-extraction error never disrupts the price scrape.
                try:
                    for feature in extract_room_features(
                        page,
                        property_name=target.name,
                        property_url=target.url,
                        captured_at=captured_at,
                    ):
                        room_features_by_id.setdefault(feature.room_id, feature)
                except Exception:
                    logging.exception("Room feature extraction failed for %s", target.name)

        if property_records:
            save_property_price_rows(property_records, output_dir)
            logging.info(
                "Saved %d price rows for %s",
                len(property_records),
                target.name,
            )

        if room_features_by_id:
            property_features = list(room_features_by_id.values())
            save_property_room_features(property_features, output_dir)
            room_feature_records.extend(property_features)
            logging.info(
                "Saved %d room feature records for %s",
                len(property_features),
                target.name,
            )

        if property_failure_records:
            append_property_failures(property_failure_records, output_dir)

    return page, records, room_feature_records, failure_records


def validate_and_report_run(run_dir: Path) -> None:
    """Validate the persisted run output and write a validation_report.json.

    Logs a clear pass/fail summary so post-run data-quality problems surface in
    the scrape log instead of being discovered later downstream.
    """

    report = validate_run_directory(run_dir)
    save_validation_report(report, run_dir / "validation_report.json")

    if report.is_valid:
        logging.info("Run output validation passed for %s", run_dir)
        return

    logging.warning(
        "Run output validation found %d issue(s) for %s",
        len(report.issues),
        run_dir,
    )
    for check, count in sorted(report.issue_counts_by_check().items()):
        logging.warning("Validation issues: %s=%d", check, count)


def build_and_save_modelling_table(run_dir: Path) -> int:
    """Build and persist the Layer 2 modelling table for a completed run."""

    from tourism_pricing_analytics.features.build_features import build_features_from_run

    rows = build_features_from_run(run_dir)
    save_jsonl_file(rows, run_dir / "modelling_table.jsonl")
    logging.info("Modelling table rows saved: %d", len(rows))
    return len(rows)


def run(
    playwright: Playwright,
    scraper_config: ScraperConfig,
    run_dir: Path,
    *,
    target_slice: list[PropertyTarget] | None = None,
    all_targets: list[PropertyTarget] | None = None,
    finalize_run: bool = True,
    worker_id: str | None = None,
    search_base_date: date | None = None,
) -> None:
    search_base_date = search_base_date or resolve_run_search_base_date(run_dir)
    browser = playwright.chromium.launch(
        headless=scraper_config.browser.headless,
        slow_mo=scraper_config.browser.slow_mo_ms,
    )

    try:
        context = browser.new_context(
            user_agent=scraper_config.browser.user_agent,
            viewport={
                "width": scraper_config.browser.viewport.width,
                "height": scraper_config.browser.viewport.height,
            },
        )
        page = context.new_page()

        all_properties = all_targets or scraper_config.properties
        requested_properties = target_slice or all_properties
        indexed_all_properties = indexed_targets(all_properties)
        indexed_requested_properties = select_indexed_targets(
            indexed_all_properties,
            requested_properties,
        )
        indexed_pending_properties = pending_indexed_targets(
            run_dir,
            indexed_requested_properties,
            scraper_config.lead_times,
            scraper_config.stay_lengths,
            search_base_date,
        )
        pending_properties = [item.target for item in indexed_pending_properties]
        skipped_count = len(indexed_requested_properties) - len(pending_properties)
        if skipped_count:
            logging.info(
                "Skipping %d completed properties based on persisted artifacts",
                skipped_count,
            )

        active_config = replace(scraper_config, properties=pending_properties)

        property_output_dirs = {
            item.target.url: create_property_output_dir(run_dir, item.index, item.target)
            for item in indexed_all_properties
        }

        for item in indexed_all_properties:
            logging.info(
                "Prepared property %d/%d output directory: %s",
                item.index,
                len(all_properties),
                property_output_dirs[item.target.url],
            )

        if worker_id is not None:
            logging.info(
                "%s scraping %d pending properties out of %d assigned",
                worker_id,
                len(pending_properties),
                len(indexed_requested_properties),
            )

        (
            page,
            room_inventory_records,
            property_feature_records,
            room_inventory_failures,
        ) = run_room_inventory_loop(
            context=context,
            page=page,
            scraper_config=active_config,
            property_output_dirs=property_output_dirs,
        )
        page, price_row_records, room_feature_records, price_row_failures = run_price_loop(
            context=context,
            page=page,
            scraper_config=active_config,
            property_output_dirs=property_output_dirs,
            search_base_date=search_base_date,
        )
        failure_records = room_inventory_failures + price_row_failures

        for target in scraper_config.properties:
            property_failures = [
                record for record in failure_records if record.property_url == target.url
            ]
            if property_failures:
                save_property_failures(property_failures, property_output_dirs[target.url])

        if finalize_run:
            artifact_counts = aggregate_run_artifacts(run_dir, indexed_all_properties)
            logging.info(
                "Room inventory records saved: %d",
                artifact_counts["room_inventory.jsonl"],
            )
            logging.info("Price row records saved: %d", artifact_counts["price_rows.jsonl"])
            logging.info(
                "Room feature records saved: %d",
                artifact_counts["room_features.jsonl"],
            )
            logging.info(
                "Property feature records saved: %d",
                artifact_counts["property_features.jsonl"],
            )
            logging.info("Failure records saved: %d", artifact_counts["failures.jsonl"])

            validate_and_report_run(run_dir)
            build_and_save_modelling_table(run_dir)
        else:
            logging.info("Worker run complete; final aggregation skipped")

        page = ensure_page(context, page)
        page.wait_for_timeout(scraper_config.timeouts.final_wait_ms)
    finally:
        logging.info("closing browser")
        browser.close()


def main() -> None:
    scraper_config = load_scraper_config()
    random.seed(scraper_config.seed)

    run_dir = create_run_dir(scraper_config.output_root)
    setup_logging(run_dir / "scrape_debug.log")
    search_base_date = resolve_run_search_base_date(run_dir)

    logging.info("Run output directory: %s", run_dir)
    logging.info("Search base date: %s", search_base_date.isoformat())
    logging.info("Starting scraper")
    logging.info("Configured property count: %d", len(scraper_config.properties))
    logging.info("Configured lead times: %s", scraper_config.lead_times)
    logging.info("Configured stay lengths: %s", scraper_config.stay_lengths)
    logging.info(
        "Default search config: adults=%d children=%d rooms=%d",
        scraper_config.default_search.group_adults,
        scraper_config.default_search.group_children,
        scraper_config.default_search.no_rooms,
    )

    with sync_playwright() as playwright:
        run(
            playwright,
            scraper_config,
            run_dir,
            search_base_date=search_base_date,
        )

    logging.info("Finished")
