"""
Escalation of an issue along the committee chain: CCGP (village) -> CLGP (commune) -> national
committee. Used by the dashboard buttons, the automatic escalation task and the mobile API, so that
every escalation reassigns the issue, leaves a trace in the history and notifies the citizen the
same way.
"""

import logging

from django.utils import timezone
from django.utils.translation import gettext as _

from grm.notifications import send_issue_notification
from issues.models import Comment

logger = logging.getLogger(__name__)


def can_be_escalated(issue):
    """Resolved and rejected issues are closed: they are neither escalated nor de-escalated."""
    status = issue.status
    return not (status and (status.final_status or status.rejected_status))


def escalate_issue(issue, user=None, reason="", automatic=False):
    """
    Reassign ``issue`` to the next committee up and return the new assignee (``None`` when the
    issue is closed or already handled by the top committee).

    - ``user``: who escalated (``None`` for the system).
    - ``reason``: why (required on the mobile app, stored in ``escalation_reason``).
    - ``automatic``: escalation triggered because the processing time was exceeded.
    """
    if not can_be_escalated(issue):
        return None
    target = issue.get_assignee_to_escalate()
    if target is None:
        return None

    issue.assignee = target
    issue.escalate_flag = False
    issue.escalated_date = timezone.now()
    if reason:
        issue.escalation_reason = reason
    issue.save()

    if automatic:
        text = _(
            "The complaint has been escalated automatically to %(committee)s because the processing time has passed."
        )
    elif reason:
        text = _("The complaint has been escalated to %(committee)s. Reason: %(reason)s")
    else:
        text = _("The complaint has been escalated to %(committee)s.")
    Comment.objects.create(user=user, issue=issue, comment=text % {"committee": target.name, "reason": reason})

    try:
        send_issue_notification(issue, "escalated")
    except Exception:
        logger.exception("Failed to send escalation notification for issue %s", issue.id)
    return target


def de_escalate_issue(issue, user=None):
    """
    Reassign ``issue`` to the next committee down towards the issue location and return the new
    assignee (``None`` when closed or already at its lowest committee). The citizen is not notified.
    """
    if not can_be_escalated(issue):
        return None
    target = issue.get_assignee_to_de_escalate()
    if target is None:
        return None

    issue.assignee = target
    issue.escalate_flag = False
    issue.save()
    Comment.objects.create(
        user=user,
        issue=issue,
        comment=_("The complaint has been sent back to %(committee)s.") % {"committee": target.name},
    )
    return target
