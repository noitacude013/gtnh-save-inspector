#!/usr/bin/env python3
"""Static sanity checks for the GUI frontend (CI-safe, no browser)."""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "gtnh_save_inspector", "gui", "static")
FAILS = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + (("  " + detail) if detail else ""))
    if not condition:
        FAILS.append(name)


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
        return handle.read()


def main() -> int:
    for name in ("index.html", "app.js", "style.css", "i18n.js"):
        check("static file " + name, os.path.isfile(os.path.join(STATIC, name)))

    html = read("index.html")
    app = read("app.js")
    i18n = read("i18n.js")

    dict_keys = set(re.findall(r'"([a-zA-Z]+\.[a-zA-Z0-9.]+)":', i18n))
    html_keys = set(re.findall(r'data-i18n(?:-placeholder)?="([^"]+)"', html))
    app_keys = set()
    for match in re.finditer(r'\bt\("([a-zA-Z]+\.[a-zA-Z0-9.]+)"\)', app):
        app_keys.add(match.group(1))

    missing = sorted((html_keys | app_keys) - dict_keys)
    check("i18n keys exist", not missing, ", ".join(missing))

    zh_block = i18n.split("zh: {", 1)[1].split("en: {", 1)[0]
    en_block = i18n.split("en: {", 1)[1]
    zh_keys = set(re.findall(r'"([a-zA-Z]+\.[a-zA-Z0-9.]+)":', zh_block))
    en_keys = set(re.findall(r'"([a-zA-Z]+\.[a-zA-Z0-9.]+)":', en_block))
    missing_zh = sorted(en_keys - zh_keys)
    missing_en = sorted(zh_keys - en_keys)
    check("zh/en key parity", not missing_zh and not missing_en,
          "zh missing=%s en missing=%s" % (missing_zh, missing_en))

    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'\$\("([^"]+)"\)', app))
    missing_ids = sorted(used - ids)
    check("DOM ids exist", not missing_ids, ", ".join(missing_ids))

    placeholders = set(re.findall(r'data-i18n-placeholder="([^"]+)"', html))
    missing_placeholders = sorted(placeholders - dict_keys)
    check("placeholder keys exist", not missing_placeholders, ", ".join(missing_placeholders))

    # Every id used in getElementById-style helpers must be unique.
    all_ids = re.findall(r'id="([^"]+)"', html)
    duplicates = sorted({value for value in all_ids if all_ids.count(value) > 1})
    check("unique DOM ids", not duplicates, ", ".join(duplicates))

    check("labels associated", html.count(" for=\"") >= 20, str(html.count(" for=\"")))
    check("aria-live toast", 'aria-live="polite"' in html)
    check("tab roles", 'role="tablist"' in html and 'role="tab"' in html)

    print("%d GUI static check(s) failed" % len(FAILS) if FAILS else "all GUI static checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
