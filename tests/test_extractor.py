"""Unit tests for the AST import extractor — the static-analysis core."""

from pathlib import Path

import pytest

from pydeadweight.extractor import extract_imports, extract_imports_from_source


def test_plain_import():
    assert extract_imports_from_source("import requests") == {"requests"}


def test_multiple_and_dotted_imports():
    src = "import os, requests.adapters\nimport django.db.models"
    assert extract_imports_from_source(src) == {"os", "requests", "django"}


def test_from_import_reduces_to_top_level():
    assert extract_imports_from_source("from foo.bar import baz") == {"foo"}


def test_relative_imports_are_skipped():
    src = "from . import utils\nfrom ..pkg import thing\nfrom .local import x"
    assert extract_imports_from_source(src) == set()


def test_aliased_import():
    assert extract_imports_from_source("import numpy as np") == {"numpy"}


def test_import_inside_function_and_try():
    src = (
        "def f():\n"
        "    import lazy_dep\n"
        "try:\n"
        "    import fast_json as json\n"
        "except ImportError:\n"
        "    import json\n"
    )
    assert extract_imports_from_source(src) == {"lazy_dep", "fast_json", "json"}


def test_type_checking_imports_count():
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import pandas\n"
    )
    assert "pandas" in extract_imports_from_source(src)


def test_import_in_string_or_comment_is_not_counted():
    src = '# import evil\ns = "import alsoevil"\nimport real\n'
    assert extract_imports_from_source(src) == {"real"}


def test_future_import_top_level():
    # __future__ is stdlib; extractor still reports it (stdlib filtered later).
    assert extract_imports_from_source("from __future__ import annotations") == {
        "__future__"
    }


def test_syntax_error_file_is_skipped_not_fatal(tmp_path: Path):
    good = tmp_path / "good.py"
    good.write_text("import requests\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")

    imports, skipped = extract_imports([good, bad])
    modules = {imp.module for imp in imports}
    assert modules == {"requests"}
    assert len(skipped) == 1
    assert "bad.py" in skipped[0].path


def test_provenance_recorded(tmp_path: Path):
    f = tmp_path / "m.py"
    f.write_text("import click\n", encoding="utf-8")
    imports, _ = extract_imports([f])
    assert imports[0].module == "click"
    assert imports[0].source_file == str(f)
