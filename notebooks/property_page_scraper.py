import random
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


SAVE_DIR = Path("saved_dom")
SAVE_DIR.mkdir(exist_ok=True)

# Basic script to interact with a property page, click on "Read more about the property" buttons,
# and capture the DOM of the opened modal/popup or the full page if no clear modal is detected.

def human_pause(a=0.2, b=0.7):
    time.sleep(random.uniform(a, b))


def noisy_scroll(page, rounds=2):
    for _ in range(rounds):
        page.mouse.wheel(0, random.randint(120, 450))
        human_pause(0.2, 0.5)


def get_visible_candidates(page, selectors):
    visible = []

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()

        for i in range(count):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    outer_html = el.evaluate("el => el.outerHTML")
                    visible.append({
                        "selector": selector,
                        "index": i,
                        "outer_html": outer_html,
                    })
            except Exception:
                pass

    return visible


def find_new_opened_element(page, before_candidates, selectors, wait_ms=2000):
    page.wait_for_timeout(wait_ms)
    before_html_set = {item["outer_html"] for item in before_candidates}

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()

        for i in range(count):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    outer_html = el.evaluate("el => el.outerHTML")
                    if outer_html not in before_html_set:
                        return el
            except Exception:
                pass

    return None
