#!/usr/bin/env python3
"""
search_click.py — Search a keyword on Google and click the first organic result.

Cross-platform (Linux + Windows + macOS). Uses Selenium with Chrome.
The Chrome driver is downloaded/matched automatically by webdriver-manager,
so you do NOT need to install chromedriver yourself.

Usage:
    python search_click.py "your keyword here"
    python search_click.py "python tutorials" --headless
    python search_click.py "news" --rank 2        # click the 2nd result instead of 1st

Note: Google discourages automated queries and may show a consent screen or a
CAPTCHA. The script tries to dismiss the consent screen automatically; if a
CAPTCHA appears, run without --headless and solve it manually.
"""

import argparse
import sys
import tempfile
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


def build_driver(headless: bool) -> webdriver.Chrome:
    """Create a cross-platform Chrome WebDriver instance."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    # Flags that improve stability across Linux/Windows and reduce bot fingerprinting noise.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--lang=en-US")
    # Dedicated throwaway profile so we don't collide with the user's everyday Chrome.
    options.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='clicker-chrome-')}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # webdriver-manager picks the right driver binary for this OS automatically.
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver


def dismiss_consent(driver) -> None:
    """Try to dismiss Google's cookie/consent dialog if it appears."""
    candidates = [
        (By.ID, "L2AGLb"),                                   # "Accept all" button id
        (By.XPATH, "//button[.//div[contains(text(),'Accept all')]]"),
        (By.XPATH, "//button[contains(., 'Accept all')]"),
        (By.XPATH, "//button[contains(., 'I agree')]"),
    ]
    for by, sel in candidates:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            time.sleep(1)
            return
        except (TimeoutException, NoSuchElementException):
            continue


def find_organic_results(driver):
    """Return a list of <a> elements that are real organic result links."""
    # Organic results live inside <div id="search">; each result title link sits in an <h3>.
    anchors = driver.find_elements(By.CSS_SELECTOR, "div#search a:has(h3)")
    if not anchors:
        # Fallback for browsers/versions that don't support :has in the engine query.
        anchors = []
        for h3 in driver.find_elements(By.CSS_SELECTOR, "div#search h3"):
            try:
                anchors.append(h3.find_element(By.XPATH, "./ancestor::a[1]"))
            except NoSuchElementException:
                continue

    results = []
    seen = set()
    for a in anchors:
        href = a.get_attribute("href") or ""
        # Skip Google-internal / ad redirect links; keep only real external destinations.
        if not href.startswith("http"):
            continue
        if "google.com" in href and "/url?" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        results.append(a)
    return results


def run(keyword: str, headless: bool, rank: int) -> int:
    driver = build_driver(headless)
    try:
        print(f"[*] Opening Google and searching for: {keyword!r}")
        driver.get("https://www.google.com/ncr")  # ncr = no country redirect
        dismiss_consent(driver)

        box = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.NAME, "q"))
        )
        box.clear()
        box.send_keys(keyword)
        box.submit()

        # Wait for the results container to render.
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#search"))
        )
        dismiss_consent(driver)
        time.sleep(1)

        results = find_organic_results(driver)
        if not results:
            print("[!] No organic results found. Google may have shown a CAPTCHA.")
            print("    Re-run without --headless and solve it manually.")
            return 2

        if rank < 1 or rank > len(results):
            print(f"[!] Only {len(results)} results found; cannot click rank {rank}.")
            return 2

        target = results[rank - 1]
        url = target.get_attribute("href")
        print(f"[*] Clicking result #{rank}: {url}")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
        time.sleep(0.5)
        target.click()

        # Give the destination page a moment to load, then report where we landed.
        time.sleep(3)
        print(f"[+] Landed on: {driver.current_url}")
        print(f"[+] Page title: {driver.title}")

        if not headless and sys.stdin.isatty():
            input("\nPress Enter to close the browser...")
        return 0

    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search a keyword on Google and click the first organic result."
    )
    parser.add_argument("keyword", help="The keyword/phrase to search for.")
    parser.add_argument(
        "--headless", action="store_true",
        help="Run without opening a visible browser window.",
    )
    parser.add_argument(
        "--rank", type=int, default=1,
        help="Which organic result to click (1 = first). Default: 1.",
    )
    args = parser.parse_args()
    return run(args.keyword, args.headless, args.rank)


if __name__ == "__main__":
    sys.exit(main())
