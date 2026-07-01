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
        // Skip Google's own nav links, but KEEP sponsored/ad links — those ride
        // on google.com/aclk or googleadservices.com redirects.
        var isAd = /[?&\/]aclk|googleadservices\.com|\/pagead\//i.test(href);
        if (isInternal(host) && !isAd) { return false; }
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


def build_driver(view: str = "desktop") -> webdriver.Chrome:
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=en-US")
    # Use a dedicated, throwaway profile so we never collide with the user's
    # everyday Chrome (which locks the default profile).
    options.add_argument(f"--user-data-dir={tempfile.mkdtemp(prefix='clicker-chrome-')}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if view == "mobile":
        # Emulate a phone so Google serves its MOBILE search layout, where
        # sponsored (ad) results show up more often and are easier to click.
        # deviceMetrics + userAgent is more portable across chromedriver
        # versions than a named "deviceName".
        options.add_experimental_option("mobileEmulation", {
            "deviceMetrics": {"width": 412, "height": 915, "pixelRatio": 2.625},
            "userAgent": ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Mobile Safari/537.36"),
        })
        options.add_argument("--window-size=420,915")
    else:
        options.add_argument("--window-size=1280,950")

    # Resolve chromedriver automatically. Selenium 4.6+ ships "Selenium Manager",
    # which finds/downloads a matching driver on its own and works when frozen
    # into a .exe with no Python installed. We try it first, then fall back to
    # webdriver-manager if Selenium Manager can't reach the network.
    last_err = None
    for attempt in ("selenium-manager", "webdriver-manager"):
        try:
            if attempt == "selenium-manager":
                driver = webdriver.Chrome(options=options)
            else:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)
            return driver
        except WebDriverException as exc:
            last_err = exc
            continue
    raise last_err


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
        EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso"))
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


def run(keyword: str | None, times: int, delay: float, log_path: str,
        view: str = "desktop") -> int:
    driver = build_driver(view)
    logger = CsvLogger(log_path)
    print(f"[+] Logging to {os.path.abspath(log_path)}")
    logger.log("session_start", keyword=keyword or "",
               total=times, detail=f"delay={delay}s view={view}")
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
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso"))
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


def _wait_loaded(driver, timeout: float) -> None:
    """Block until the active tab reports document.readyState == 'complete'."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete")
    except (TimeoutException, WebDriverException):
        pass


def keyword_search_once(driver, google_tab: str, keyword: str,
                        target_domain: str, logger: CsvLogger, iteration: int,
                        clicks, ua: str, first: bool) -> str:
    """One pass: open a fresh tab, search page 1, and click the first result
    (ad or organic) whose destination domain matches *target_domain*. The exact
    URL need not match — only the domain — because ad URLs change every load.
    Then (if clicked) wait for full load and close the tab. Returns the status
    string. Always returns focus to *google_tab*."""
    search_url = "https://www.google.com/search?q=" + quote_plus(keyword)
    driver.switch_to.new_window("tab")
    try:
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride", {"userAgent": ua})
    except WebDriverException:
        pass
    try:
        driver.get(search_url)
    except WebDriverException:
        pass
    # Wait for page-1 results before scanning for the target domain.
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso")))
    except (TimeoutException, WebDriverException):
        pass
    if first:
        dismiss_consent(driver)

    try:
        res = driver.execute_script(CLICK_BY_DOMAIN_JS, target_domain)
    except WebDriverException:
        res = None
    res = res or {"status": "error"}
    status = res.get("status", "error")

    if status == "clicked":
        clicks[0] += 1
        _wait_loaded(driver, 30)   # close only after it fully loads
        kind = "ad" if res.get("ad") else "result"
        print(f"    iter {iteration}: clicked {kind} {res.get('domain', '')} "
              f"-> {res.get('href', '')}")
        logger.log("kw_click", keyword=keyword, url=res.get("href", ""),
                   click=clicks[0], total=res.get("total", ""), user_agent=ua,
                   detail=f"iter{iteration}:{res.get('domain', '')}")
    else:
        note = {"absent": f"domain '{target_domain}' not on page 1",
                "error": "check failed"}.get(status, status)
        print(f"    iter {iteration}: skip ({note})")
        logger.log("kw_skip", keyword=keyword, url=target_domain,
                   total=res.get("total", ""), user_agent=ua,
                   detail=f"iter{iteration}:{status}")

    try:
        driver.close()
    except WebDriverException:
        pass
    driver.switch_to.window(google_tab)
    return status


# Shared finder: returns ALL sponsored (ad) blocks on the page — top, inline
# (between organic results), and bottom. Google labels every ad with a bold
# "Sponsored" tag; ads may also sit in #tads / #tadsb / #bottomads or carry a
# data-text-ad attribute. We gather from every signal so no ad is missed, then
# de-duplicate so nested matches collapse to a single outermost block.
_FIND_SPONSORED_JS = r"""
  function _trim(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
  function _visible(el) {
    if (!el) { return false; }
    var r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) { return false; }
    var s = window.getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' &&
           parseFloat(s.opacity || '1') > 0.01;
  }
  function _hasVisibleLink(el) {
    var as = el.querySelectorAll('a[href^="http"]');
    for (var i = 0; i < as.length; i++) { if (_visible(as[i])) { return true; } }
    return false;
  }
  function _isSponsoredLabel(el) {
    return el.children.length === 0 && _trim(el.textContent) === 'Sponsored' &&
           _visible(el);
  }
  function _findSponsored() {
    var regions = [];
    // Only keep VISIBLE blocks that actually hold a visible link — Google ships
    // hidden ad-template/placeholder nodes that would otherwise false-positive.
    function add(el) {
      if (!el || !_visible(el) || !_hasVisibleLink(el)) { return; }
      for (var i = 0; i < regions.length; i++) {
        if (regions[i] === el || regions[i].contains(el)) { return; }
      }
      regions = regions.filter(function (r) { return !el.contains(r); });
      regions.push(el);
    }
    ['#tads', '#tadsb', '#bottomads'].forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) { add(el); });
    });
    document.querySelectorAll('[data-text-ad]').forEach(function (el) { add(el); });
    // Every visible "Sponsored" label -> climb to the ad card that holds it.
    var nodes = document.querySelectorAll('span, div');
    for (var i = 0; i < nodes.length; i++) {
      if (!_isSponsoredLabel(nodes[i])) { continue; }
      var block = nodes[i], chosen = null;
      for (var k = 0; k < 8 && block.parentElement; k++) {
        block = block.parentElement;
        if (_hasVisibleLink(block)) {
          chosen = block;
          // Stop once the block also carries the title/description text.
          if (_trim(block.textContent).length > 40) { break; }
        }
      }
      add(chosen);
    }
    return regions;
  }
"""

SPONSORED_PRESENT_JS = ("return (function () {\n" + _FIND_SPONSORED_JS +
                        "\n  return _findSponsored().length > 0;\n})();")

# Visually isolate the sponsored result(s): hide every node EXCEPT the ad
# block(s) and the chain of ancestors that hold them. Google's own markup and
# stylesheets stay in place, so each ad keeps its native styling. Returns how
# many ad blocks were kept.
STRIP_TO_SPONSORED_JS = ("return (function () {\n" + _FIND_SPONSORED_JS + r"""
  var regions = _findSponsored();
  if (!regions.length) { return 0; }

  // Keep the ancestor chain of every ad block (so layout/positioning CSS that
  // relies on those containers still applies).
  var keep = new Set();
  regions.forEach(function (r) {
    var n = r;
    while (n && n !== document.documentElement) { keep.add(n); n = n.parentElement; }
  });
  function insideRegion(el) {
    for (var i = 0; i < regions.length; i++) {
      if (regions[i].contains(el)) { return true; }
    }
    return false;
  }
  // Hide anything that is neither on a kept ancestor chain nor part of an ad.
  var all = document.body.querySelectorAll('*');
  for (var j = 0; j < all.length; j++) {
    var node = all[j];
    if (keep.has(node) || insideRegion(node)) { continue; }
    node.style.setProperty('display', 'none', 'important');
  }
  // Nudge each kept block so the hover overlay box never covers the ad.
  regions.forEach(function (r) {
    r.style.setProperty('scroll-margin-top', '80px');
  });
  window.scrollTo(0, 0);
  return regions.length;
})();""")


# Helpers to derive a result's *destination domain*. Organic results carry the
# real host directly; ads ride on google.com/aclk or googleadservices.com
# redirects, so we dig the advertiser domain out of the aclk "adurl" param, and
# fall back to the ad's visible display URL (e.g. "example.com"). Matching is by
# domain, NOT exact URL — ad URLs carry a fresh token on every page load.
_DOMAIN_HELPERS_JS = r"""
  function _reg(h) { return (h || '').toLowerCase().replace(/^www\./, ''); }
  function _hostDomain(href) {
    try { return _reg(new URL(href).hostname); } catch (e) { return ''; }
  }
  function _isAdHost(href) {
    var h = _hostDomain(href);
    return /(^|\.)googleadservices\.com$/.test(h) ||
           (/(^|\.)google\.[a-z.]+$/.test(h) && /\/aclk/i.test(href));
  }
  function _adUrlDomain(href) {
    try {
      var u = new URL(href), keys = ['adurl', 'url', 'durl', 'q', 'dest'];
      for (var i = 0; i < keys.length; i++) {
        var v = u.searchParams.get(keys[i]);
        if (v && /^https?:/i.test(v)) { return _hostDomain(v); }
      }
    } catch (e) {}
    return '';
  }
  function _looksDomain(t) {
    var s = (t || '').replace(/\s+/g, ' ').trim();
    var m = s.match(/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)+/i);
    if (!m) { return ''; }
    var d = _reg(m[0]);
    if (d.indexOf('google') !== -1 || d.indexOf('gstatic') !== -1) { return ''; }
    return d;
  }
  function _displayDomain(block) {
    if (!block) { return ''; }
    var cite = block.querySelector('cite');
    if (cite) { var c = _looksDomain(cite.textContent); if (c) { return c; } }
    var els = block.querySelectorAll('span, cite, div');
    for (var i = 0; i < els.length; i++) {
      if (els[i].children.length) { continue; }
      var d = _looksDomain(els[i].textContent);
      if (d) { return d; }
    }
    return '';
  }
  function _destDomain(anchor, block) {
    var href = anchor ? anchor.href : '';
    if (href && !_isAdHost(href)) { return _hostDomain(href); }
    var d = _adUrlDomain(href);
    if (d) { return d; }
    return _displayDomain(block);
  }
  function _domainMatch(a, b) {
    if (!a || !b) { return false; }
    if (a === b) { return true; }
    return a.endsWith('.' + b) || b.endsWith('.' + a);
  }
"""

# Resolve the destination domain of the locked target (arguments[0] = its href).
LOCK_DOMAIN_JS = ("return (function (href) {\n" + _DOMAIN_HELPERS_JS +
                  _FIND_SPONSORED_JS + r"""
  var as = document.querySelectorAll('a[href]'), anchor = null;
  for (var i = 0; i < as.length; i++) {
    if (as[i].href === href) { anchor = as[i]; break; }
  }
  var block = null, regions = _findSponsored();
  for (var r = 0; r < regions.length; r++) {
    if (anchor && regions[r].contains(anchor)) { block = regions[r]; break; }
  }
  if (!block && anchor) { block = anchor.closest('div') || anchor.parentElement; }
  return _destDomain(anchor, block) || _hostDomain(href);
})(arguments[0]);""")

# Click the first result (ad or organic) whose destination domain matches the
# target (arguments[0]). Returns {status: clicked|absent, ...}.
CLICK_BY_DOMAIN_JS = ("return (function (target) {\n" + _DOMAIN_HELPERS_JS +
                      _FIND_SPONSORED_JS + r"""
  function _titleAnchor(block) {
    var h = block.querySelector('h3, [role="heading"]');
    if (h) { var a = h.closest('a'); if (a && /^http/.test(a.href)) { return a; } }
    var as = block.querySelectorAll('a[href^="http"]');
    for (var i = 0; i < as.length; i++) {
      var lbl = (as[i].getAttribute('aria-label') || '') + ' ' +
                (as[i].textContent || '');
      if (/why this ad|ad settings|about this/i.test(lbl)) { continue; }
      return as[i];
    }
    return as[0] || null;
  }
  var cands = [];
  _findSponsored().forEach(function (block) {
    var a = _titleAnchor(block);
    if (a) { cands.push({ a: a, block: block, ad: true }); }
  });
  var h3 = document.querySelectorAll('#search h3, #rso h3');
  for (var i = 0; i < h3.length; i++) {
    var a = h3[i].closest('a');
    if (a && a.href && a.href.indexOf('http') === 0) {
      cands.push({ a: a, block: a.closest('div'), ad: false });
    }
  }
  var total = cands.length;
  for (var j = 0; j < total; j++) {
    var dom = _destDomain(cands[j].a, cands[j].block);
    if (_domainMatch(dom, target)) {
      var el = cands[j].a;
      el.target = '_self';        // navigate this tab, don't spawn one
      el.scrollIntoView({ block: 'center' });
      el.click();
      return { status: 'clicked', index: j, total: total,
               href: el.href, domain: dom, ad: cands[j].ad };
    }
  }
  return { status: 'absent', total: total };
})(arguments[0]);""")


def _target_domain(driver, href: str) -> str:
    """Destination domain of the locked target (advertiser domain for ads)."""
    try:
        return driver.execute_script(LOCK_DOMAIN_JS, href) or ""
    except WebDriverException:
        return ""


def _sponsored_present(driver) -> bool:
    """True if the current results page shows at least one sponsored result."""
    try:
        return bool(driver.execute_script(SPONSORED_PRESENT_JS))
    except WebDriverException:
        return False


def _wait_for_sponsored(driver, logger, keyword: str,
                        interval: float = 5.0, max_refreshes: int = 5) -> bool:
    """Return True as soon as a sponsored result is present. If none yet, refresh
    every *interval* seconds up to *max_refreshes* times, re-checking after each.
    Return False if still none. Lets WebDriverException propagate so a closed
    browser is handled by the caller."""
    if _sponsored_present(driver):
        return True
    for attempt in range(1, max_refreshes + 1):
        time.sleep(interval)
        driver.refresh()      # may raise WebDriverException -> caller exits
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso")))
        except (TimeoutException, WebDriverException):
            pass
        print(f"    no sponsored result — refresh {attempt}/{max_refreshes}")
        logger.log("kw_refresh", keyword=keyword,
                   detail=f"{attempt}/{max_refreshes}")
        if _sponsored_present(driver):
            return True
    return False


def _strip_to_sponsored(driver) -> int:
    """Strip the page down to only its sponsored result(s). Returns the count."""
    try:
        return int(driver.execute_script(STRIP_TO_SPONSORED_JS) or 0)
    except WebDriverException:
        return 0


def run_keyword_mode(keyword: str | None, delay: float, log_path: str,
                     prompt_keyword=None, view: str = "desktop") -> int:
    """Lock a target result for *keyword*, then repeatedly search page 1 and
    click that target wherever it ranks on page 1, waiting for full load before
    closing, until the user presses Stop. *delay* is the pause between searches
    (default 0)."""
    if not keyword:
        print("[!] Keyword mode needs a keyword.")
        return 1
    logger = CsvLogger(log_path)
    print(f"[+] Logging to {os.path.abspath(log_path)}")
    logger.log("kw_session_start", keyword=keyword,
               detail=f"delay={delay}s view={view}")
    driver = None
    try:
        # Outer loop: one full attempt per keyword. A keyword whose page never
        # shows a sponsored result is dropped and we ask for another one.
        while keyword:
            driver = build_driver(view)
            try:
                driver.get("https://www.google.com/ncr")
                dismiss_consent(driver)
                google_tab = driver.current_window_handle
                print(f"[*] Searching for: {keyword!r}")
                logger.log("search", keyword=keyword)
                do_search(driver, keyword)

                # Require a sponsored result. If none, refresh every 5s up to 5
                # times; if still none, drop this keyword and ask for another.
                if not _wait_for_sponsored(driver, logger, keyword):
                    print("[*] No sponsored result after 5 refreshes — "
                          "closing Chrome.")
                    logger.log("kw_no_sponsored", keyword=keyword)
                    try:
                        driver.quit()
                    except WebDriverException:
                        pass
                    driver = None
                    if prompt_keyword is None:
                        print("[*] No way to ask for a keyword — exiting.")
                        return 0
                    nxt = prompt_keyword(keyword)
                    if not nxt:
                        print("[*] No keyword entered — exiting.")
                        return 0
                    keyword = nxt
                    logger.log("kw_retry", keyword=keyword)
                    continue

                # Sponsored result(s) present: strip the page down to only them.
                kept = _strip_to_sponsored(driver)
                print(f"[*] Sponsored result(s) found — kept {kept}, removed the "
                      "rest of the page.")
                logger.log("kw_sponsored", keyword=keyword, total=kept)

                driver.execute_script(OVERLAY_JS, 1, "✓ Use this link")
                print("[*] Hover a sponsored result and click the blue "
                      "'✓ Use this link' box to lock it.")

                # Phase 1: let the user lock a target.
                target = None
                while target is None:
                    try:
                        if not driver.execute_script(
                                "return !!window.__clickerInstalled"):
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

                target_domain = _target_domain(driver, target)
                if not target_domain:
                    print("[!] Could not read the target's domain — using the "
                          "raw link.")
                print(f"[*] Target locked: {target}")
                print(f"[*] Will click results on domain: "
                      f"{target_domain or '(unknown)'}")
                logger.log("kw_target", keyword=keyword, url=target,
                           detail=f"domain={target_domain}")

                # Phase 2: search-check-click loop until Stop.
                try:
                    driver.execute_script(
                        "window.__beginRun && window.__beginRun();")
                except WebDriverException:
                    pass
                clicks = [0]
                it = 0
                last_ua = None
                while True:
                    if _stop_requested(driver):
                        break
                    it += 1
                    try:
                        driver.execute_script(
                            "window.__setBadge && window.__setBadge(arguments[0]);",
                            f"Search {it} • {clicks[0]} clicks")
                    except WebDriverException:
                        print("[*] Browser closed — exiting.")
                        logger.log("browser_closed")
                        return 0
                    ua = pick_user_agent(last_ua)
                    last_ua = ua
                    try:
                        keyword_search_once(driver, google_tab, keyword,
                                            target_domain, logger, it, clicks,
                                            ua, first=(it == 1))
                    except WebDriverException:
                        print("[*] Browser closed — exiting.")
                        logger.log("browser_closed")
                        return 0
                    try:
                        driver.execute_script(
                            "window.__setBadge && window.__setBadge(arguments[0]);",
                            f"Search {it} done • {clicks[0]} clicks")
                    except WebDriverException:
                        break
                    # Optional pause between searches (default 0 = no delay).
                    if delay > 0 and not _stop_requested(driver):
                        waited = 0.0
                        while waited < delay:
                            if _stop_requested(driver):
                                break
                            time.sleep(0.2)
                            waited += 0.2

                print(f"[*] Stopped after {it} search(es), {clicks[0]} clicks.")
                logger.log("kw_stopped", keyword=keyword, click=clicks[0],
                           total=it)
                try:
                    driver.execute_script(
                        "window.__hideProgress && window.__hideProgress();")
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
            except WebDriverException:
                print("[*] Browser closed — exiting.")
                logger.log("browser_closed")
                return 0
        return 0
    finally:
        logger.log("kw_session_end")
        logger.close()
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException:
                pass


CONFIG_FILE = "clicker_config.json"
DEFAULT_CONFIG = {
    "times": 10,
    "delay": 5.0,
    "kw_delay": 0.0,   # keyword mode: pause between searches (0 = no delay)
    "log": "click_log.csv",
    "keyword": "",     # blank = type the search by hand in the browser
    "view": "mobile",  # "mobile" = phone emulation (more ads), or "desktop"
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
        print(f"  1) Default clicks per link ..... {cfg['times']}")
        print(f"  2) Delay between clicks (s) .... {cfg['delay']}")
        print(f"  3) Keyword-mode delay (s) ...... {cfg['kw_delay']}")
        print(f"  4) Default keyword ............. "
              f"{cfg['keyword'] or '(type manually)'}")
        print(f"  5) Log file .................... {cfg['log']}")
        print("  6) Back")
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
            raw = _prompt("Keyword-mode delay seconds", cfg["kw_delay"])
            if raw:
                try:
                    cfg["kw_delay"] = max(0.0, float(raw))
                except ValueError:
                    print("  [!] Enter a number.")
        elif choice == "4":
            raw = _prompt("Keyword (blank to clear)", cfg["keyword"])
            cfg["keyword"] = raw
        elif choice == "5":
            raw = _prompt("Log file path", cfg["log"])
            if raw:
                cfg["log"] = raw
        elif choice == "6":
            save_config(CONFIG_FILE, cfg)
            return
        else:
            print("  [!] Pick 1-6.")


# Columns shown in the spreadsheet-style log view: (display title, CSV field).
LOG_COLUMNS = [
    ("Time", "timestamp"),
    ("Event", "event"),
    ("Keyword", "keyword"),
    ("Click", "click"),
    ("Total", "total"),
    ("URL / Target", "url"),
    ("User agent", "user_agent"),
    ("Detail", "detail"),
]


def read_log_table(log_path: str, tail: int = 200):
    """Return (headers, rows) for a table view of the last *tail* log entries.
    Each row is a list of cell strings aligned to LOG_COLUMNS."""
    headers = [title for title, _ in LOG_COLUMNS]
    if not os.path.exists(log_path):
        return headers, []
    try:
        with open(log_path, encoding="utf-8") as fh:
            raw = list(csv.reader(fh))
    except OSError:
        return headers, []
    if len(raw) <= 1:
        return headers, []
    csv_header, data = raw[0], raw[1:]
    idx = {name: i for i, name in enumerate(csv_header)}

    def cell(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else ""

    def target_of(row):
        """Always return a URL or target for the row: the logged URL, else the
        domain embedded in the detail field, else the keyword."""
        url = cell(row, "url")
        if url:
            return url
        detail = cell(row, "detail")
        if detail.startswith("domain="):
            return detail[len("domain="):]
        if ":" in detail:                    # e.g. "iter3:example.com"
            tail = detail.split(":", 1)[1]
            if "." in tail:
                return tail
        return cell(row, "keyword") or "—"   # never leave the cell blank

    rows = []
    for r in data[-tail:]:
        values = []
        for _title, key in LOG_COLUMNS:
            if key == "url":
                values.append(target_of(r))
            elif key == "timestamp":
                values.append(cell(r, key)[11:19] or cell(r, key))
            else:
                values.append(cell(r, key))
        rows.append(values)
    return headers, rows


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


def _ask_view(cfg: dict) -> str:
    """Prompt Mobile / Desktop, defaulting to the saved choice. Persists it."""
    default = cfg.get("view", "mobile")
    raw = input(f"  View - [M]obile / [D]esktop [{default}]: ").strip().lower()
    if raw.startswith("m"):
        view = "mobile"
    elif raw.startswith("d"):
        view = "desktop"
    else:
        view = default
    if view != cfg.get("view"):
        cfg["view"] = view
        save_config(CONFIG_FILE, cfg)
    return view


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
            view = _ask_view(cfg)
            try:
                run(cfg["keyword"] or None, cfg["times"], cfg["delay"],
                    cfg["log"], view=view)
            except KeyboardInterrupt:
                print("\n[*] Interrupted — back to menu.")
        elif choice == "2":
            kw = cfg["keyword"] or input("  Keyword: ").strip()
            if kw:
                cfg["keyword"] = kw
                view = _ask_view(cfg)

                def ask_again(current):
                    nxt = input("  No sponsored result. New keyword "
                                "(blank to stop): ").strip()
                    if nxt:
                        cfg["keyword"] = nxt
                    return nxt or None

                try:
                    run_keyword_mode(kw, cfg["kw_delay"], cfg["log"], ask_again,
                                     view=view)
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
    from tkinter import messagebox, simpledialog, ttk

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
             fg="#34d399", bg="#1f2937").pack(pady=(0, 8))

    # --- View selector: Mobile (default, more ads) or Desktop ---------------
    view_var = tk.StringVar(value=cfg.get("view", "mobile"))

    def on_view_change():
        cfg["view"] = view_var.get()
        save_config(CONFIG_FILE, cfg)

    view_row = tk.Frame(root, bg="#1f2937")
    view_row.pack(pady=(0, 12))
    tk.Label(view_row, text="View:", font=("Arial", 10, "bold"),
             fg="#e5e7eb", bg="#1f2937").pack(side="left", padx=(0, 8))
    for text, val in (("📱 Mobile", "mobile"), ("💻 Desktop", "desktop")):
        tk.Radiobutton(view_row, text=text, value=val, variable=view_var,
                       command=on_view_change, font=("Arial", 10),
                       fg="#e5e7eb", bg="#1f2937", selectcolor="#374151",
                       activebackground="#1f2937", activeforeground="#ffffff",
                       highlightthickness=0).pack(side="left", padx=4)

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
        view = view_var.get()
        _run_session(
            lambda: run(cfg["keyword"] or None, cfg["times"], cfg["delay"],
                        cfg["log"], view=view),
            f"Chrome ({view}) running… (close the browser to return)")

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

        def ask_again(current):
            """Called from the worker thread when a keyword shows no sponsored
            result. Marshals the prompt onto the Tk main thread and blocks until
            the user answers. Returns the new keyword, or None to stop."""
            holder = {}
            done = threading.Event()

            def show():
                holder["v"] = simpledialog.askstring(
                    "No sponsored result",
                    "No sponsored result for that keyword.\n"
                    "Enter another keyword (Cancel to stop):",
                    initialvalue=current, parent=root)
                done.set()

            root.after(0, show)
            done.wait()
            val = holder.get("v")
            val = val.strip() if val else ""
            if val:
                cfg["keyword"] = val
            return val or None

        view = view_var.get()
        _run_session(
            lambda: run_keyword_mode(kw, cfg["kw_delay"], cfg["log"], ask_again,
                                     view=view),
            f"Keyword auto-click ({view}) running… (press ■ Stop in browser)")

    def view_logs():
        win = tk.Toplevel(root)
        win.title("Logs")
        win.geometry("1000x540")

        style = ttk.Style(win)
        try:
            style.theme_use("clam")          # draws clean cell/grid borders
        except tk.TclError:
            pass
        style.configure("Logs.Treeview", rowheight=24, font=("Arial", 10),
                        borderwidth=1, relief="solid", fieldbackground="#ffffff")
        style.configure("Logs.Treeview.Heading", font=("Arial", 10, "bold"),
                        background="#d7dde5", relief="raised")

        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        headers = [title for title, _ in LOG_COLUMNS]
        widths = {"Time": 74, "Event": 120, "Keyword": 170, "Click": 54,
                  "Total": 54, "URL / Target": 300, "User agent": 230,
                  "Detail": 180}
        centered = {"Click", "Total"}
        tree = ttk.Treeview(frame, columns=headers, show="headings",
                            style="Logs.Treeview")
        for h in headers:
            tree.heading(h, text=h)
            tree.column(h, width=widths.get(h, 120), minwidth=40,
                        anchor="center" if h in centered else "w",
                        stretch=False)

        ysb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        tree.tag_configure("odd", background="#ffffff")
        tree.tag_configure("even", background="#eef2f7")   # Excel-style banding

        def reload():
            tree.delete(*tree.get_children())
            _, rows = read_log_table(cfg["log"])
            for i, vals in enumerate(rows):
                tree.insert("", "end", values=vals,
                            tags=("even" if i % 2 else "odd",))
            kids = tree.get_children()
            if kids:
                tree.see(kids[-1])           # jump to the latest entry

        reload()
        tk.Button(win, text="Refresh", command=reload).pack(pady=6)

    def open_settings():
        win = tk.Toplevel(root)
        win.title("Settings")
        win.geometry("400x360")
        win.configure(bg="#1f2937")
        fields = {
            "Clicks per link (normal mode)": ("times", str(cfg["times"])),
            "Delay between clicks (s)": ("delay", str(cfg["delay"])),
            "Keyword-mode delay between searches (s)":
                ("kw_delay", str(cfg["kw_delay"])),
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
                cfg["kw_delay"] = max(
                    0.0, float(entries["kw_delay"].get().strip()))
            except ValueError:
                messagebox.showerror(
                    "Invalid", "Clicks must be a whole number and delays numbers.")
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
    try:                       # flush prints promptly so log files stay current
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
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
    parser.add_argument("--view", choices=("mobile", "desktop"), default=None,
                        help="Chrome view: mobile (phone emulation) or desktop.")
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
    if args.view is not None:
        cfg["view"] = args.view

    if args.no_menu:
        return run(cfg["keyword"] or None, cfg["times"], cfg["delay"],
                   cfg["log"], view=cfg["view"])

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
