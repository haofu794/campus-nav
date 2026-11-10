"""Polite HTTP helpers shared by all scrapers.

Every scraper talks to someone else's server, so we:
  1. wait between requests (delay + a little random jitter),
  2. retry with exponential backoff when the server errors or rate-limits us,
  3. give up after a few tries instead of hammering the site.
"""
import random
import time

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class PoliteSession:
    """A thin wrapper around requests.Session that waits between calls and retries."""

    def __init__(self, delay=1.0, retries=3, timeout=20, headers=None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        if headers:
            self.s.headers.update(headers)
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0

    @property
    def headers(self):
        return self.s.headers

    def _wait(self):
        # Sleep so that two requests are at least `delay` seconds apart (+0~30% jitter).
        elapsed = time.time() - self._last
        wait = self.delay * (1 + random.uniform(0, 0.3)) - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(self, method, url, **kwargs):
        last_err = None
        for attempt in range(self.retries):
            self._wait()
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kwargs)
                self._last = time.time()
                if r.status_code == 429 or r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                self._last = time.time()
                last_err = e
                # Exponential backoff: 2s, 4s, 8s ...
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"{method} {url} failed after {self.retries} tries: {last_err}")

    def post_json(self, url, body):
        return self._request("POST", url, json=body).json()

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def get_json(self, url):
        return self.get(url).json()
