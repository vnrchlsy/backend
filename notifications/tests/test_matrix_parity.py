"""US-P3 · Tech Spec §14 <-> notifications.types.REGISTRY parity.

Guards against the two staying in sync only by discipline: if a type is added, renamed,
or re-pointed to a different deep_link in the registry without updating §14 (or vice
versa), this test fails. `dev/check-docs.py::check_notification_matrix` enforces the same
invariant from the docs side; this is the backend-side half of the same guard.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]  # the docs workspace, one level above backend/
SPEC = ROOT / "KupkopPH-Technical-Spec.html"
CHECKDOCS = ROOT / "dev" / "check-docs.py"

# The Tech Spec and check-docs.py live in a SEPARATE repository. In a backend-only
# checkout — which is what CI clones — neither file is present, and this cross-repo
# guard has nothing to compare against. Skip rather than fail: a missing sibling repo
# is not a parity violation. `dev/check-docs.py::check_notification_matrix` enforces
# the same invariant from the docs side whenever backend/ is checked out alongside.
pytestmark = pytest.mark.skipif(
    not (SPEC.exists() and CHECKDOCS.exists()),
    reason="docs repo not checked out alongside backend/ — §14 parity runs in the docs workspace",
)


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
