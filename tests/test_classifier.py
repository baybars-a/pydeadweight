"""Unit tests for the classifier + convention layer.

Resolution is constructed by hand so these tests don't depend on what's
actually installed in the environment.
"""

from pydeadweight.classifier import classify
from pydeadweight.config import Config
from pydeadweight.models import DeclaredDependency, Status
from pydeadweight.resolution import Resolution


def dep(name, *groups):
    return DeclaredDependency(name=name, raw_spec=name, groups=groups or ("main",))


def make_resolution(mapping):
    dist_to_imports = {k: frozenset(v) for k, v in mapping.items()}
    return Resolution(
        dist_to_imports=dist_to_imports,
        installed_dists=frozenset(mapping.keys()),
    )


def status_of(results, name):
    return next(c for c in results if c.dependency.name == name).status


def test_used_when_provided_import_appears():
    res = make_resolution({"requests": {"requests"}})
    out = classify([dep("requests")], {"requests"}, res, Config())
    assert status_of(out, "requests") is Status.USED


def test_unused_when_installed_but_not_imported():
    res = make_resolution({"requests": {"requests"}})
    out = classify([dep("requests")], {"os"}, res, Config())
    assert status_of(out, "requests") is Status.UNUSED


def test_name_mismatch_pillow_pil():
    # Pillow provides the PIL import name; importing PIL means Pillow is used.
    res = make_resolution({"pillow": {"PIL"}})
    out = classify([dep("pillow")], {"PIL"}, res, Config())
    assert status_of(out, "pillow") is Status.USED


def test_not_installed_is_unknown_not_unused():
    res = make_resolution({})  # nothing installed
    out = classify([dep("requests")], {"os"}, res, Config())
    c = next(c for c in out if c.dependency.name == "requests")
    assert c.status is Status.UNKNOWN
    assert "not installed" in c.reason


def test_allowlist_forces_used():
    res = make_resolution({"gunicorn": set()})
    cfg = Config(ignore=("gunicorn",))
    out = classify([dep("gunicorn")], set(), res, cfg)
    c = next(c for c in out if c.dependency.name == "gunicorn")
    assert c.status is Status.USED
    assert "allowlist" in c.reason


def test_builtin_runtime_only_kept():
    # psycopg2 is installed, provides an import name, but isn't imported.
    res = make_resolution({"psycopg2": {"psycopg2"}})
    out = classify([dep("psycopg2")], set(), res, Config())
    c = next(c for c in out if c.dependency.name == "psycopg2")
    assert c.status is Status.USED
    assert "runtime-only" in c.reason


def test_config_runtime_only_extends_list():
    res = make_resolution({"my-driver": {"my_driver"}})
    cfg = Config(runtime_only=("my-driver",))
    out = classify([dep("my-driver")], set(), res, cfg)
    assert status_of(out, "my-driver") is Status.USED


def test_installed_no_importable_module_is_unknown():
    res = make_resolution({"weirdpkg": set()})
    out = classify([dep("weirdpkg")], set(), res, Config())
    c = next(c for c in out if c.dependency.name == "weirdpkg")
    assert c.status is Status.UNKNOWN
    assert "no importable" in c.reason
