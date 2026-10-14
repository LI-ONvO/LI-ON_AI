"""시험일정 배치의 빈자리 추가접수 제외 필터."""

from datetime import date

from batch.sync_certifications import drop_extra_registrations


def _row(seq: str, start: date | None) -> dict:
    return {"impl_seq": seq, "doc_reg_start_dt": start}


def test_keeps_earliest_registration_per_round():
    """같은 회차 두 줄 중 먼저 시작하는 정기 접수만 남긴다(프로그래밍기능사 2026 제4회)."""
    rows = [_row("4", date(2026, 9, 10)), _row("4", date(2026, 8, 24))]

    assert drop_extra_registrations(rows) == [_row("4", date(2026, 8, 24))]


def test_keeps_practical_only_round():
    """필기 없이 실기만 있는 제0회는 회차가 달라 그대로 남는다."""
    rows = [_row("0", None), _row("1", date(2026, 1, 6)), _row("1", date(2026, 1, 14))]

    kept = drop_extra_registrations(rows)

    assert _row("0", None) in kept
    assert len(kept) == 2


def test_prefers_dated_row_over_missing_date():
    rows = [_row("2", None), _row("2", date(2026, 3, 16))]

    assert drop_extra_registrations(rows) == [_row("2", date(2026, 3, 16))]
