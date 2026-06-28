import grm_learning_materials.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    state_operations = [
        migrations.CreateModel(
            name="LearningMaterial",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title_fr", models.CharField(max_length=255, verbose_name="Title (French)")),
                ("title_en", models.CharField(blank=True, default="", max_length=255, verbose_name="Title (English)")),
                ("summary_fr", models.TextField(blank=True, default="", verbose_name="Summary (French)")),
                ("summary_en", models.TextField(blank=True, default="", verbose_name="Summary (English)")),
                ("body_fr", models.TextField(blank=True, default="", verbose_name="Body (French)")),
                ("body_en", models.TextField(blank=True, default="", verbose_name="Body (English)")),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("getting_started", "Getting Started"),
                            ("filing_grievance", "Filing a Grievance"),
                            ("your_rights", "Your Rights"),
                            ("triage_processing", "Triage & Processing"),
                            ("escalation", "Escalation"),
                            ("reporting_duties", "Reporting Duties"),
                            ("faq", "FAQ"),
                        ],
                        max_length=50,
                        verbose_name="Category",
                    ),
                ),
                (
                    "content_type",
                    models.CharField(
                        choices=[("article", "Article"), ("video", "Video"), ("pdf", "PDF")],
                        default="article",
                        max_length=20,
                        verbose_name="Type",
                    ),
                ),
                ("target_roles", models.JSONField(blank=True, default=list, verbose_name="Target Roles")),
                ("languages", models.JSONField(blank=True, default=list, verbose_name="Languages")),
                (
                    "status",
                    models.CharField(
                        choices=[("published", "Published"), ("draft", "Draft"), ("archived", "Archived")],
                        default="draft",
                        max_length=20,
                        verbose_name="Status",
                    ),
                ),
                ("read_time", models.CharField(blank=True, default="", max_length=20, verbose_name="Read Time (mins)")),
                (
                    "file",
                    models.FileField(
                        blank=True,
                        help_text="Upload a PDF, JPG, or PNG file",
                        null=True,
                        upload_to=grm_learning_materials.models.learning_material_upload_path,
                        verbose_name="File",
                    ),
                ),
                ("created_date", models.DateTimeField(auto_now_add=True, verbose_name="Created Date")),
                ("updated_date", models.DateTimeField(auto_now=True, verbose_name="Updated Date")),
            ],
            options={
                "verbose_name": "Learning Material",
                "verbose_name_plural": "Learning Materials",
                "db_table": "dashboard_learningmaterial",
                "ordering": ["-updated_date"],
            },
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=state_operations,
            database_operations=[],
        ),
    ]
