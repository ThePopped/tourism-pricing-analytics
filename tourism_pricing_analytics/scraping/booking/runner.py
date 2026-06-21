import logging
import random
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from tourism_pricing_analytics.scraping.booking.browser import ensure_page, navigate_to_page
from tourism_pricing_analytics.scraping.booking.config import load_scraper_config
from tourism_pricing_analytics.scraping.booking.failures import (
    PageFailureClassification,
    classify_playwright_page_failure,
)
from tourism_pricing_analytics.scraping.booking.io import (
    create_property_output_dir,
    create_run_dir,
    failure_records_to_dicts,
    price_row_records_to_dicts,
    room_inventory_records_to_dicts,
    save_full_page_dom,
    save_jsonl_file,
    save_property_failures,
    save_property_price_rows,
    save_property_room_inventory,
    save_validation_report,
    setup_logging,
)
from tourism_pricing_analytics.scraping.booking.models import (
    FailureCategory,
    PriceRowRecord,
    RoomInventoryRecord,
    ScrapeFailureRecord,
    ScrapeStage,
    ScraperConfig,
)
from tourism_pricing_analytics.scraping.booking.parsing import (
    extract_price_rows,
    extract_room_inventory,
)
from tourism_pricing_analytics.scraping.booking.urls import (
    build_date_window,
    build_dated_url,
    build_room_inventory_url,
)
from tourism_pricing_analytics.scraping.booking.validation import validate_run_directory


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


def run_room_inventory_loop(
    context: BrowserContext,
    page: Page,
    scraper_config: ScraperConfig,
    property_output_dirs: dict[str, Path],
) -> tuple[Page | None, list[RoomInventoryRecord], list[ScrapeFailureRecord]]:
    records: list[RoomInventoryRecord] = []
    failure_records: list[ScrapeFailureRecord] = []

    for target in scraper_config.properties:
        property_url = build_room_inventory_url(target.url)
        output_dir = property_output_dirs[target.url]
        page = ensure_page(context, page)
        status_code: int | None = None
        navigation_completed = False

        try:
            status_code = navigate_to_page(page, property_url, scraper_config, scroll_page=True)
            navigation_completed = True
            captured_at = datetime.now().isoformat(timespec="seconds")
            property_records = extract_room_inventory(page, target, property_url, captured_at)
        except Exception as exc:
            captured_at = datetime.now().isoformat(timespec="seconds")
            logging.exception("Room inventory extraction failed for %s", target.name)
            classification = classify_current_page_failure(
                page,
                requested_url=property_url,
                expected_selector=ROOM_INVENTORY_SELECTOR,
                fallback_selectors=ROOM_INVENTORY_FALLBACK_SELECTORS,
                status_code=status_code,
                default_category="extraction_error" if navigation_completed else "navigation_error",
                default_reason="Room inventory navigation or extraction raised an exception.",
            )
            filename = f"room_inventory_{classification.category}.html"
            snapshot_filename = save_failure_snapshot(page, output_dir, filename)
            failure_records.append(
                build_failure_record(
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
            )
            page = None
            continue

        records.extend(property_records)

        if not property_records:
            classification = classify_current_page_failure(
                page,
                requested_url=property_url,
                expected_selector=ROOM_INVENTORY_SELECTOR,
                fallback_selectors=ROOM_INVENTORY_FALLBACK_SELECTORS,
                status_code=status_code,
                default_category="selector_drift",
                default_reason="No room inventory records were extracted.",
            )
            logging.warning(
                "No room inventory extracted for %s; category=%s",
                target.name,
                classification.category,
            )
            filename = f"room_inventory_{classification.category}.html"
            snapshot_filename = save_failure_snapshot(page, output_dir, filename)
            failure_records.append(
                build_failure_record(
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
            )
            continue

        save_property_room_inventory(property_records, output_dir)
        logging.info(
            "Saved %d room inventory records for %s",
            len(property_records),
            target.name,
        )

    return page, records, failure_records


def run_price_loop(
    context: BrowserContext,
    page: Page | None,
    scraper_config: ScraperConfig,
    property_output_dirs: dict[str, Path],
) -> tuple[Page | None, list[PriceRowRecord], list[ScrapeFailureRecord]]:
    records: list[PriceRowRecord] = []
    failure_records: list[ScrapeFailureRecord] = []

    for target in scraper_config.properties:
        output_dir = property_output_dirs[target.url]
        property_records: list[PriceRowRecord] = []

        for lead_time_days in scraper_config.lead_times:
            for stay_length_days in scraper_config.stay_lengths:
                checkin, checkout = build_date_window(lead_time_days, stay_length_days)
                dated_url = build_dated_url(
                    target.url,
                    checkin=checkin,
                    checkout=checkout,
                    default_search=scraper_config.default_search,
                )
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
                    logging.exception(
                        "Price extraction failed for %s, lead_time=%d, stay_length=%d",
                        target.name,
                        lead_time_days,
                        stay_length_days,
                    )
                    captured_at = datetime.now().isoformat(timespec="seconds")
                    classification = classify_current_page_failure(
                        page,
                        requested_url=dated_url,
                        expected_selector=PRICE_ROW_SELECTOR,
                        fallback_selectors=PRICE_ROW_FALLBACK_SELECTORS,
                        status_code=status_code,
                        default_category="extraction_error" if navigation_completed else "navigation_error",
                        default_reason="Price navigation or extraction raised an exception.",
                    )
                    filename = (
                        f"price_rows_{classification.category}_lead_{lead_time_days:03d}"
                        f"_stay_{stay_length_days:03d}.html"
                    )
                    snapshot_filename = save_failure_snapshot(page, output_dir, filename)
                    failure_records.append(
                        build_failure_record(
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
                    )
                    page = None
                    continue

                records.extend(price_rows)
                property_records.extend(price_rows)

                if not price_rows:
                    classification = classify_current_page_failure(
                        page,
                        requested_url=dated_url,
                        expected_selector=PRICE_ROW_SELECTOR,
                        fallback_selectors=PRICE_ROW_FALLBACK_SELECTORS,
                        status_code=status_code,
                        default_category="selector_drift",
                        default_reason="No price rows were extracted.",
                    )
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
                    failure_records.append(
                        build_failure_record(
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
                    )

        if property_records:
            save_property_price_rows(property_records, output_dir)
            logging.info(
                "Saved %d price rows for %s",
                len(property_records),
                target.name,
            )

    return page, records, failure_records


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


def run(playwright: Playwright, scraper_config: ScraperConfig, run_dir: Path) -> None:
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

        property_output_dirs = {
            target.url: create_property_output_dir(run_dir, index, target)
            for index, target in enumerate(scraper_config.properties, start=1)
        }

        for index, target in enumerate(scraper_config.properties, start=1):
            logging.info(
                "Prepared property %d/%d output directory: %s",
                index,
                len(scraper_config.properties),
                property_output_dirs[target.url],
            )

        page, room_inventory_records, room_inventory_failures = run_room_inventory_loop(
            context=context,
            page=page,
            scraper_config=scraper_config,
            property_output_dirs=property_output_dirs,
        )
        page, price_row_records, price_row_failures = run_price_loop(
            context=context,
            page=page,
            scraper_config=scraper_config,
            property_output_dirs=property_output_dirs,
        )
        failure_records = room_inventory_failures + price_row_failures

        save_jsonl_file(
            room_inventory_records_to_dicts(room_inventory_records),
            run_dir / "room_inventory.jsonl",
        )
        save_jsonl_file(
            price_row_records_to_dicts(price_row_records),
            run_dir / "price_rows.jsonl",
        )
        save_jsonl_file(
            failure_records_to_dicts(failure_records),
            run_dir / "failures.jsonl",
        )
        for target in scraper_config.properties:
            property_failures = [
                record for record in failure_records if record.property_url == target.url
            ]
            if property_failures:
                save_property_failures(property_failures, property_output_dirs[target.url])

        logging.info("Room inventory records saved: %d", len(room_inventory_records))
        logging.info("Price row records saved: %d", len(price_row_records))
        logging.info("Failure records saved: %d", len(failure_records))

        validate_and_report_run(run_dir)

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

    logging.info("Run output directory: %s", run_dir)
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
        run(playwright, scraper_config, run_dir)

    logging.info("Finished")
