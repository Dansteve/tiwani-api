#!/usr/bin/env python3
"""Validate the TIWANI Supabase auth email templates.

Runs in CI (and locally) to catch a broken template before it ships: balanced
tags, a balanced ``{{ if }}`` greeting guard, the GoTrue variable(s) each
template needs, brand-only colours, and no clinical vocabulary. Exits non-zero
on any problem. No secrets, no network.
"""
import glob
import os
import re
import sys

# The only colours allowed in the templates (Deep Teal / Coral / Warm Grey plus
# the warm neutrals derived from them). Anything else is an off-brand leak.
BRAND = {
    "#04342c", "#0f6e56", "#1d9e75", "#d85a30", "#993c1d", "#e1f5ee",
    "#9fe1cb", "#2c2c2a", "#5f5e5a", "#ffffff", "#f5f3ef", "#e7e3dc",
}

# Words the non-clinical boundary bars from a transactional account email.
CLINICAL = [
    "therapy", "diagnos", "clinical", "patient", "disorder", "symptom",
    "treatment", "mental health", "crisis", "trauma", "medication",
]

# Each template and the GoTrue variable(s) it must reference.
NEEDS = {
    "confirmation.html": ["{{ .ConfirmationURL }}"],
    "invite.html": ["{{ .ConfirmationURL }}"],
    "magic_link.html": ["{{ .ConfirmationURL }}", "{{ .Token }}"],
    "email_change.html": ["{{ .ConfirmationURL }}", "{{ .NewEmail }}"],
    "recovery.html": ["{{ .ConfirmationURL }}"],
    "reauthentication.html": ["{{ .Token }}"],
}

TAGS = ["html", "head", "body", "table", "tr", "td", "h1", "style"]


def check(name, html):
    """Return a list of problems for one template (empty when it is clean)."""
    problems = []
    for tag in TAGS:
        opened = len(re.findall(rf"<{tag}[ >]", html))
        closed = len(re.findall(rf"</{tag}>", html))
        if opened != closed:
            problems.append(f"tag {tag} {opened}/{closed}")
    if html.count("{{ if") != html.count("{{ end }}"):
        problems.append("unbalanced {{ if }}/{{ end }}")
    for var in NEEDS.get(name, []):
        if var not in html:
            problems.append(f"missing variable {var}")
    # Reauthentication has no link: GoTrue issues only a code for it.
    if name == "reauthentication.html" and "ConfirmationURL" in html:
        problems.append("reauthentication must not contain a link")
    offs = sorted(set(re.findall(r"#[0-9a-fA-F]{6}", html)) - BRAND)
    if offs:
        problems.append(f"off-palette colours {offs}")
    hits = [w for w in CLINICAL if re.search(w, html, re.I)]
    if hits:
        problems.append(f"clinical vocabulary {hits}")
    return problems


def main():
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    files = sorted(glob.glob(os.path.join(here, "*.html")))
    found = {os.path.basename(f) for f in files}
    failures = 0

    missing = sorted(set(NEEDS) - found)
    if missing:
        print(f"FAIL: missing template files: {missing}")
        failures += 1

    for path in files:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as handle:
            problems = check(name, handle.read())
        if problems:
            failures += 1
            print(f"FAIL {name}: " + "; ".join(problems))
        else:
            print(f"ok   {name}")

    if failures:
        print(f"\n{failures} problem(s).")
        return 1
    print("\nAll templates valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
