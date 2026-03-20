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


def save_element_dom(element, filename_prefix="opened"):
    outer_html = element.evaluate("el => el.outerHTML")
    filepath = SAVE_DIR / f"{filename_prefix}.html"
    filepath.write_text(outer_html, encoding="utf-8")
    print(f"Saved opened element DOM to: {filepath}")
    return filepath


def save_full_page_dom(page, filename="full_page_after_click.html"):
    filepath = SAVE_DIR / filename
    filepath.write_text(page.content(), encoding="utf-8")
    print(f"Saved full page DOM to: {filepath}")
    return filepath

# Found that the most reliable way to close the opened.
def click_left_edge_to_close(page):
    print("Closing overlay by clicking near the left edge of the page.")
    viewport = page.viewport_size or {"width": 1280, "height": 900}

    left_edge_x = random.randint(8, 25)
    left_edge_y = random.randint(
        max(80, int(viewport["height"] * 0.25)),
        max(120, int(viewport["height"] * 0.75))
    )

    # small natural movement before the closing click
    page.mouse.move(
        random.randint(40, 120),
        random.randint(100, viewport["height"] - 100),
        steps=random.randint(10, 25)
    )
    human_pause(0.15, 0.35)

    page.mouse.move(left_edge_x, left_edge_y, steps=random.randint(12, 30))
    human_pause(0.1, 0.25)

    page.mouse.click(left_edge_x, left_edge_y)
    human_pause(0.6, 1.1)

# Main function to click the trigger and capture the opened content or full page if no clear modal is detected.
def click_trigger_and_capture(page, trigger, idx):
    COMMON_OPENED_SELECTORS = [
        '[role="dialog"]',
        '[aria-modal="true"]',
        '.modal',
        '.popup',
        '.popover',
        '.drawer',
        '.panel',
        '.overlay',
        '.lightbox',
        '[class*="modal"]',
        '[class*="popup"]',
        '[class*="drawer"]',
        '[class*="overlay"]',
    ]

    print(f"\n--- Processing trigger {idx} ---")

    before_candidates = get_visible_candidates(page, COMMON_OPENED_SELECTORS)

    trigger.scroll_into_view_if_needed()
    human_pause()
    trigger.hover()
    human_pause(0.1, 0.3)
    trigger.click()

    human_pause(0.8, 1.5)

    opened = find_new_opened_element(page, before_candidates, COMMON_OPENED_SELECTORS, wait_ms=1500)

    if opened is None:
        print("No obvious modal/popup detected. Saving full page DOM instead.")
        save_full_page_dom(page, filename=f"full_page_after_click_{idx}.html")
        click_left_edge_to_close(page)
        return

    print("Detected opened element.")
    save_element_dom(opened, filename_prefix=f"opened_element_{idx}")
    save_full_page_dom(page, filename=f"full_page_after_click_{idx}.html")

    click_left_edge_to_close(page)



url = 'https://www.booking.com/hotel/gr/solimar-aquamarine-platanias-chania.en-gb.html?'

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        slow_mo=75,
    )

    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )

    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    human_pause(1.0, 2.0)
    noisy_scroll(page)

    rd_buttons = page.locator('[href^="#RD"]')
    count = rd_buttons.count()
    print(f"Found {count} RD buttons")

    for i in range(count):
        try:
            trigger = rd_buttons.nth(i)
            if trigger.is_visible():
                click_trigger_and_capture(page, trigger, i)
        except Exception as e:
            print(f"Error on trigger {i}: {e}")

    page.wait_for_timeout(3000)
    browser.close()
  

