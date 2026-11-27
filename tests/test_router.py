from ahsr.router.heuristic import HeuristicRouter

r = HeuristicRouter()


def test_identifiers_route_sparse():
    for q in ["ERR_0x884A", "--max-retries", "client.create_webhook(url, secret)",
              "rotate_webhook_secret grace_period_s", "what does ERR_0x884A mean"]:
        d = r.route(q)
        assert d.label == "identifier", (q, d)
        assert d.sparse_weight > d.dense_weight


def test_concepts_route_dense():
    for q in ["how to stop billing", "my webhook signature check keeps failing",
              "how do I preview a deployment without applying it"]:
        d = r.route(q)
        assert d.label == "conceptual", (q, d)
        assert d.dense_weight > d.sparse_weight


def test_weights_never_silence_an_engine():
    for q in ["ERR_0x884A", "how to stop billing"]:
        d = r.route(q)
        assert d.sparse_weight >= 0.2 and d.dense_weight >= 0.2
