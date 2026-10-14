from datetime import date

from pipeline.publish import is_publish_week


def test_biweekly_parity():
    # anchor ISO week 42 of 2026 (Monday 12 Oct 2026)
    assert is_publish_week(date(2026, 10, 12))
    assert is_publish_week(date(2026, 10, 14))
    assert not is_publish_week(date(2026, 10, 19))
    assert is_publish_week(date(2026, 10, 26))
    # crosses the year boundary correctly (2026 has 53 ISO weeks)
    assert is_publish_week(date(2027, 1, 4)) == (((date(2027, 1, 4) - date(2026, 10, 12)).days // 7) % 2 == 0)
