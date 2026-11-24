import logging

from celery import shared_task
from celery.schedules import crontab
from django.conf import settings
from django.core.management import call_command
from django.db.models import F, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Extract, Now
from django.db.models.functions.comparison import Cast
from django.utils import timezone
from django.utils.translation import gettext as _

from dashboard.constants import MONTHLY_CHOICE, QUARTERLY_CHOICE, WEEKLY_CHOICE
from grm.celery_app import app
from issues.models import Comment, Issue, IssueStatusChange

COUCHDB_GRM_DATABASE = settings.COUCHDB_GRM_DATABASE

logger = logging.getLogger(__name__)


ANONYMIZED_VALUE = "*"


def _issues_needing_backfill():
    """
    Confirmed issues for which at least one backfill step is still pending:
    no internal code, citizen name not anonymized yet, contact not anonymized yet,
    or no assignee.
    """
    missing_internal_code = Q(internal_code__isnull=True) | Q(internal_code="")
    citizen_not_anonymized = Q(citizen__isnull=False) & ~Q(citizen__name=ANONYMIZED_VALUE)
    contact_not_anonymized = Q(contact_information__isnull=False) & ~Q(contact_information__in=["", ANONYMIZED_VALUE])
    missing_assignee = Q(assignee__isnull=True)

    return (
        Issue.objects.filter(confirmed=True)
        .filter(missing_internal_code | citizen_not_anonymized | contact_not_anonymized | missing_assignee)
        .select_related('administrative_region', 'category', 'citizen')
    )


@app.task
def check_issues():
    """
    Check the issues without internal_code, citizen information anonymization
    or assignee, and try to set a value for these fields.

    Each step of each issue is isolated: a failure is recorded in ``result["errors"]``
    and never prevents the other steps or the other issues from being processed.
    """
    result = {
        "errors": [],
        "internal_code_updated": [],
        "anonymized_data": [],
        "assignee_updated": [],
    }
    updated_issues = 0
    for issue in _issues_needing_backfill():
        changed = False
        new_assignee = None

        # set internal_code if needed
        if not issue.internal_code:
            try:
                issue.internal_code = issue.get_internal_code()
                changed = True
                result["internal_code_updated"].append(issue.id)
            except Exception:
                logger.exception("check_issues: cannot compute internal code for issue %s", issue.id)
                result["errors"].append(f"Error trying to set internal code for issue with id {issue.id}")

        # anonymize citizen name and contact information when not done yet
        citizen = issue.citizen
        contact_information = issue.contact_information
        if (citizen and citizen.name != ANONYMIZED_VALUE) or (
            contact_information and contact_information != ANONYMIZED_VALUE
        ):
            try:
                issue.anonymize_issue_data()
                changed = True
                result["anonymized_data"].append(issue.id)
            except Exception:
                logger.exception("check_issues: cannot anonymize issue %s", issue.id)
                result["errors"].append(f"Error trying to anonymize issue with id {issue.id}")

        # set assignee if not defined yet
        if not issue.assignee_id:
            try:
                new_assignee = issue.get_assignee()
                if new_assignee:
                    issue.assignee = new_assignee
                    changed = True
            except Exception:
                new_assignee = None
                logger.exception("check_issues: cannot find an assignee for issue %s", issue.id)
                result["errors"].append(f"Error trying to set assignee for issue with id {issue.id}")

        if not changed:
            continue

        try:
            issue.save()
        except Exception:
            logger.exception("check_issues: cannot save issue %s", issue.id)
            result["errors"].append(f"Error trying to save issue with id {issue.id}")
            continue

        updated_issues += 1
        if new_assignee:
            result["assignee_updated"].append(issue.id)
            # System comment (user=None), created only once the assignment is persisted
            Comment.objects.create(
                user=None,
                comment=_("The issue has been assigned to %s.") % new_assignee.name,
                issue=issue,
            )

    result["updated_issues"] = updated_issues
    return result


@app.task
def escalate_issues():
    issues = Issue.objects.filter(confirmed=True, escalate_flag=True, assignee__isnull=False)
    result = {
        "issues_updated": [],
        "scale_is_not_available": [],
    }
    updated_issues = 0
    now = timezone.now()
    for issue in issues:
        issues_updated = False
        assignee = issue.get_assignee_to_escalate(issue.assignee.governmentworker.administrative_region)
        if assignee:
            issue.assignee = assignee
            issue.escalate_flag = False
            issue.escalated_date = now
            result["issues_updated"].append(issue.id)
            issues_updated = True
            Comment.objects.create(
                user=None,  # take None like user system
                comment=_("The complaint has been escalated automatically because the processing time has passed."),
                issue=issue,
            )

        else:
            result["scale_is_not_available"].append(issue.id)

        if issues_updated:
            issue.save()
            updated_issues += 1

    result["updated_issues"] = updated_issues
    return result


@app.task
def mark_issues_to_be_escalated():
    """
    Identify and mark issues that have exceeded their escalation threshold.

    An issue is marked for escalation when all of the following conditions are met:
      - It is confirmed.
      - It is not already flagged for escalation.
      - Its current status is neither final nor rejected.
      - Its current status defines a valid `threshold_days_to_escalate`.
      - The issue has remained in its current status longer than that threshold.

    The function performs this efficiently using SQL-level annotations:
      - Retrieves the timestamp of the open IssueStatusChange (the moment the issue
        entered its current status).
      - Computes the number of days spent in the current status directly in SQL.
      - Filters issues that exceed their escalation threshold.
      - Marks all matching issues by setting `escalate_flag=True` in a single bulk update.

    Returns:
        dict: A dictionary with the number of issues updated:
              {"updated_issues": <count>}
    """

    # Subquery: get the entered_at of the open status change
    open_status_change = (
        IssueStatusChange.objects.filter(
            issue=OuterRef("pk"),
            exited_at__isnull=True,
        )
        .order_by()
        .values("entered_at")[:1]
    )

    # Annotate issues with:
    # - entered_at of open status
    # - days_in_status computed in SQL
    issues = (
        Issue.objects.filter(
            confirmed=True,
            escalate_flag=False,
            status__final_status=False,
            status__rejected_status=False,
            status__threshold_days_to_escalate__isnull=False,
        )
        .annotate(
            entered_at=Subquery(open_status_change),
            seconds_in_status=Extract(Now() - F("entered_at"), "epoch"),
            days_in_status=Cast(F("seconds_in_status") / 86400.0, IntegerField()),
        )
        .filter(days_in_status__gt=F("status__threshold_days_to_escalate"))
    )

    # Bulk update: no loops, no per-object save()
    updated_count = issues.update(escalate_flag=True)

    return {"updated_issues": updated_count}


@app.task
def reassign_issues_to_appeal():
    issues = Issue.objects.filter(confirmed=True, appeal_status=True).select_related(
        'category__assigned_appeal_department__department__head'
    )
    result = {
        "issues_updated": [],
        "appeal_is_not_available": [],
    }
    updated_issues = 0
    for issue in issues:
        try:
            assignee = issue.category.assigned_appeal_department.department.head
            issue.assignee = assignee
            if assignee:
                issue.appeal_status = False
                issue.appeal_reason = ''
                result["issues_updated"].append(issue.id)
                issue.save()
                updated_issues += 1
            else:
                result["appeal_is_not_available"].append(issue.id)
        except Exception:
            result["appeal_is_not_available"].append(issue.id)

    result["updated_issues"] = updated_issues
    return result


# test tasks
@app.task
def task_one():
    print(" task one called and worker is running good")
    return "success"


@shared_task
def task_two(x, y):
    print(f" task two called with the arguments {x} and {y}. Worker is running good")
    return x + y


@shared_task
def update_performance_metrics(
    periods=None,
    create_global=False,
    create_regions=True,
    create_categories=False,
    create_region_category=False,
    limit_regions=0,
    offset_regions=0,
    limit_categories=0,
    offset_categories=0,
    batch_size=50,
    no_progress=True,
    dry_run=False,
):
    """
    Wrapper task that calls the management command `populate_performance_metrics`.
    Arguments mirror the command flags; pass them as kwargs when calling the task.

    Examples:
      # Full update (may be heavy)
      update_performance_metrics.delay(periods=['7d','30d','90d'], create_global=True, create_regions=True, create_categories=True, create_region_category=False)

      # Sharded update for worker 1
      update_performance_metrics.delay(create_regions=True, limit_regions=100, offset_regions=0)

      # Sharded update for worker 2
      update_performance_metrics.delay(create_regions=True, limit_regions=100, offset_regions=100)
    """
    periods = periods or [WEEKLY_CHOICE, MONTHLY_CHOICE, QUARTERLY_CHOICE]

    cmd_args = []
    for p in periods:
        cmd_args.extend(['--periods', p])

    if create_global:
        cmd_args.append('--create-global')
    if create_regions:
        cmd_args.append('--create-regions')
    if create_categories:
        cmd_args.append('--create-categories')
    if create_region_category:
        cmd_args.append('--create-region-category')

    if limit_regions:
        cmd_args.extend(['--limit-regions', str(limit_regions)])
    if offset_regions:
        cmd_args.extend(['--offset-regions', str(offset_regions)])
    if limit_categories:
        cmd_args.extend(['--limit-categories', str(limit_categories)])
    if offset_categories:
        cmd_args.extend(['--offset-categories', str(offset_categories)])

    if batch_size and int(batch_size) != 50:
        cmd_args.extend(['--batch-size', str(batch_size)])
    if no_progress:
        cmd_args.append('--no-progress')
    if dry_run:
        cmd_args.append('--dry-run')

    start = timezone.now()
    try:
        # call_command handles management command invocation in-process
        call_command('populate_performance_metrics', *cmd_args)
    except Exception:
        # Re-raise or fail the task depending on your retry policy; here we mark as failure.
        raise

    elapsed = timezone.now() - start
    return {
        'status': 'ok',
        'started_at': start.isoformat(),
        'elapsed_seconds': elapsed.total_seconds(),
    }


@shared_task
def update_status_bottlenecks(
    periods=None,
    create_global=False,
    limit_regions=0,
    limit_categories=0,
    batch_size=50,
    dry_run=False,
):
    """
    Wrapper task that calls the management command `populate_status_bottlenecks`.
    - If `periods` is None or empty, calls the command once WITHOUT --period (command will compute all periods).
    - If `periods` is a list, calls the command once per period (each run will have its own calculated_at).
    """
    # default to weekly if explicitly passed None as single value
    if periods is None or len(periods) == 0:
        # call once without --period to compute all supported periods
        cmd_args = []
        if create_global:
            cmd_args.append('--only-global')
        if limit_regions:
            cmd_args.extend(['--limit-regions', str(limit_regions)])
        if limit_categories:
            cmd_args.extend(['--limit-categories', str(limit_categories)])
        if batch_size and int(batch_size) != 10:  # default in command is 10
            cmd_args.extend(['--batch-size', str(batch_size)])
        if dry_run:
            cmd_args.append('--dry-run')

        start = timezone.now()
        try:
            call_command('populate_status_bottlenecks', *cmd_args)
        except Exception:
            raise
        elapsed = timezone.now() - start
        return {
            'status': 'ok',
            'started_at': start.isoformat(),
            'elapsed_seconds': elapsed.total_seconds(),
        }

    # If periods provided, call once per period so each run has its own calculated_at
    results = []
    for p in periods:
        cmd_args = ['--period', p]
        if create_global:
            cmd_args.append('--only-global')
        if limit_regions:
            cmd_args.extend(['--limit-regions', str(limit_regions)])
        if limit_categories:
            cmd_args.extend(['--limit-categories', str(limit_categories)])
        if batch_size and int(batch_size) != 10:
            cmd_args.extend(['--batch-size', str(batch_size)])
        if dry_run:
            cmd_args.append('--dry-run')

        start = timezone.now()
        try:
            call_command('populate_status_bottlenecks', *cmd_args)
        except Exception:
            # Re-raise para que Celery pueda manejar retries
            raise
        elapsed = timezone.now() - start
        results.append(
            {
                'period': p,
                'started_at': start.isoformat(),
                'elapsed_seconds': elapsed.total_seconds(),
            }
        )

    return {
        'status': 'ok',
        'runs': results,
    }


@shared_task
def update_region_performance_metrics(
    periods=None,
    regions=None,
    categories=None,
    limit_regions=0,
    dry_run=False,
    verbose=False,
):
    """
    Wrapper task that calls the management command `populate_region_performance_metrics`.

    Examples:
      # Full update for all regions and all periods
      update_region_performance_metrics.delay()

      # Update only 7d period
      update_region_performance_metrics.delay(periods=['7d'])

      # Sharded update for worker 1
      update_region_performance_metrics.delay(limit_regions=100)
    """
    from dashboard.constants import MONTHLY_CHOICE, QUARTERLY_CHOICE, WEEKLY_CHOICE

    periods = periods or [WEEKLY_CHOICE, MONTHLY_CHOICE, QUARTERLY_CHOICE]

    cmd_args = []
    for p in periods:
        cmd_args.extend(['--periods', p])

    if regions:
        for r in regions:
            cmd_args.extend(['--regions', str(r)])

    if categories:
        for c in categories:
            cmd_args.extend(['--categories', str(c)])

    if limit_regions:
        cmd_args.extend(['--limit-regions', str(limit_regions)])

    if verbose:
        cmd_args.append('--verbose')

    if dry_run:
        cmd_args.append('--dry-run')

    start = timezone.now()
    try:
        call_command('populate_region_performance_metrics', *cmd_args)
    except Exception:
        raise

    elapsed = timezone.now() - start
    return {
        'status': 'ok',
        'started_at': start.isoformat(),
        'elapsed_seconds': elapsed.total_seconds(),
    }


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    # Calls check_issues() every 5 minutes.
    sender.add_periodic_task(300, check_issues.s(), name="check issues every 5 minutes")

    # Calls escalate_issues() every 5 minutes.
    sender.add_periodic_task(300, escalate_issues.s(), name="escalate issues every 5 minutes")

    # Citizen notifications are sent immediately by the actions themselves (grm/notifications.py),
    # there is no notification queue task anymore.

    # Calls mark_issues_to_be_escalated() every day
    sender.add_periodic_task(86400, mark_issues_to_be_escalated.s(), name="mark issues to be escalated every day")

    # Calls reassign_issues_to_appeal() every hour.
    sender.add_periodic_task(3600, reassign_issues_to_appeal.s(), name="reassign issues to appeal every hour")

    # === Frequent small-window updates (7d) every 15 minutes, sharded ===
    # Now that we process ancestors, the regions set grows. Use smaller shards.
    # Example: 20 shards, each handles 50 regions (20 * 50 = 1000 regions covered)
    shards_7d = 20
    limit_per_shard = 50
    for i in range(shards_7d):
        sender.add_periodic_task(
            900,  # 15 minutes
            update_performance_metrics.s(
                periods=[WEEKLY_CHOICE],
                create_global=True,
                create_regions=True,
                create_categories=True,
                create_region_category=False,
                limit_regions=limit_per_shard,
                offset_regions=i * limit_per_shard,
                no_progress=True,
            ),
            name=f"update metrics 7d shard {i}",
        )

    # === Medium-window updates (30d) every hour, fewer shards but still safe ===
    shards_30d = 8
    limit_30 = 125  # approx 1000 / 8
    for i in range(shards_30d):
        sender.add_periodic_task(
            3600,  # every hour
            update_performance_metrics.s(
                periods=[MONTHLY_CHOICE],
                create_global=True,
                create_regions=True,
                create_categories=True,
                create_region_category=False,
                limit_regions=limit_30,
                offset_regions=i * limit_30,
                no_progress=True,
            ),
            name=f"update metrics 30d shard {i}",
        )

    # === Long-window updates (90d) daily ===
    # Daily recalculation can be heavier; run with fewer shards or single run.
    # If you expect >2000 regions+ancestors, consider 2 shards instead.
    sender.add_periodic_task(
        crontab(hour=2, minute=30),
        update_performance_metrics.s(
            periods=[QUARTERLY_CHOICE],
            create_global=True,
            create_regions=True,
            create_categories=True,
            create_region_category=False,
            no_progress=True,
        ),
        name="update metrics 90d daily",
    )

    # === Status Bottlenecks periodic tasks ===

    # Frequent small-window updates (7d) every 15 minutes, sharded by limit_regions
    shards_7d_sb = 20
    limit_per_shard_sb = 50
    for i in range(shards_7d_sb):
        sender.add_periodic_task(
            900,  # 15 minutes
            update_status_bottlenecks.s(
                periods=[WEEKLY_CHOICE],
                create_global=True,
                limit_regions=limit_per_shard_sb,
                batch_size=50,
                dry_run=False,
            ),
            name=f"update status bottlenecks 7d shard {i}",
        )

    # Medium-window updates (30d) every hour, fewer shards
    shards_30d_sb = 8
    limit_30_sb = 125
    for i in range(shards_30d_sb):
        sender.add_periodic_task(
            3600,  # every hour
            update_status_bottlenecks.s(
                periods=[MONTHLY_CHOICE],
                create_global=True,
                limit_regions=limit_30_sb,
                batch_size=50,
                dry_run=False,
            ),
            name=f"update status bottlenecks 30d shard {i}",
        )

    # Long-window updates (90d) daily
    sender.add_periodic_task(
        crontab(hour=3, minute=0),
        update_status_bottlenecks.s(
            periods=[QUARTERLY_CHOICE],
            create_global=True,
            batch_size=50,
            dry_run=False,
        ),
        name="update status bottlenecks 90d daily",
    )

    # === Region Performance Metrics Updates ===

    # Frequent updates (7d) every 30 minutes
    sender.add_periodic_task(
        1800,  # 30 minutes
        update_region_performance_metrics.s(
            periods=[WEEKLY_CHOICE],
        ),
        name="update region performance 7d every 30min",
    )

    # Medium-window updates (30d) every 2 hours
    sender.add_periodic_task(
        7200,  # 2 hours
        update_region_performance_metrics.s(
            periods=[MONTHLY_CHOICE],
        ),
        name="update region performance 30d every 2h",
    )

    # Long-window updates (90d) daily at 3:30 AM
    sender.add_periodic_task(
        crontab(hour=3, minute=30),
        update_region_performance_metrics.s(
            periods=[QUARTERLY_CHOICE],
        ),
        name="update region performance 90d daily",
    )
