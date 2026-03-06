"""Tests for ingest hash store manager.

Covers load, save, check, add, corrupt file quarantine,
metadata storage, and deterministic behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avos_cli.config.hash_store import IngestHashStore


@pytest.fixture()
def avos_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".avos"
    d.mkdir()
    return d


@pytest.fixture()
def store(avos_dir: Path) -> IngestHashStore:
    return IngestHashStore(avos_dir)


class TestLoad:
    def test_load_returns_empty_when_no_file(self, store: IngestHashStore):
        store.load()
        assert store.count() == 0

    def test_load_reads_existing_hashes(self, avos_dir: Path):
        data = {
            "abc123": {
                "artifact_type": "pr",
                "source_id": "42",
                "stored_at": "2026-01-15T10:00:00Z",
            }
        }
        (avos_dir / "ingest_hashes.json").write_text(json.dumps(data))

        store = IngestHashStore(avos_dir)
        store.load()
        assert store.contains("abc123")
        assert store.count() == 1

    def test_load_quarantines_corrupt_file(self, avos_dir: Path):
        (avos_dir / "ingest_hashes.json").write_text("{bad json")

        store = IngestHashStore(avos_dir)
        store.load()
        assert store.count() == 0
        corrupt_files = list(avos_dir.glob("ingest_hashes.json.corrupt.*"))
        assert len(corrupt_files) == 1


class TestContains:
    def test_contains_returns_false_for_unknown(self, store: IngestHashStore):
        store.load()
        assert not store.contains("unknown_hash")

    def test_contains_returns_true_for_known(self, store: IngestHashStore):
        store.load()
        store.add("hash1", "pr", "42")
        assert store.contains("hash1")


class TestAdd:
    def test_add_stores_hash_with_metadata(self, store: IngestHashStore):
        store.load()
        store.add("hash1", "pr", "42")
        assert store.contains("hash1")

    def test_add_duplicate_is_idempotent(self, store: IngestHashStore):
        store.load()
        store.add("hash1", "pr", "42")
        store.add("hash1", "pr", "42")
        assert store.count() == 1

    def test_add_multiple_distinct_hashes(self, store: IngestHashStore):
        store.load()
        store.add("h1", "pr", "1")
        store.add("h2", "issue", "2")
        store.add("h3", "commit", "abc")
        assert store.count() == 3


class TestSave:
    def test_save_creates_file(self, store: IngestHashStore, avos_dir: Path):
        store.load()
        store.add("hash1", "pr", "42")
        store.save()
        assert (avos_dir / "ingest_hashes.json").exists()

    def test_save_roundtrip(self, avos_dir: Path):
        store1 = IngestHashStore(avos_dir)
        store1.load()
        store1.add("h1", "pr", "1")
        store1.add("h2", "issue", "2")
        store1.save()

        store2 = IngestHashStore(avos_dir)
        store2.load()
        assert store2.contains("h1")
        assert store2.contains("h2")
        assert store2.count() == 2

    def test_save_preserves_metadata(self, avos_dir: Path):
        store = IngestHashStore(avos_dir)
        store.load()
        store.add("hash1", "pr", "42")
        store.save()

        raw = json.loads((avos_dir / "ingest_hashes.json").read_text())
        entry = raw["hash1"]
        assert entry["artifact_type"] == "pr"
        assert entry["source_id"] == "42"
        assert "stored_at" in entry

    def test_save_empty_store(self, store: IngestHashStore, avos_dir: Path):
        store.load()
        store.save()
        raw = json.loads((avos_dir / "ingest_hashes.json").read_text())
        assert raw == {}


class TestCount:
    def test_count_zero_initially(self, store: IngestHashStore):
        store.load()
        assert store.count() == 0

    def test_count_after_adds(self, store: IngestHashStore):
        store.load()
        store.add("a", "pr", "1")
        store.add("b", "issue", "2")
        assert store.count() == 2


class TestEdgeCases:
    def test_empty_file_treated_as_empty_store(self, avos_dir: Path):
        (avos_dir / "ingest_hashes.json").write_text("")
        store = IngestHashStore(avos_dir)
        store.load()
        assert store.count() == 0

    def test_non_dict_json_treated_as_corrupt(self, avos_dir: Path):
        (avos_dir / "ingest_hashes.json").write_text('["not", "a", "dict"]')
        store = IngestHashStore(avos_dir)
        store.load()
        assert store.count() == 0

    def test_stored_at_is_iso_format(self, store: IngestHashStore):
        store.load()
        store.add("h1", "pr", "1")
        entry = store.get_entry("h1")
        assert entry is not None
        assert "T" in entry["stored_at"]
