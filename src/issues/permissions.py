from datetime import timedelta

from django.http import Http404
from django.utils.timezone import now
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import SAFE_METHODS, BasePermission

from grm.constants import ISSUE_CLOSED_ERROR_MESSAGE
from issues.models import Issue


class IsReporterOrAssigneePermission(BasePermission):
    """
    Custom permission to only allow reporters or assignees to view an issue.

    This permission checks if the requesting user is either:
    - The reporter of the issue
    - The assignee of the issue
    """

    def has_object_permission(self, request, view, obj):
        """
        Check if the user has permission to access this specific issue.

        Args:
            request: HTTP request object
            view: The view being accessed
            obj: The Issue object being accessed

        Returns:
            bool: True if user is reporter or assignee, False otherwise
        """
        # Allow access if user is the reporter or assignee
        return request.user == obj.reporter or request.user == obj.assignee

    def has_permission(self, request, view):
        """
        Check if the user has permission to access the view based on the issue context.

        This method is evaluated before accessing the queryset or any specific object.
        It ensures that the requesting user is either the reporter or the assignee of
        the issue referenced in the URL (via the "id" parameter).

        Args:
            request: HTTP request object
            view: The view being accessed

        Returns:
            bool: True if user is the reporter or assignee of the issue, False otherwise
        """
        issue_id = view.kwargs.get("id")
        if not issue_id:
            return True  # No issue context available, allow access
        if hasattr(view, "get_issue"):
            try:
                issue = view.get_issue()
            except Exception:
                raise Http404
        else:
            issue = get_object_or_404(Issue, id=issue_id)
        return request.user == issue.reporter or request.user == issue.assignee


# The app closes an issue (status resolved / rejected) and then sends the comment and the files of
# that action, in the same synchronisation even when it was offline. The closing committee may
# therefore still add them shortly after the closure date (set by the server at reception).
CLOSING_ACTION_GRACE_PERIOD = timedelta(hours=1)


class IssueNotClosedPermission(BasePermission):
    """
    A resolved or rejected issue can no longer be modified by the committee: no new comment
    (step) or attachment, no deletion. Read access is unchanged. Exception: the closing committee
    can add the comment / files of the closing action during CLOSING_ACTION_GRACE_PERIOD.
    """

    message = ISSUE_CLOSED_ERROR_MESSAGE

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or not view.kwargs.get("id"):
            return True
        try:
            issue = view.get_issue() if hasattr(view, "get_issue") else Issue.objects.get(id=view.kwargs["id"])
        except Exception:
            return True  # missing issue: answered by the other permissions / the view (404)
        status = issue.status
        if not (status and (status.final_status or status.rejected_status)):
            return True
        return (
            request.method == "POST"
            and request.user == issue.assignee
            and issue.resolution_date is not None
            and now() - issue.resolution_date <= CLOSING_ACTION_GRACE_PERIOD
        )
