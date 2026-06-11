"""No-DB tests pinning the foundation package structure.

Assert the target layout from HardRules/Api/SETUP.md exists and imports, that the
engine subpackages are STUBS (a documented package with no public callables yet,
since the logic is BLOCKED on the seed companion docs), and that app/db.py exposes
the two Supabase client factories without opening a connection at import time.
Nothing here touches a database.
"""

import importlib
import inspect

import pytest

ENGINE_MODULES = [
    "app.engines",
    "app.engines.lce",
    "app.engines.lci",
    "app.engines.alerts",
    "app.engines.pulse",
    "app.engines.cards",
    "app.engines.strategies",
]


@pytest.mark.parametrize("module_name", ENGINE_MODULES + ["app.seed", "app.auth", "app.db"])
def test_foundation_module_imports(module_name):
    module = importlib.import_module(module_name)
    assert module is not None


@pytest.mark.parametrize("module_name", ENGINE_MODULES + ["app.seed"])
def test_engine_and_seed_stubs_have_a_docstring(module_name):
    module = importlib.import_module(module_name)
    # Each stub documents its authoritative spec + module file; the docstring is
    # the contract until the logic lands.
    assert module.__doc__ is not None and len(module.__doc__.strip()) > 0


@pytest.mark.parametrize("module_name", ENGINE_MODULES)
def test_engine_stubs_define_no_logic(module_name):
    module = importlib.import_module(module_name)
    # A stub defines no functions or classes of its own yet. Anything callable
    # here would be un-spec'd engine logic shipped ahead of the seed (Q7) and the
    # required table-driven tests, which the hard rules forbid.
    own_members = [
        name
        for name, obj in vars(module).items()
        if not name.startswith("__")
        and (inspect.isfunction(obj) or inspect.isclass(obj))
        and getattr(obj, "__module__", None) == module_name
    ]
    assert own_members == [], f"{module_name} should be a stub with no logic, found {own_members}"


def test_db_exposes_the_two_clients():
    from app import db

    assert hasattr(db, "get_anon_client")
    assert hasattr(db, "get_service_client")
    # Signature check only (no call): the anon factory takes an optional token so
    # it can be built per request with the caller's session for RLS scoping.
    sig = inspect.signature(db.get_anon_client)
    assert "access_token" in sig.parameters


def test_engines_package_flags_the_seed_blocker():
    import app.engines as engines

    doc = engines.__doc__ or ""
    # The blocker must be visible at the package level so no one builds the LCE
    # before the Knowledge Base + Tag Architecture exist.
    assert "BLOCK" in doc.upper()
    assert "SeedData.md" in doc
