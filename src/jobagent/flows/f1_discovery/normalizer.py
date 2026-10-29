import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jobagent.core.schemas import JobRaw

_TRACKING = re.compile(r"^(utm_.*|trk|trkemail|trackingid|refid|ref|src|source|lipi|midtoken|midsig|eid|otptoken|alertid|campaign)$", re.I)
_COMPANY_SUFFIX = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|incorporated|corp|corporation|co|technologies|technology|solutions)\b\.?", re.I)


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d+)", p.path)
    if "linkedin.com" in host and m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    if "naukri.com" in host:  # the path (ending in the job id) identifies the job; the query is only tracking
        return f"https://{host}{p.path.rstrip('/')}"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)])
    return urlunparse((p.scheme.lower() or "https", host, p.path.rstrip("/"), "", query, ""))


def norm(s: str | None) -> str:
    s = _COMPANY_SUFFIX.sub(" ", (s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def city_of(location: str | None) -> str:
    return norm((location or "").split(",")[0].split("(")[0])


def dedupe_key(job: JobRaw) -> str:
    return hashlib.sha1(f"{norm(job.company)}|{norm(job.title)}|{city_of(job.location)}".encode()).hexdigest()


def parse_posted(text: str | None, now: datetime) -> datetime | None:
    """'2 days ago', '5 hours ago', 'Just now', 'Today', '30+ days ago' -> datetime. None when unknown."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.search(r"just now|today|few (seconds|minutes)", t):
        return now
    m = re.search(r"(\d+)\+?\s*(minute|hour|day|week|month)s?", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n),
             "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
    return now - delta
