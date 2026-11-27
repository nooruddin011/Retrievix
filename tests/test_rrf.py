from ahsr.retrieval.hybrid import rrf_fuse
from ahsr.types import Hit


def H(i):
    return Hit(id=i, score=0.0, text=i, payload={"source": i})


def test_rrf_rewards_agreement():
    fused = rrf_fuse([[H("a"), H("b"), H("c")], [H("c"), H("b"), H("d")]], [1, 1], k=60)
    # b and c appear in BOTH lists, a and d in only one -> agreement wins
    assert {h.id for h in fused[:2]} == {"b", "c"}


def test_rrf_weights_shift_ranking():
    dense, sparse = [H("a"), H("b")], [H("b"), H("a")]
    assert rrf_fuse([dense, sparse], [1.8, 0.2])[0].id == "a"
    assert rrf_fuse([dense, sparse], [0.2, 1.8])[0].id == "b"


def test_rrf_records_per_engine_ranks():
    top = rrf_fuse([[H("a")], [H("z"), H("a")]], [1, 1], labels=["dense", "sparse"])[0]
    assert top.id == "a" and top.ranks == {"dense": 1, "sparse": 2}
