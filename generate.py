#!/usr/bin/env python3
"""Generate an XMLTV EPG for the UK news channel "Sky News".

Sky publishes no XMLTV feed. The source is Sky UK's own guide API — the one behind sky.com's TV
guide (`awk.epgsky.com/hawk/linear/schedule/<YYYYMMDD>/<sid>`) — which answers without a key, one
day per request, from yesterday to a week ahead. Sky News HD is service id 4050 (EPG 501).

The sister repo skytg24-epg reads Sky ITALIA's guide; this is its UK counterpart, in the same shape.

## What the source gives

Every programme has a title, a synopsis and a `programmeuuid`, which is also its picture id on
Sky's image service (`images.metadata.sky.com/pd-image/<uuid>/16-9/1024`, measured 18 Nov 2026:
200, JPEG). No category worth carrying — the genre is a numeric code — so none is written.

## Times are British

The channel is broadcast from London. The API answers in epoch seconds; every time is written in
Europe/London (+0000 in winter, +0100 in summer) and the player converts to wherever it is.

## Merging

Sky stops answering for a day once it is two days old, so the hours already aired exist only in
the file committed by earlier runs. Each run keeps the committed guide for everything BEFORE the
first programme the API returned, and the API is the authority from there on — a programme Sky
reschedules does not linger beside its replacement. Anything that finished more than RETAIN_DAYS
ago is dropped.

Stdlib only — no pip install, runs on a stock GitHub Actions runner.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

# --- config -------------------------------------------------------------------------------------
CHANNEL_ID = "SkyNews.uk"             # XMLTV id → paste this exact string as the app's tvg-id
CHANNEL_NAME = "Sky News"
CHANNEL_LOGO = ("https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-kingdom/"
                "sky-news-uk.png")
LONDON = ZoneInfo("Europe/London")
API = "https://awk.epgsky.com/hawk/linear/schedule/{day}/{sid}"
SKY_SERVICE = 4050                    # Sky News HD in /hawk/linear/services/4101/1 (EPG 501)
IMAGE = "https://images.metadata.sky.com/pd-image/{uuid}/16-9/1024"
DAYS = range(-1, 8)                   # yesterday (what is left of it) to a week ahead
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
OUT = "skynews.xml"
RETAIN_DAYS = 3                       # how much already-broadcast guide to keep when merging


class Unreachable(Exception):
    """The source did not answer, or answered with something that is not the schedule."""


def fetch() -> list[tuple]:
    """Every programme Sky lists from yesterday to a week ahead, as rows.

    Raises Unreachable rather than returning junk if TODAY's answer is missing or malformed; a day
    further out that comes back empty is simply not published yet.
    """
    today = datetime.now(timezone.utc).date()
    rows = []
    for offset in DAYS:
        day = today + timedelta(days=offset)
        req = urllib.request.Request(API.format(day=f"{day:%Y%m%d}", sid=SKY_SERVICE),
                                     headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.load(resp)
            events = body["schedule"][0]["events"]
            if not isinstance(events, list):
                raise TypeError("events is not a list")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as exc:
            if offset == 0:
                raise Unreachable(f"Sky UK guide, {day}: {exc}") from exc
            continue
        rows += [row for row in map(to_row, events) if row]
    # Days overlap at midnight; the same programme can be listed twice.
    unique = {(r[0], r[2]): r for r in rows}
    return sorted(unique.values(), key=lambda r: r[0])


def to_row(event: dict) -> tuple | None:
    """(start, stop, title, desc, icon), times in London, or None if unusable."""
    try:
        start = datetime.fromtimestamp(int(event["st"]), timezone.utc).astimezone(LONDON)
        stop = start + timedelta(seconds=int(event["d"]))
    except (KeyError, TypeError, ValueError):
        return None
    title = (event.get("t") or "").strip()
    if not title or stop <= start:
        return None
    desc = (event.get("sy") or "").strip()
    uuid = (event.get("programmeuuid") or "").strip()
    icon = IMAGE.format(uuid=uuid) if uuid else ""
    return (start, stop, title, desc, icon)


def read_committed() -> dict:
    """The programmes already in the repo, keyed as the fresh ones are."""
    try:
        root = ET.parse(OUT).getroot()
    except (OSError, ET.ParseError):
        return {}
    out = {}
    for pr in root.findall("programme"):
        try:
            start = datetime.strptime(pr.get("start", ""), "%Y%m%d%H%M%S %z")
            stop = datetime.strptime(pr.get("stop", ""), "%Y%m%d%H%M%S %z")
        except ValueError:
            continue
        title = (pr.findtext("title") or "").strip()
        if not title:
            continue
        icon = pr.find("icon")
        out[(start, title)] = (start, stop, title, (pr.findtext("desc") or "").strip(),
                               icon.get("src", "") if icon is not None else "")
    return out


def committed_guide_ends() -> datetime | None:
    """The last stop time in the committed file, so we know how long it can carry us."""
    try:
        with open(OUT, encoding="utf-8") as fh:
            stamps = re.findall(r'stop="(\d{14}) ([+-]\d{4})"', fh.read())
    except OSError:
        return None
    if not stamps:
        return None
    return max(datetime.strptime(f"{s} {z}", "%Y%m%d%H%M%S %z") for s, z in stamps)


def main() -> int:
    programmes = read_committed()
    try:
        fresh = fetch()
    except Unreachable as exc:
        # Someone else's outage should not mail a failure every four hours while the committed
        # guide still covers tomorrow.
        ends = committed_guide_ends()
        if ends and ends - datetime.now(LONDON) > timedelta(hours=24):
            print(f"{exc}\nKeeping the committed guide, good until {ends:%Y-%m-%d %H:%M}.",
                  file=sys.stderr)
            return 0
        print(f"{exc}\nAND the committed guide is nearly spent.", file=sys.stderr)
        return 1
    if not fresh:
        print("  ! Sky answered with no programmes for Sky News — has the service id changed?",
              file=sys.stderr)
        return 1
    first = fresh[0][0]
    programmes = {k: r for k, r in programmes.items() if r[0] < first}
    carried = len(programmes)
    for row in fresh:
        programmes[(row[0], row[2])] = row
    print(f"  Sky UK guide: {len(fresh)} programme(s), {first:%d %b %H:%M} to "
          f"{max(r[1] for r in fresh):%d %b %H:%M}")

    cutoff = datetime.now(LONDON) - timedelta(days=RETAIN_DAYS)
    rows = sorted((r for r in programmes.values() if r[1] > cutoff), key=lambda r: r[0])

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
        '<tv generator-info-name="skynews-epg" source-info-name="Sky UK guide">',
        f'  <channel id="{CHANNEL_ID}">',
        f'    <display-name>{escape(CHANNEL_NAME)}</display-name>',
        f'    <icon src="{escape(CHANNEL_LOGO)}" />',
        '  </channel>',
    ]
    for start, stop, title, desc, icon in rows:
        lines.append(f'  <programme start="{start:%Y%m%d%H%M%S %z}" '
                     f'stop="{stop:%Y%m%d%H%M%S %z}" channel="{CHANNEL_ID}">')
        lines.append(f'    <title lang="en">{escape(title)}</title>')
        if desc:
            lines.append(f'    <desc lang="en">{escape(desc)}</desc>')
        if icon:
            lines.append(f'    <icon src="{escape(icon)}" />')
        lines.append('  </programme>')
    lines.append('</tv>')

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    covered = max(r[1] for r in rows)
    print(f"Wrote {OUT}: {len(rows)} programmes for {CHANNEL_NAME}, "
          f"{rows[0][0]:%d %b %H:%M} to {covered:%d %b %H:%M %Z} "
          f"({carried} carried over from the committed guide).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
