from pathlib import Path

from escalane.catalog import compute_catalog_hash, load_catalog


def test_catalog_hash_stable(repo_root: Path, tmp_path: Path):
    src = repo_root / "datasets" / "sysops_decide" / "catalog.yaml"
    if not src.is_file():
        src = repo_root / "src" / "escalane" / "examples" / "catalog.yaml"
    h1 = compute_catalog_hash(src)
    h2 = compute_catalog_hash(src)
    assert h1 == h2
    assert h1.startswith("sha256:")
    cat = load_catalog(src)
    assert cat.catalog_hash == h1
    assert "escalate" in cat.ids

    mutated = tmp_path / "catalog.yaml"
    text = src.read_text(encoding="utf-8")
    mutated.write_text(text + "\n# touch\n", encoding="utf-8")
    assert compute_catalog_hash(mutated) != h1


def test_catalog_load_has_criteria(catalog):
    assert catalog.criteria_map()
    assert "restart_php_fpm" in catalog.ids or "clear_tmp_disk" in catalog.ids
