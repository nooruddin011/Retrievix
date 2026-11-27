import pytest

from ahsr.config import Settings
from ahsr.ingestion.ingest import ingest_directory, remove_document, sync_directory, sync_document
from ahsr.models.hashing import HashDenseEncoder, HashSparseEncoder
from ahsr.retrieval.store import HybridStore

DOC_A = "# Alpha\n\n## One\nFirst section about apples.\n\n## Two\nSecond section about oranges.\n"
DOC_B = "# Beta\n\n## Only\nA single section about bananas.\n"


def fresh(tmp_path, docs):
    d = tmp_path / "docs"
    d.mkdir(exist_ok=True)
    for n, t in docs.items():
        (d / n).write_text(t)
    return HybridStore(Settings(qdrant_url=":memory:")), HashDenseEncoder(), HashSparseEncoder(), d


def test_first_sync_indexes_everything_and_second_is_a_noop(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A, "b.md": DOC_B})
    r1 = sync_directory(store, dense, sparse, d)
    assert (r1.chunks, r1.added, r1.removed, r1.documents) == (3, 3, 0, 2) and store.count() == 3
    r2 = sync_directory(store, dense, sparse, d)
    assert (r2.added, r2.removed, r2.unchanged) == (0, 0, 3)


def test_editing_one_section_only_reindexes_that_chunk(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A, "b.md": DOC_B})
    sync_directory(store, dense, sparse, d)
    (d / "a.md").write_text(DOC_A.replace("oranges", "mangoes"))
    r = sync_directory(store, dense, sparse, d)
    assert (r.added, r.removed, r.unchanged) == (1, 1, 2) and store.count() == 3


def test_deleted_file_is_removed_from_index(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A, "b.md": DOC_B})
    sync_directory(store, dense, sparse, d)
    (d / "b.md").unlink()
    r = sync_directory(store, dense, sparse, d)
    assert r.removed == 1 and store.count() == 2 and "b.md" not in store.ids_by_source()


def test_upserts_happen_before_deletes_so_index_never_empties(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A})
    sync_directory(store, dense, sparse, d)
    calls = []
    real_upsert, real_delete = store.upsert, store.delete_ids
    store.upsert = lambda *a, **k: (calls.append("upsert"), real_upsert(*a, **k))[1]
    store.delete_ids = lambda ids: (calls.append("delete"), real_delete(ids))[1]
    (d / "a.md").write_text("# Alpha\n\n## One\nCompletely new text.\n")
    sync_directory(store, dense, sparse, d)
    assert calls.index("upsert") < calls.index("delete")


def test_full_rebuild_and_dimension_change_trigger_rebuild(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A})
    sync_directory(store, dense, sparse, d)
    assert sync_directory(store, dense, sparse, d, full=True).rebuilt is True

    class Narrow(HashDenseEncoder):
        dim = 128
    narrow = Narrow()
    assert store.compatible(narrow.dim) is False
    r = sync_directory(store, narrow, sparse, d)                # model swap: rebuild instead of failing at upsert
    assert r.rebuilt is True and store.count() == r.chunks


def test_missing_docs_dir_raises_instead_of_wiping_the_index(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A})
    sync_directory(store, dense, sparse, d)
    with pytest.raises(FileNotFoundError):
        sync_directory(store, dense, sparse, tmp_path / "nope")
    assert store.count() == 2


def test_single_document_sync_and_removal(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A})
    sync_directory(store, dense, sparse, d)
    assert sync_document(store, dense, sparse, d, "new.md", DOC_B) == (1, 0)
    assert sync_document(store, dense, sparse, d, "new.md", DOC_B) == (0, 0)
    assert remove_document(store, "new.md") == 1 and "new.md" not in store.ids_by_source()


def test_search_on_empty_store_returns_nothing_instead_of_raising(tmp_path):
    store, dense, sparse, _ = fresh(tmp_path, {})
    assert store.dense_search(dense.encode(["x"], is_query=True)[0], 3) == []
    assert store.sparse_search(sparse.encode(["x"], is_query=True)[0], 3) == []


def test_ingest_directory_backcompat_returns_chunk_count(tmp_path):
    store, dense, sparse, d = fresh(tmp_path, {"a.md": DOC_A})
    assert ingest_directory(store, dense, sparse, d) == 2
