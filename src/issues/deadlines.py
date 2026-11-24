"""
Processing deadlines of the committees (COSO: CCGP 3, CLGP 3, national 5 working days).

- The deadline is the committee's ``IssueDepartment.processing_days``, or the category's
  ``IssueCategory.processing_days`` when set (e.g. GBV / SEA / SH cases).
- It is counted in working days (Monday to Friday, public holidays are not handled) from the
  reception by the committee: the issue creation, or its last escalation.
- An open issue past its deadline is escalated to the next committee; at the top (national
  committee) it is only marked as overdue.
"""

from datetime import date, timedelta

from django.utils import timezone

SATURDAY = 5


def add_working_days(start: date, days: int) -> date:
    """Date ``days`` working days after ``start`` (weekends skipped)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < SATURDAY:
            remaining -= 1
    return current


def working_days_between(start: date, end: date) -> int:
    """Working days after ``start`` up to ``end`` included (0 when ``end`` <= ``start``)."""
    if end <= start:
        return 0
    days = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < SATURDAY:
            days += 1
    return days


def processing_days(issue):
    """Processing time of the committee in charge, in working days (None: no deadline)."""
    category = issue.category
    if category is not None and category.processing_days:
        return category.processing_days
    worker = getattr(issue.assignee, "governmentworker", None) if issue.assignee_id else None
    if worker is None:
        return None
    return worker.department.processing_days or None


def reception_date(issue):
    """When the committee in charge received the issue: creation or last escalation (local date)."""
    moments = [m for m in (issue.created_date, issue.escalated_date) if m]
    if not moments:
        return None
    return timezone.localdate(max(moments))


def is_closed(issue):
    status = issue.status
    return bool(status and (status.final_status or status.rejected_status))


def processing_deadline(issue):
    days = processing_days(issue)
    start = reception_date(issue)
    if not days or start is None or is_closed(issue):
        return None
    return add_working_days(start, days)


def is_overdue(issue, today=None):
    deadline = processing_deadline(issue)
    if deadline is None:
        return False
    return (today or timezone.localdate()) > deadline
