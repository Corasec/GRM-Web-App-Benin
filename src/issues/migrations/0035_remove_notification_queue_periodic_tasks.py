from django.db import migrations

# The send_sms_message / send_mail_message Celery tasks were removed: citizen notifications are
# sent immediately by the actions (grm/notifications.py). Delete their schedules so celery beat
# does not keep sending tasks that no longer exist.
REMOVED_TASKS = ["grm.tasks.send_sms_message", "grm.tasks.send_mail_message"]
REMOVED_NAMES = ["send sms every 5 minutes", "send mail every 5 minutes"]


def remove_periodic_tasks(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(task__in=REMOVED_TASKS).delete()
    PeriodicTask.objects.filter(name__in=REMOVED_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0034_issue_appeal_reason"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [migrations.RunPython(remove_periodic_tasks, migrations.RunPython.noop)]
