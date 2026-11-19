"""Д1.1: правило «команда підтверджує за 10 хв; рівно на межі заявка переходить іншій команді».
Запуск із web/server:  python -m unittest discover -s tests -v
"""

import unittest
from datetime import UTC, datetime, timedelta, timezone

from app.timerules import accept_deadline, is_accept_expired

KYIV_WINTER = timezone(timedelta(hours=2))


class AcceptDeadline(unittest.TestCase):
    def test_ten_minutes(self):
        created = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
        self.assertEqual(accept_deadline(created), datetime(2026, 11, 19, 12, 10, tzinfo=UTC))

    def test_before_boundary_not_expired(self):
        d = datetime(2026, 11, 19, 12, 10, tzinfo=UTC)
        self.assertFalse(is_accept_expired(d, d - timedelta(microseconds=1)))

    def test_exactly_on_boundary_expired(self):
        d = datetime(2026, 11, 19, 12, 10, tzinfo=UTC)
        self.assertTrue(is_accept_expired(d, d))

    def test_same_moment_other_offset(self):
        # 14:10+02:00 і 12:10Z — один момент: порівнюються моменти, а не рядки
        d = datetime(2026, 11, 19, 12, 10, tzinfo=UTC)
        self.assertTrue(is_accept_expired(d, datetime(2026, 11, 19, 14, 10, tzinfo=KYIV_WINTER)))

    def test_naive_rejected(self):
        with self.assertRaises(ValueError):
            accept_deadline(datetime(2026, 11, 19, 12, 0))


if __name__ == "__main__":
    unittest.main()
