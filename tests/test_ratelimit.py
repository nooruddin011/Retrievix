from ahsr.ratelimit import TokenBucketLimiter


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_burst_then_throttle_then_refill():
    clock = Clock()
    lim = TokenBucketLimiter(60, clock=clock)                  # 1 token / second, burst 60
    assert all(lim.check("a")[0] for _ in range(60))
    ok, retry = lim.check("a")
    assert not ok and 0.9 < retry <= 1.0
    clock.t += 2
    assert lim.check("a")[0] and lim.check("a")[0] and not lim.check("a")[0]


def test_keys_are_independent_and_costs_apply():
    lim = TokenBucketLimiter(10, clock=Clock())
    assert lim.check("a", cost=10)[0] and not lim.check("a")[0]
    assert lim.check("b")[0]
    assert lim.check("c", cost=1000)[0]                         # capped at capacity: never permanently locked out


def test_disabled_limiter_allows_everything():
    lim = TokenBucketLimiter(0)
    assert all(lim.check("a", cost=100)[0] for _ in range(1000))
