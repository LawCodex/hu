"""Shared helpers for the Hungarian (njt.jog.gov.hu) LawCodex scraper."""
import os
import time
import random
import threading

import requests

BASE = "https://njt.jog.gov.hu"
UA = "LawCodex/1.0 (+https://github.com/LawCodex)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (hu/)
RAW = os.environ.get(
    "HU_RAW", os.path.join(os.path.dirname(ROOT), "_raw", "hu"))

# Minimum delay between two requests issued by the same thread (seconds).
DELAY = float(os.environ.get("HU_DELAY", "0.5"))

_local = threading.local()


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "hu"})
        _local.s = s
        _local.last = 0.0
    return s


def _wait():
    last = getattr(_local, "last", 0.0)
    d = DELAY - (time.time() - last)
    if d > 0:
        time.sleep(d)
    _local.last = time.time()


def request(method, url, retries=6, allow_redirects=True, **kw):
    """HTTP request with polite delay and exponential backoff."""
    s = session()
    err = None
    for attempt in range(retries):
        _wait()
        try:
            r = s.request(method, url, timeout=120,
                          allow_redirects=allow_redirects, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                err = "HTTP %d" % r.status_code
                ra = r.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit()
                           else (2 ** attempt) * 2 + random.random())
                continue
            return r
        except requests.RequestException as e:
            err = str(e)
            time.sleep((2 ** attempt) * 2 + random.random())
    raise RuntimeError("failed %s %s: %s" % (method, url, err))


def get(url, **kw):
    return request("GET", url, **kw)


def post_json(url, payload):
    return request("POST", url, json=payload,
                   headers={"Content-Type": "application/json; charset=utf-8",
                            "X-Requested-With": "XMLHttpRequest"})


def today():
    import datetime
    return os.environ.get("HU_TODAY") or datetime.date.today().isoformat()


def in_force(item):
    """In force (or enacted and not yet in force) today: no end date or end date later."""
    return item.get("to") is None or item["to"] > today()
