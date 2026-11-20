#!/usr/bin/env python3
"""Bajenbot: pingar dig när Hammarby Fotboll publicerar något nytt.

Läser klubbens RSS-flöden, minns vad den redan sett (seen.json) och skickar
push via ntfy.sh. Biljettrelaterade nyheter skickas med högsta prioritet.

Kör:  python3 bajenbot.py            (en kontroll, för launchd/cron)
      python3 bajenbot.py --test     (skicka en testnotis)
"""
import base64
import html
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
_cfg = HERE / "config.json"
CONFIG = json.loads(_cfg.read_text()) if _cfg.exists() else {}
# I molnet kommer kanalnamnet från en hemlig miljövariabel
CONFIG["ntfy_topic"] = os.environ.get("NTFY_TOPIC") or CONFIG.get("ntfy_topic")
STATE = HERE / "seen.json"

FEEDS = [
    "https://www.hammarbyfotboll.se/feed/nyeterrss.xml",
    "https://www.hammarbyfotboll.se/feed/apprss.xml",
    "https://www.hammarbyfotboll.se/feed/herrarrss.xml",
    "https://www.hammarbyfotboll.se/feed/damrss.xml",
]

# Träff i rubrik eller ingress => akut notis
URGENT = re.compile(
    r"biljett|släpp|slutsål|restplats|säsongskort|försäljning|bortasektion|"
    r"bortaresa|extra ?platser|fler platser|ticket|köp(?:et)? öppnar",
    re.IGNORECASE,
)


def fetch(url):
    # curl i stället för urllib: undviker certifikatstrul med python.org-installationen
    return subprocess.run(
        ["curl", "-sfL", "--max-time", "20", "-A", "Mozilla/5.0 bajenbot", url],
        capture_output=True, check=True,
    ).stdout


def items():
    found = {}
    for url in FEEDS:
        try:
            root = ET.fromstring(fetch(url))
        except Exception as e:  # ett trasigt flöde ska inte stoppa de andra
            print(f"fel vid {url}: {e}", file=sys.stderr)
            continue
        for it in root.iter("item"):
            link = (it.findtext("link") or "").strip()
            if not link:
                continue
            desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
            found.setdefault(link, {
                "title": (it.findtext("title") or "").strip(),
                "desc": re.sub(r"\s+", " ", desc).strip(),
                "link": link,
            })
    return found


def notify(title, body, link, urgent):
    headers = {
        "Title": title,
        "Click": link,
        "Priority": "5" if urgent else "3",
        "Tags": "rotating_light,tickets" if urgent else "green_heart",
    }
    cmd = ["curl", "-sf", "--max-time", "15"]
    for k, v in headers.items():
        # ntfy accepterar UTF-8 i headers via RFC 2047-kodning
        if not v.isascii():
            v = f"=?UTF-8?B?{base64.b64encode(v.encode()).decode()}?="
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["--data-binary", body, f"{CONFIG.get('ntfy_server', 'https://ntfy.sh')}/{CONFIG['ntfy_topic']}"]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    if "--test" in sys.argv:
        notify("Bajenbot är igång 💚🤍", "Testnotis. Nu bevakar jag Hammarbys nyheter.",
               "https://www.hammarbyfotboll.se/nyheter", urgent=False)
        print("testnotis skickad")
        return

    current = items()
    if not current:
        print("inga poster hämtade, hoppar över", file=sys.stderr)
        return

    first_run = not STATE.exists()
    seen = set() if first_run else set(json.loads(STATE.read_text()))
    new = [v for k, v in current.items() if k not in seen]

    if first_run:
        print(f"första körningen: sparar {len(current)} befintliga nyheter utan att pinga")
    else:
        for n in new:
            urgent = bool(URGENT.search(n["title"] + " " + n["desc"]))
            prefix = "🎟️ BILJETTER? " if urgent else ""
            notify(prefix + n["title"], n["desc"][:300] or n["link"], n["link"], urgent)
            print(("AKUT: " if urgent else "ny: ") + n["title"])

    keep = seen | set(current)  # växer bara med några länkar per dag
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(keep), ensure_ascii=False))
    os.replace(tmp, STATE)


if __name__ == "__main__":
    main()
