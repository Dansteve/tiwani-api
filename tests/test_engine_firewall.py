"""The determinism firewall: the authoritative engines stay pure and unreachable
from external, learned, or real-world data.

Companion to ``test_seed.py``'s ``test_engine_lce_source_hardcodes_no_score`` (the
LCE-specific "no inlined score" guard). This file pins the WIDER invariant that the
three AUTHORITATIVE engines, the LCE (Product.md 4.4), the LCI (4.8), and the
Erosion Alerts (4.9), cannot import the persistence, clock, network, or context
layer, so no real-world datum, no DB read, no wall clock, and no future context
layer can ever reach a score. The engines are pure functions of their inputs (a
profile, an activity, stored outcomes, plus an INJECTED ``now``). This makes that
a test, not a convention (FeatureDecisions.md 2026-06-19: the Context-Layer Part C
NO-GO and the Engine-Intelligence + growth decision).

WHY import-isolation, and NOT a "no literal >= 2" guard over the LCI/Alerts the way
``test_seed.py`` guards the LCE: the LCE reads EVERY number from the seed, so it
legitimately holds none. But the LCI's ``adjustments.py`` and the Alerts'
``evaluation.py`` ARE the authoritative calc seams, the only place the 4.8/4.9
constants live by design, so a literal ban there would be wrong. Those NUMBERS are
pinned by ``test_engine_lci.py`` / ``test_engine_alerts.py`` against Product.md;
their PURITY (that no external input can ever displace them) is pinned here.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The three authoritative engine packages (Product.md 4.4 / 4.8 / 4.9).
_ENGINE_DIRS = ("lce", "lci", "alerts")
_ENGINES_ROOT = Path(__file__).resolve().parents[1] / "app" / "engines"

# The ONLY app.* prefixes a pure engine may import: the engines themselves, the
# pydantic models (pure schemas), and the static authoritative seed. Everything
# else under app.* (above all app.services.*, where the DB, the clock, the IO, and
# any future context layer live) is out of bounds.
_ALLOWED_APP_PREFIXES = (
    "app.engines.lce",
    "app.engines.lci",
    "app.engines.alerts",
    "app.models",
    "app.seed",
)

# Third-party / stdlib modules that would breach determinism or reach the outside
# world. A pure engine imports none of them.
_FORBIDDEN_TOP_LEVEL = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "aiohttp",
        "socket",
        "http",
        "smtplib",
        "ftplib",
        "random",
        "secrets",
        "supabase",
        "postgrest",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "sqlalchemy",
        "redis",
        "boto3",
    }
)

# Wall-clock reads forbidden inside a deterministic engine: the instant is always
# INJECTED as ``now``. Detected as calls like datetime.now(), date.today(),
# time.time().
_CLOCK_NAMES = frozenset({"datetime", "date"})
_CLOCK_ATTRS = frozenset({"now", "utcnow", "today"})
_TIME_ATTRS = frozenset({"time", "monotonic"})


def _engine_files() -> list[Path]:
    files: list[Path] = []
    for name in _ENGINE_DIRS:
        files.extend((_ENGINES_ROOT / name).rglob("*.py"))
    return sorted(files)


def _imported_modules(tree: ast.AST) -> list[str]:
    """All absolute modules imported anywhere in the tree (any nesting depth)."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # node.module is None for ``from . import x``; the engines use
            # absolute imports (level 0), but skip relative ones defensively.
            if node.module is not None and node.level == 0:
                modules.append(node.module)
    return modules


def _app_import_allowed(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in _ALLOWED_APP_PREFIXES
    )


def test_firewall_scan_is_not_vacuous():
    # A green result must mean the scan actually saw the engine sources.
    files = _engine_files()
    names = {f.name for f in files}
    assert len(files) >= 8, files
    assert {"engine.py", "adjustments.py", "evaluation.py"} <= names


def test_authoritative_engines_import_no_external_or_io_module():
    offenders = []
    for path in _engine_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for module in _imported_modules(tree):
            if module == "app" or module.startswith("app."):
                if not _app_import_allowed(module):
                    offenders.append((path.name, module))
            elif module.split(".")[0] in _FORBIDDEN_TOP_LEVEL:
                offenders.append((path.name, module))
    assert not offenders, (
        "the authoritative engines must stay pure and unreachable from the "
        "persistence / clock / network / context layer; firewall breach: "
        f"{offenders}"
    )


def test_authoritative_engines_make_no_wall_clock_call():
    offenders = []
    for path in _engine_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name):
                continue
            owner, attr = func.value.id, func.attr
            is_dt_clock = owner in _CLOCK_NAMES and attr in _CLOCK_ATTRS
            is_time_clock = owner == "time" and attr in _TIME_ATTRS
            if is_dt_clock or is_time_clock:
                offenders.append((path.name, node.lineno, f"{owner}.{attr}"))
    assert not offenders, (
        "a deterministic engine never reads the wall clock; the instant must be "
        f"injected as `now`. Clock read(s): {offenders}"
    )
