#!/usr/bin/env python3
"""
interactive_clicker.py — Interactive Google result clicker.

Flow:
  1. Opens Google and (optionally) searches the keyword you pass.
  2. Injects an overlay: hover ANY organic result and a blue "Click xN" box
     appears over it.
  3. Click that box -> the link is opened/clicked N times (default 10), each in
     a new tab so the Google results page stays put and the overlay keeps working.

Cross-platform (Linux / Windows / macOS). Must run with a VISIBLE browser
(do not use headless) because you interact with it by hand.

Usage:
    python interactive_clicker.py "python tutorials"
    python interactive_clicker.py "news" --times 5
    python interactive_clicker.py "news" --delay 3      # 3s between clicks (default 5)
    python interactive_clicker.py            # opens Google, type the search yourself
"""

import argparse
import csv
import json
import os
import random
import sys
import tempfile
import threading
import time
from datetime import datetime
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
)
from webdriver_manager.chrome import ChromeDriverManager


# JavaScript injected into the Google results page. It draws a clickable box
# over whichever organic link you hover, and records your choice in
# window.__selectedHref so the Python side can act on it.
OVERLAY_JS = r"""
(function (N, LABEL) {
  if (window.__clickerInstalled) { return; }
  window.__clickerInstalled = true;
  window.__selectedHref = null;
  window.__clickN = N;
  var BOX_LABEL = LABEL || ('Click ×' + N);

  var box = document.createElement('div');
  box.textContent = BOX_LABEL;
  Object.assign(box.style, {
    position: 'absolute', zIndex: 2147483647, background: '#1a73e8',
    color: '#fff', padding: '11px 22px', borderRadius: '9px',
    font: 'bold 17px/1.2 Arial, sans-serif', cursor: 'pointer', display: 'none',
    boxShadow: '0 3px 12px rgba(0,0,0,.4)', userSelect: 'none'
  });
  document.body.appendChild(box);

  // Live progress badge pinned to the top-right corner of the page.
  var prog = document.createElement('div');
  prog.id = '__clickProgress';
  Object.assign(prog.style, {
    position: 'fixed', top: '14px', right: '14px', zIndex: 2147483647,
    background: '#0b8043', color: '#fff', padding: '10px 18px',
    borderRadius: '9px', font: 'bold 16px/1.2 Arial, sans-serif',
    display: 'none', boxShadow: '0 3px 12px rgba(0,0,0,.4)', userSelect: 'none'
  });
  document.body.appendChild(prog);

  // Stop button pinned just under the progress badge. Clicking it asks the
  // Python side to abort the remaining clicks for the current link.
  var stopBtn = document.createElement('div');
  stopBtn.textContent = '■ Stop';
  Object.assign(stopBtn.style, {
    position: 'fixed', top: '54px', right: '14px', zIndex: 2147483647,
    background: '#d93025', color: '#fff', padding: '10px 18px',
    borderRadius: '9px', font: 'bold 16px/1.2 Arial, sans-serif',
    cursor: 'pointer', display: 'none',
    boxShadow: '0 3px 12px rgba(0,0,0,.4)', userSelect: 'none'
  });
  document.body.appendChild(stopBtn);
  stopBtn.addEventListener('click', function () {
    window.__stopRequested = true;
    stopBtn.textContent = 'Stopping…';
  });

  window.__stopRequested = false;
  // Called by Python when a click run starts: reset the flag, reveal the
  // Stop button so the user can abort at any point during the run.
  window.__beginRun = function () {
    window.__stopRequested = false;
    stopBtn.textContent = '■ Stop';
    stopBtn.style.display = 'block';
  };
  window.__setProgress = function (i, n) {
    prog.textContent = 'Click ' + i + ' / ' + n;
    prog.style.display = 'block';
  };
  // Free-form badge text (used by keyword auto-click mode).
  window.__setBadge = function (text) {
    prog.textContent = text;
    prog.style.display = 'block';
  };
  window.__hideProgress = function () {
    prog.style.display = 'none';
    stopBtn.style.display = 'none';
  };

  var currentHref = null;
  var hideTimer = null;

  function isInternal(host) {
    return /(^|\.)google\.[a-z.]+$/.test(host) || /(^|\.)gstatic\.com$/.test(host);
  }

  // ALL real links anywhere on the page (top to bottom), minus Google's own
  // navigation links and minus sponsored/ad links.
  function clickableAnchors() {
    return Array.prototype.slice
      .call(document.querySelectorAll('a[href]'))
      .filter(function (a) {
        var href = a.href || '';
        if (href.indexOf('http') !== 0) { return false; }
        var host;
        try { host = new URL(href).hostname; } catch (e) { return false; }
        if (isInternal(host)) { return false; }   // skip google's own links
        var r = a.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) { return false; }  // skip hidden
        return true;
      });
  }

  function showBoxFor(a) {
    var r = a.getBoundingClientRect();
    // Default above the link; if it's near the top of the page, show below it.
    var top = (r.top < 34) ? (window.scrollY + r.bottom + 4)
                           : (window.scrollY + r.top - 32);
    box.style.top = top + 'px';
    box.style.left = (window.scrollX + r.left) + 'px';
    box.style.display = 'block';
    currentHref = a.href;
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
  }

  function scheduleHide() {
    hideTimer = setTimeout(function () { box.style.display = 'none'; }, 400);
  }

  function attach() {
    clickableAnchors().forEach(function (a) {
      if (a.__hooked) { return; }
      a.__hooked = true;
      a.addEventListener('mouseenter', function () { showBoxFor(a); });
      a.addEventListener('mouseleave', scheduleHide);
    });
  }

  box.addEventListener('mouseenter', function () {
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
  });
  box.addEventListener('mouseleave', scheduleHide);
  box.addEventListener('click', function (e) {
    e.preventDefault();
    e.stopPropagation();
    if (!currentHref) { return; }
    window.__selectedHref = currentHref;
    box.textContent = 'Selected ✓';
    setTimeout(function () {
      box.textContent = BOX_LABEL;
      box.style.display = 'none';
    }, 600);
  });

  attach();
  // Google rewrites results dynamically; re-hook periodically.
  setInterval(attach, 1500);
})(arguments[0], arguments[1]);
"""


# A pool of realistic desktop + mobile user agents. Each click picks one that
# differs from the previous click, so every request looks like a fresh client.
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Safari on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    # Chrome on Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    # Samsung Internet on Android
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
    # Chrome on older Windows
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def pick_user_agent(previous: str | None) -> str:
    """Return a user agent different from *previous* (when possible)."""
    if len(USER_AGENTS) > 1 and previous:
        choices = [ua for ua in USER_AGENTS if ua != previous]
        return random.choice(choices)
    return random.choice(USER_AGENTS)


LOG_FIELDS = ["timestamp", "event", "keyword", "url", "click", "total",
              "user_agent", "detail"]


class CsvLogger:
    """Appends every event to a CSV file (header written once)."""

    def __init__(self, path: str):
        self.path = path
        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=LOG_FIELDS)
        if new_file:
            self._writer.writeheader()
            self._fh.flush()

    def log(self, event: str, keyword: str = "", url: str = "",
            click="", total="", user_agent: str = "", detail: str = "") -> None:
        self._writer.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event, "keyword": keyword, "url": url,
            "click": click, "total": total, "user_agent": user_agent,
            "detail": detail,
        })
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,950")
    options.add_argument("--lang=en-US")
    # Use a dedicated, throwaway profile so we never collide with the user's
    # everyday Chrome (which locks the default profile).
    options.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='clicker-chrome-')}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver


def dismiss_consent(driver) -> None:
    for by, sel in [
        (By.ID, "L2AGLb"),
        (By.XPATH, "//button[contains(., 'Accept all')]"),
        (By.XPATH, "//button[contains(., 'I agree')]"),
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            time.sleep(0.5)
            return
        except (TimeoutException, NoSuchElementException):
            continue


def do_search(driver, keyword: str) -> None:
    box = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.NAME, "q")))
    box.clear()
    box.send_keys(keyword)
    box.submit()
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div#search"))
    )
    dismiss_consent(driver)


def _stop_requested(driver) -> bool:
    """True if the user pressed the on-page Stop button."""
    try:
        return bool(driver.execute_script("return !!window.__stopRequested"))
    except WebDriverException:
        return False


def click_link_n_times(driver, google_tab: str, url: str, times: int,
                       delay: float, logger: "CsvLogger | None" = None) -> bool:
    """Open *url* up to *times* times. Returns True if the user pressed Stop."""
    print(f"    -> opening {times}x (delay {delay}s between clicks): {url}")
    if logger:
        logger.log("run_start", url=url, total=times,
                   detail=f"delay={delay}s")
    # Reset the stop flag and reveal the Stop button for this run.
    try:
        driver.execute_script("window.__beginRun && window.__beginRun();")
    except WebDriverException:
        pass
    completed = 0
    stopped = False
    last_ua = None
    for i in range(times):
        if _stop_requested(driver):
            stopped = True
            break
        ua = pick_user_agent(last_ua)
        last_ua = ua
        driver.switch_to.new_window("tab")
        click_status = "ok"
        try:
            # Spoof a fresh user agent for THIS tab/navigation via CDP.
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride", {"userAgent": ua})
            driver.get(url)
            time.sleep(1.2)
        except WebDriverException as exc:
            click_status = f"error:{exc.__class__.__name__}"
            print(f"       click {i + 1}: error ({exc.__class__.__name__})")
        finally:
            driver.close()
            driver.switch_to.window(google_tab)
        completed = i + 1
        ua_short = ua.split(") ", 1)[0] + ")" if ")" in ua else ua[:40]
        print(f"       click {i + 1}/{times} done  [UA: {ua_short}]")
        if logger:
            logger.log("click", url=url, click=i + 1, total=times,
                       user_agent=ua, detail=click_status)
        # Update the on-page top-right counter back on the Google tab.
        try:
            driver.execute_script(
                "window.__setProgress && window.__setProgress(arguments[0], arguments[1]);",
                i + 1, times)
        except WebDriverException:
            pass
        # Wait the configured threshold before the next click (skip after last).
        # Poll the stop flag in small slices so Stop reacts within ~0.2s.
        if i < times - 1 and delay > 0:
            waited = 0.0
            while waited < delay:
                if _stop_requested(driver):
                    break
                time.sleep(0.2)
                waited += 0.2
    stopped = stopped or _stop_requested(driver)
    if stopped:
        print(f"    -> stopped by user after {completed}/{times} click(s)")
    if logger:
        logger.log("stopped" if stopped else "run_done", url=url,
                   click=completed, total=times)
    # Leave the final count visible briefly, then hide it.
    time.sleep(1.5)
    try:
        driver.execute_script("window.__hideProgress && window.__hideProgress();")
    except WebDriverException:
        pass
    return stopped


def run(keyword: str | None, times: int, delay: float, log_path: str) -> int:
    driver = build_driver()
    logger = CsvLogger(log_path)
    print(f"[+] Logging to {os.path.abspath(log_path)}")
    logger.log("session_start", keyword=keyword or "",
               total=times, detail=f"delay={delay}s")
    google_tab = None
    try:
        driver.get("https://www.google.com/ncr")
        dismiss_consent(driver)
        google_tab = driver.current_window_handle

        if keyword:
            print(f"[*] Searching for: {keyword!r}")
            logger.log("search", keyword=keyword)
            do_search(driver, keyword)
        else:
            print("[*] Google is open — type your search in the browser window.")
            # Wait until a results page exists.
            WebDriverWait(driver, 300).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search"))
            )

        driver.execute_script(OVERLAY_JS, times)
        print(f"[+] Overlay active. Hover any result, then click the blue "
              f"'Click x{times}' box.")
        print("[+] Close the browser window to quit.")

        # Poll: re-inject overlay if the page changed, and act on selections.
        while True:
            try:
                # If the user ran a new search, the results page reloads and the
                # overlay flag is gone — re-inject it.
                installed = driver.execute_script("return !!window.__clickerInstalled")
                if not installed:
                    driver.execute_script(OVERLAY_JS, times)

                href = driver.execute_script("return window.__selectedHref")
                if href:
                    driver.execute_script("window.__selectedHref = null;")
                    print(f"[*] Selected: {href}")
                    logger.log("selected", url=href, total=times)
                    stopped = click_link_n_times(driver, google_tab, href,
                                                 times, delay, logger)
                    if stopped:
                        # Return to Google so the user can search a new keyword.
                        print("[*] Stopped — reopening Google to search again.")
                        logger.log("reopen_google")
                        driver.get("https://www.google.com/ncr")
                        dismiss_consent(driver)
                        google_tab = driver.current_window_handle
                        print("[+] Type a new search in the browser window.")
                    else:
                        print("[+] Done. Hover another result or close the window.")
            except WebDriverException:
                # Window/browser was closed by the user.
                print("[*] Browser closed — exiting.")
                logger.log("browser_closed")
                break
            time.sleep(0.5)
        return 0
    finally:
        logger.log("session_end")
        logger.close()
        try:
            driver.quit()
        except WebDriverException:
            pass


# Injected into a fresh Google results tab: find the result link whose
# host+path matches the locked target and click it (opening it in that tab).
# Returns the clicked href, or null if the target isn't on this results page.
FIND_AND_CLICK_JS = r"""
(function (target) {
  function norm(u) {
    try {
      var x = new URL(u);
      return (x.hostname + x.pathname.replace(/\/+$/, '')).toLowerCase();
    } catch (e) { return ''; }
  }
  var want = norm(target);
  if (!want) { return null; }
  var as = document.querySelectorAll('a[href]');
  for (var i = 0; i < as.length; i++) {
    if (norm(as[i].href) === want) {
      as[i].scrollIntoView({ block: 'center' });
      as[i].click();
      return as[i].href;
    }
  }
  return null;
})(arguments[0]);
"""

BATCH_SIZE = 10


def _wait_loaded(driver, timeout: float) -> None:
    """Block until the active tab reports document.readyState == 'complete'."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete")
    except (TimeoutException, WebDriverException):
        pass


def run_keyword_batch(driver, google_tab: str, keyword: str, target: str,
                      delay: float, logger: CsvLogger, batch_no: int,
                      clicks) -> int:
    """Open BATCH_SIZE search tabs for *keyword* as fast as possible, then go
    tab by tab: click the matching target, wait for it to fully load, close the
    tab, move on. Returns clicks landed this batch."""
    search_url = "https://www.google.com/search?q=" + quote_plus(keyword)
    handles = []
    last_ua = None
    # 1) Open all tabs quickly — navigate via JS so we DON'T block on load.
    for i in range(BATCH_SIZE):
        ua = pick_user_agent(last_ua)
        last_ua = ua
        driver.switch_to.new_window("tab")
        try:
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride", {"userAgent": ua})
        except WebDriverException:
            pass
        try:
            # Fire the navigation and return immediately (no page-load wait).
            driver.execute_script("window.location.href = arguments[0];",
                                  search_url)
        except WebDriverException:
            pass
        handles.append((driver.current_window_handle, ua))
    # 2) Process each tab one by one: click target -> wait full load -> close.
    landed = 0
    first = True
    for (h, ua) in handles:
        try:
            driver.switch_to.window(h)
        except WebDriverException:
            continue
        # Make sure the results page is ready before searching for the link.
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search")))
        except (TimeoutException, WebDriverException):
            pass
        if first:
            dismiss_consent(driver)
            first = False
        try:
            href = driver.execute_script(FIND_AND_CLICK_JS, target)
        except WebDriverException:
            href = None
        if href:
            landed += 1
            clicks[0] += 1
            # Wait until the opened target page has FULLY loaded, then close.
            _wait_loaded(driver, 30)
            print(f"       batch {batch_no} click {landed}: opened {href}")
            logger.log("kw_click", keyword=keyword, url=href,
                       click=clicks[0], total=batch_no, user_agent=ua,
                       detail=f"batch{batch_no}")
        else:
            logger.log("kw_miss", keyword=keyword, url=target,
                       total=batch_no, user_agent=ua,
                       detail=f"batch{batch_no}:not_found")
        # Close this tab and move to the next one.
        try:
            driver.close()
        except WebDriverException:
            pass
    driver.switch_to.window(google_tab)
    return landed


def run_keyword_mode(keyword: str | None, delay: float, log_path: str) -> int:
    """Lock a target result for *keyword*, then repeatedly open batches of
    BATCH_SIZE search tabs and click that target until the user presses Stop."""
    if not keyword:
        print("[!] Keyword mode needs a keyword.")
        return 1
    driver = build_driver()
    logger = CsvLogger(log_path)
    print(f"[+] Logging to {os.path.abspath(log_path)}")
    logger.log("kw_session_start", keyword=keyword, detail=f"delay={delay}s")
    try:
        driver.get("https://www.google.com/ncr")
        dismiss_consent(driver)
        google_tab = driver.current_window_handle
        print(f"[*] Searching for: {keyword!r}")
        logger.log("search", keyword=keyword)
        do_search(driver, keyword)
        driver.execute_script(OVERLAY_JS, 1, "✓ Use this link")
        print("[*] Refine the search if you like. When you see the result you "
              "want, hover it and click the blue '✓ Use this link' box.")

        # Phase 1: let the user browse/re-search until they lock a target.
        target = None
        while target is None:
            try:
                if not driver.execute_script("return !!window.__clickerInstalled"):
                    driver.execute_script(OVERLAY_JS, 1, "✓ Use this link")
                href = driver.execute_script("return window.__selectedHref")
                if href:
                    driver.execute_script("window.__selectedHref = null;")
                    target = href
            except WebDriverException:
                print("[*] Browser closed — exiting.")
                logger.log("browser_closed")
                return 0
            time.sleep(0.4)

        print(f"[*] Target locked: {target}")
        logger.log("kw_target", keyword=keyword, url=target)

        # Phase 2: batch loop until Stop.
        try:
            driver.execute_script("window.__beginRun && window.__beginRun();")
        except WebDriverException:
            pass
        clicks = [0]
        batch = 0
        while True:
            if _stop_requested(driver):
                break
            batch += 1
            try:
                driver.execute_script(
                    "window.__setBadge && window.__setBadge(arguments[0]);",
                    f"Batch {batch} • {clicks[0]} opens")
            except WebDriverException:
                print("[*] Browser closed — exiting.")
                logger.log("browser_closed")
                return 0
            print(f"[*] Batch {batch}: opening {BATCH_SIZE} search tabs…")
            try:
                landed = run_keyword_batch(driver, google_tab, keyword, target,
                                           delay, logger, batch, clicks)
            except WebDriverException:
                print("[*] Browser closed — exiting.")
                logger.log("browser_closed")
                return 0
            print(f"[+] Batch {batch}: {landed}/{BATCH_SIZE} opened "
                  f"(total {clicks[0]}).")
            try:
                driver.execute_script(
                    "window.__setBadge && window.__setBadge(arguments[0]);",
                    f"Batch {batch} done • {clicks[0]} opens")
            except WebDriverException:
                break

        print(f"[*] Stopped after {batch} batch(es), {clicks[0]} opens.")
        logger.log("kw_stopped", keyword=keyword, click=clicks[0], total=batch)
        try:
            driver.execute_script("window.__hideProgress && window.__hideProgress();")
        except WebDriverException:
            pass
        # Keep the window open until the user closes it.
        print("[+] Done. Close the browser window to finish.")
        while True:
            try:
                driver.execute_script("return 1")
            except WebDriverException:
                break
            time.sleep(0.5)
        return 0
    finally:
        logger.log("kw_session_end")
        logger.close()
        try:
            driver.quit()
        except WebDriverException:
            pass


CONFIG_FILE = "clicker_config.json"
DEFAULT_CONFIG = {
    "times": 10,
    "delay": 5.0,
    "log": "click_log.csv",
    "keyword": "",   # blank = type the search by hand in the browser
}


def load_config(path: str) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(path: str, cfg: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        print(f"[+] Settings saved to {os.path.abspath(path)}")
    except OSError as exc:
        print(f"[!] Could not save settings: {exc}")


def _prompt(label: str, current) -> str:
    raw = input(f"  {label} [{current}]: ").strip()
    return raw


def settings_menu(cfg: dict) -> None:
    while True:
        print("\n--- Settings ---")
        print(f"  1) Default clicks per link ... {cfg['times']}")
        print(f"  2) Delay between clicks (s) .. {cfg['delay']}")
        print(f"  3) Default keyword ........... "
              f"{cfg['keyword'] or '(type manually)'}")
        print(f"  4) Log file .................. {cfg['log']}")
        print("  5) Back")
        choice = input("Select: ").strip()
        if choice == "1":
            raw = _prompt("Clicks per link", cfg["times"])
            if raw:
                try:
                    cfg["times"] = max(1, int(raw))
                except ValueError:
                    print("  [!] Enter a whole number.")
        elif choice == "2":
            raw = _prompt("Delay seconds", cfg["delay"])
            if raw:
                try:
                    cfg["delay"] = max(0.0, float(raw))
                except ValueError:
                    print("  [!] Enter a number.")
        elif choice == "3":
            raw = _prompt("Keyword (blank to clear)", cfg["keyword"])
            cfg["keyword"] = raw
        elif choice == "4":
            raw = _prompt("Log file path", cfg["log"])
            if raw:
                cfg["log"] = raw
        elif choice == "5":
            save_config(CONFIG_FILE, cfg)
            return
        else:
            print("  [!] Pick 1-5.")


def format_logs(log_path: str, tail: int = 50) -> str:
    """Return a compact text view of the last *tail* log entries."""
    if not os.path.exists(log_path):
        return "(no log file yet — start Chrome and click something first)"
    try:
        with open(log_path, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
    except OSError as exc:
        return f"[!] Could not read log: {exc}"
    if len(rows) <= 1:
        return "(log is empty)"
    header, data = rows[0], rows[1:]
    shown = data[-tail:]
    idx = {name: header.index(name) for name in header}

    def cell(row, name):
        return row[idx[name]] if name in idx and idx[name] < len(row) else ""

    lines = []
    if len(data) > tail:
        lines.append(f"... showing last {tail} of {len(data)} entries ...")
    for r in shown:
        ts = cell(r, "timestamp")[11:]
        ev = cell(r, "event")
        click, total = cell(r, "click"), cell(r, "total")
        cnt = f"{click}/{total}" if click and total else ""
        target = cell(r, "url") or cell(r, "keyword")
        lines.append(f"{ts:<9} {ev:<14} {cnt:<7} {target}")
    return "\n".join(lines)


def show_logs(log_path: str, tail: int = 25) -> None:
    print(f"\n--- Logs ({os.path.abspath(log_path)}) ---")
    for line in format_logs(log_path, tail).splitlines():
        print(f"  {line}")


def terminal_menu(cfg: dict) -> int:
    """Text-based fallback menu (used when tkinter is unavailable)."""
    while True:
        print("\n========= Interactive Clicker =========")
        print(f"  clicks={cfg['times']}  delay={cfg['delay']}s  "
              f"keyword={cfg['keyword'] or '(manual)'}  log={cfg['log']}")
        print("  1) Start Chrome (normal)")
        print("  2) Start Chrome (keyword auto-click)")
        print("  3) See logs")
        print("  4) Settings (delay, default clicks, etc.)")
        print("  5) Exit")
        try:
            choice = input("Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[*] Bye.")
            return 0
        if choice == "1":
            try:
                run(cfg["keyword"] or None, cfg["times"], cfg["delay"],
                    cfg["log"])
            except KeyboardInterrupt:
                print("\n[*] Interrupted — back to menu.")
        elif choice == "2":
            kw = cfg["keyword"] or input("  Keyword: ").strip()
            if kw:
                cfg["keyword"] = kw
                try:
                    run_keyword_mode(kw, cfg["delay"], cfg["log"])
                except KeyboardInterrupt:
                    print("\n[*] Interrupted — back to menu.")
            else:
                print("  [!] Keyword required.")
        elif choice == "3":
            show_logs(cfg["log"])
        elif choice == "4":
            settings_menu(cfg)
        elif choice == "5":
            print("[*] Bye.")
            return 0
        else:
            print("  [!] Pick 1-5.")


def launch_gui(cfg: dict) -> int:
    """Native desktop launcher: Open Chrome / Logs / Settings / Exit."""
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, simpledialog

    session = {"active": False}

    root = tk.Tk()
    root.title("Interactive Clicker")
    root.geometry("440x520")
    root.configure(bg="#1f2937")

    tk.Label(root, text="Interactive Clicker", font=("Arial", 20, "bold"),
             fg="#ffffff", bg="#1f2937").pack(pady=(22, 4))
    summary = tk.StringVar()
    tk.Label(root, textvariable=summary, font=("Arial", 10),
             fg="#9ca3af", bg="#1f2937").pack(pady=(0, 6))
    status = tk.StringVar(value="Ready.")
    tk.Label(root, textvariable=status, font=("Arial", 10, "italic"),
             fg="#34d399", bg="#1f2937").pack(pady=(0, 14))

    def refresh_summary():
        summary.set(f"clicks={cfg['times']}   delay={cfg['delay']}s   "
                    f"keyword={cfg['keyword'] or '(type manually)'}")

    def styled(text, color, command):
        b = tk.Button(root, text=text, font=("Arial", 13, "bold"),
                      fg="#ffffff", bg=color, activebackground=color,
                      relief="flat", width=26, height=2, command=command,
                      cursor="hand2")
        b.pack(pady=6)
        return b

    def _run_session(target_fn, busy_msg):
        """Run a blocking browser session in a worker thread, toggling the
        Open buttons so only one session runs at a time."""
        if session["active"]:
            messagebox.showinfo("Busy", "A Chrome session is already running.")
            return
        session["active"] = True
        status.set(busy_msg)
        open_btn.config(state="disabled")
        kw_btn.config(state="disabled")

        def worker():
            try:
                target_fn()
            except Exception as exc:  # surface, don't crash the GUI
                root.after(0, lambda: messagebox.showerror(
                    "Error", f"{exc.__class__.__name__}: {exc}"))
            finally:
                session["active"] = False
                root.after(0, lambda: (status.set("Ready."),
                                       open_btn.config(state="normal"),
                                       kw_btn.config(state="normal")))

        threading.Thread(target=worker, daemon=True).start()

    def open_chrome():
        _run_session(
            lambda: run(cfg["keyword"] or None, cfg["times"], cfg["delay"],
                        cfg["log"]),
            "Chrome session running… (close the browser to return)")

    def open_chrome_keyword():
        if session["active"]:
            messagebox.showinfo("Busy", "A Chrome session is already running.")
            return
        kw = simpledialog.askstring(
            "Keyword auto-click",
            "Keyword to search and auto-click:",
            initialvalue=cfg["keyword"], parent=root)
        if not kw or not kw.strip():
            return
        kw = kw.strip()
        cfg["keyword"] = kw
        _run_session(
            lambda: run_keyword_mode(kw, cfg["delay"], cfg["log"]),
            "Keyword auto-click running… (press ■ Stop in the browser)")

    def view_logs():
        win = tk.Toplevel(root)
        win.title("Logs")
        win.geometry("760x460")
        st = scrolledtext.ScrolledText(win, font=("Courier New", 10),
                                       wrap="none")
        st.pack(fill="both", expand=True)
        st.insert("1.0", format_logs(cfg["log"], tail=200))
        st.config(state="disabled")
        tk.Button(win, text="Refresh", command=lambda: (
            st.config(state="normal"), st.delete("1.0", "end"),
            st.insert("1.0", format_logs(cfg["log"], tail=200)),
            st.config(state="disabled"))).pack(pady=4)

    def open_settings():
        win = tk.Toplevel(root)
        win.title("Settings")
        win.geometry("380x300")
        win.configure(bg="#1f2937")
        fields = {
            "Clicks per link": ("times", str(cfg["times"])),
            "Delay between clicks (s)": ("delay", str(cfg["delay"])),
            "Default keyword (blank = manual)": ("keyword", cfg["keyword"]),
            "Log file": ("log", cfg["log"]),
        }
        entries = {}
        for label, (key, val) in fields.items():
            tk.Label(win, text=label, fg="#e5e7eb", bg="#1f2937",
                     anchor="w").pack(fill="x", padx=16, pady=(10, 0))
            e = tk.Entry(win, width=40)
            e.insert(0, val)
            e.pack(padx=16)
            entries[key] = e

        def save():
            try:
                cfg["times"] = max(1, int(entries["times"].get().strip()))
                cfg["delay"] = max(0.0, float(entries["delay"].get().strip()))
            except ValueError:
                messagebox.showerror(
                    "Invalid", "Clicks must be a whole number and delay a number.")
                return
            cfg["keyword"] = entries["keyword"].get().strip()
            log_val = entries["log"].get().strip()
            if log_val:
                cfg["log"] = log_val
            save_config(CONFIG_FILE, cfg)
            refresh_summary()
            win.destroy()

        tk.Button(win, text="Save", font=("Arial", 11, "bold"), bg="#2563eb",
                  fg="#ffffff", relief="flat", width=12,
                  command=save).pack(pady=16)

    open_btn = styled("▶  Open Chrome (normal)", "#16a34a", open_chrome)
    kw_btn = styled("🎯  Open Chrome (keyword)", "#0d9488", open_chrome_keyword)
    styled("📄  Logs", "#2563eb", view_logs)
    styled("⚙  Settings", "#6b7280", open_settings)
    styled("✖  Exit", "#dc2626", root.destroy)

    refresh_summary()
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactive Google result clicker (hover -> click box -> "
                    "open link N times).",
    )
    parser.add_argument("keyword", nargs="?", default=None,
                        help="Default keyword (overrides saved setting).")
    parser.add_argument("--times", type=int, default=None,
                        help="Override default clicks per link for this run.")
    parser.add_argument("--delay", type=float, default=None,
                        help="Override delay between clicks for this run.")
    parser.add_argument("--log", default=None,
                        help="Override CSV log file path.")
    parser.add_argument("--no-menu", action="store_true",
                        help="Skip the menu and start Chrome immediately.")
    parser.add_argument("--cli", action="store_true",
                        help="Force the text menu instead of the GUI window.")
    args = parser.parse_args()

    cfg = load_config(CONFIG_FILE)
    # CLI flags override saved settings when provided.
    if args.keyword is not None:
        cfg["keyword"] = args.keyword
    if args.times is not None:
        cfg["times"] = args.times
    if args.delay is not None:
        cfg["delay"] = args.delay
    if args.log is not None:
        cfg["log"] = args.log

    if args.no_menu:
        return run(cfg["keyword"] or None, cfg["times"], cfg["delay"], cfg["log"])

    if not args.cli:
        try:
            import tkinter  # noqa: F401
            return launch_gui(cfg)
        except ImportError:
            print("[!] tkinter not installed — falling back to text menu.")
            print("    Install it with: sudo dnf install python3-tkinter")
    return terminal_menu(cfg)


if __name__ == "__main__":
    sys.exit(main())
