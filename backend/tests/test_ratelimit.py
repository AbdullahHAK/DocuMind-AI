from app.ratelimit import DailyBudget, SlidingWindowLimiter


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_allows_up_to_limit_then_blocks_with_retry_after():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.check("ip")[0]
    assert limiter.check("ip")[0]
    allowed, retry = limiter.check("ip")
    assert not allowed and 1 <= retry <= 61


def test_window_slides():
    clock = Clock()
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.check("ip")[0]
    clock.t += 61
    assert limiter.check("ip")[0]


def test_keys_are_independent():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60, clock=Clock())
    assert limiter.check("a")[0]
    assert limiter.check("b")[0]
    assert not limiter.check("a")[0]


def test_daily_budget_resets_on_new_day():
    day = ["2026-10-15"]
    budget = DailyBudget(limit=1, today=lambda: day[0])
    assert budget.try_spend()
    assert not budget.try_spend()
    day[0] = "2026-10-16"
    assert budget.try_spend()
