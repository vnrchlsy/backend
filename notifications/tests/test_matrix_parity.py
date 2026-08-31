"""US-P3 · Tech Spec §14 <-> notifications.types.REGISTRY parity.

Guards against the two staying in sync only by discipline: if a type is added, renamed,
or re-pointed to a different deep_link in the registry without updating §14 (or vice
versa), this test fails. `dev/check-docs.py::check_notification_matrix` enforces the same
invariant from the docs side; this is the backend-side half of the same guard.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]  # repo root


def _load_checkdocs():
    spec = importlib.util.spec_from_file_location("checkdocs", ROOT / "dev" / "check-docs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_matrix_matches_registry():
    cd = _load_checkdocs()
    parsed = cd.parse_notification_matrix(ROOT / "KupkopPH-Technical-Spec.html")  # {type: (push, deep_link)}

    from notifications.types import REGISTRY

    assert parsed is not None
    assert set(parsed) == set(REGISTRY)
    for k, t in REGISTRY.items():
        assert parsed[k] == (t.push, t.deep_link), k
