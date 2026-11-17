"""Catalog hash stability + unknown playbook handling."""

from __future__ import annotations

import pytest

from escalane.catalog import CatalogError, compute_catalog_hash, load_catalog


def test_catalog_hash_stable_and_unknown(catalog, suite_catalog_path):
    h1 = compute_catalog_hash(suite_catalog_path)
    h2 = catalog.catalog_hash
    assert h1 == h2
    assert "escalate" in catalog.ids
    with pytest.raises(CatalogError, match="unknown playbook"):
        catalog.get("not_in_catalog")


def test_reload_same_hash(suite_catalog_path):
    a = load_catalog(suite_catalog_path)
    b = load_catalog(suite_catalog_path)
    assert a.catalog_hash == b.catalog_hash
    assert a.ids == b.ids
