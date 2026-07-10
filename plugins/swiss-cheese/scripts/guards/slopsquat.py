"""slopsquat guard — hallucinated / typosquatted dependencies.

Adapters per ecosystem (npm | pypi | packagist | crates | rubygems), chosen
from the dependency manifests recorded in manifest.json. Two tiers:

- Offline (always): a new package name within edit-distance 1 of a very
  popular package (but not an exact match) -> high. Catches `reqeusts`,
  `loadsh`, `expres`.
- Online (opt-in, urllib, soft-skip on timeout): no registry record -> medium;
  package younger than 30 days -> medium.

The only guard that reaches the network, and only when explicitly enabled.
"""

import json
import re
import urllib.request

from . import finding, iter_added_lines, load_ref_json

NAME = "slopsquat"

_FALLBACK = {"npm": [], "pypi": [], "packagist": [], "crates": [], "rubygems": []}

_MANIFEST_ECOSYSTEM = {
    "package.json": "npm", "package-lock.json": "npm", "yarn.lock": "npm",
    "pnpm-lock.yaml": "npm",
    "requirements.txt": "pypi", "pyproject.toml": "pypi", "pipfile": "pypi",
    "setup.py": "pypi",
    "composer.json": "packagist", "composer.lock": "packagist",
    "cargo.toml": "crates", "cargo.lock": "crates",
    "gemfile": "rubygems", "gemfile.lock": "rubygems",
}

_THIRTY_DAYS = 30 * 24 * 3600


def ecosystem_for(path):
    base = path.rsplit("/", 1)[-1].lower()
    if base in _MANIFEST_ECOSYSTEM:
        return _MANIFEST_ECOSYSTEM[base]
    if base.startswith("requirements") and base.endswith(".txt"):
        return "pypi"
    return None


def extract_packages(ecosystem, text):
    """Best-effort package names from one added manifest line."""
    t = text.strip()
    if ecosystem == "npm":
        m = re.match(r'"([@A-Za-z0-9._/-]+)"\s*:\s*"[^"]*"', t)
        return [m.group(1)] if m else []
    if ecosystem == "pypi":
        m = re.match(r'^["\']?([A-Za-z0-9][A-Za-z0-9._-]+)\s*(?:[=<>!~;\[ ]|$)', t)
        return [m.group(1)] if m else []
    if ecosystem == "packagist":
        m = re.match(r'"([a-z0-9._-]+/[a-z0-9._-]+)"\s*:\s*"[^"]*"', t)
        return [m.group(1)] if m else []
    if ecosystem == "crates":
        m = re.match(r'([A-Za-z0-9_-]+)\s*=\s*[{"]', t)
        return [m.group(1)] if m else []
    if ecosystem == "rubygems":
        m = re.match(r"gem\s+['\"]([A-Za-z0-9._-]+)['\"]", t)
        return [m.group(1)] if m else []
    return []


def _within_edit_distance_1(a, b):
    """True if `a` and `b` differ by one edit (Damerau: insert/delete/sub or
    an adjacent transposition).

    Pure Levenshtein misses transpositions (`reqeusts`->`requests`,
    `loadsh`->`lodash`), which are among the most common typosquats, so we
    accept a single adjacent swap as distance 1.
    """
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        mismatches = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(mismatches) == 1:
            return True
        if len(mismatches) == 2:
            i, j = mismatches
            return j == i + 1 and a[i] == b[j] and a[j] == b[i]  # transposition
        return False
    # length differs by one: check single insertion/deletion
    short, long = (a, b) if la < lb else (b, a)
    i = j = 0
    edited = False
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
        elif edited:
            return False
        else:
            edited = True
            j += 1
    return True


def _online_check(ecosystem, name, timeout=4):
    """Return a finding severity/message via registry lookup, or None.

    Soft-skips (returns None) on any network error/timeout.
    """
    urls = {
        "npm": f"https://registry.npmjs.org/{name}",
        "pypi": f"https://pypi.org/pypi/{name}/json",
        "packagist": f"https://repo.packagist.org/p2/{name}.json",
        "crates": f"https://crates.io/api/v1/crates/{name}",
        "rubygems": f"https://rubygems.org/api/v1/gems/{name}.json",
    }
    url = urls.get(ecosystem)
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "swiss-cheese-guard"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("medium", f"{ecosystem} package {name!r} has no registry record")
        return None
    except Exception:
        return None  # timeout / no network -> soft skip

    created = _first_release_epoch(ecosystem, body)
    if created is not None:
        import time
        if time.time() - created < _THIRTY_DAYS:
            return ("medium", f"{ecosystem} package {name!r} is younger than 30 days")
    return None


def _first_release_epoch(ecosystem, body):
    try:
        data = json.loads(body)
    except Exception:
        return None
    import calendar
    import time

    def parse(ts):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return calendar.timegm(time.strptime(ts[:19], fmt))
            except Exception:
                continue
        return None

    try:
        if ecosystem == "npm":
            return parse(data["time"]["created"])
        if ecosystem == "pypi":
            uploads = [r["upload_time"] for v in data["releases"].values() for r in v]
            stamps = [parse(u) for u in uploads if parse(u)]
            return min(stamps) if stamps else None
        if ecosystem == "crates":
            return parse(data["crate"]["created_at"])
        if ecosystem == "rubygems":
            return None  # no reliable created date in this endpoint
    except Exception:
        return None
    return None


def scan(ctx):
    popular = load_ref_json("popular-packages.json", _FALLBACK)
    findings = []
    seen = set()

    for path, _lineno, text in iter_added_lines(ctx.diff_text):
        eco = ecosystem_for(path or "")
        if not eco:
            continue
        for name in extract_packages(eco, text):
            key = (eco, name)
            if key in seen:
                continue
            seen.add(key)

            popular_list = popular.get(eco, [])
            lowered = name.lower()
            for known in popular_list:
                if _within_edit_distance_1(lowered, known.lower()):
                    findings.append(finding(
                        NAME, "high",
                        f"{eco} dependency {name!r} is edit-distance 1 from "
                        f"popular {known!r} — likely typosquat",
                        path=path))
                    break

            if getattr(ctx, "online", False):
                res = _online_check(eco, name)
                if res:
                    sev, msg = res
                    findings.append(finding(NAME, sev, msg, path=path))
    return findings
