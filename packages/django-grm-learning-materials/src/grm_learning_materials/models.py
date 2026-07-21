import os
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .conf import settings


def learning_material_upload_path(instance, filename):
    _, ext = os.path.splitext(filename)
    filename = f"{uuid.uuid4()}{ext}"
    prefix = settings.UPLOAD_PATH_PREFIX
    return f"{prefix}/{filename}"


class LearningMaterial(models.Model):
    class Category(models.TextChoices):
        GETTING_STARTED = 'getting_started', _('Getting Started')
        FILING_GRIEVANCE = 'filing_grievance', _('Filing a Grievance')
        YOUR_RIGHTS = 'your_rights', _('Your Rights')
        TRIAGE_PROCESSING = 'triage_processing', _('Triage & Processing')
        ESCALATION = 'escalation', _('Escalation')
        REPORTING_DUTIES = 'reporting_duties', _('Reporting Duties')
        FAQ = 'faq', _('FAQ')

    class ContentType(models.TextChoices):
        ARTICLE = 'article', _('Article')
        VIDEO = 'video', _('Video')
        PDF = 'pdf', _('PDF')

    class Status(models.TextChoices):
        PUBLISHED = 'published', _('Published')
        DRAFT = 'draft', _('Draft')
        ARCHIVED = 'archived', _('Archived')

    class TargetRole(models.TextChoices):
        CITIZEN = 'citizen', _('Citizen')
        FACILITATOR = 'facilitator', _('Facilitator')
        VILLAGE_SECRETARY = 'village_secretary', _('Village Secretary')

    title_fr = models.CharField(max_length=255, verbose_name=_('Title (French)'))
    title_en = models.CharField(max_length=255, blank=True, default='', verbose_name=_('Title (English)'))
    summary_fr = models.TextField(blank=True, default='', verbose_name=_('Summary (French)'))
    summary_en = models.TextField(blank=True, default='', verbose_name=_('Summary (English)'))
    body_fr = models.TextField(blank=True, default='', verbose_name=_('Body (French)'))
    body_en = models.TextField(blank=True, default='', verbose_name=_('Body (English)'))

    category = models.CharField(max_length=50, choices=Category.choices, verbose_name=_('Category'))
    content_type = models.CharField(
        max_length=20, default=ContentType.ARTICLE, choices=ContentType.choices, verbose_name=_('Type')
    )
    target_roles = models.JSONField(default=list, blank=True, verbose_name=_('Target Roles'))
    languages = models.JSONField(default=list, blank=True, verbose_name=_('Languages'))

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name=_('Status'))
    read_time = models.CharField(max_length=20, blank=True, default='', verbose_name=_('Read Time (mins)'))
    file = models.FileField(
        upload_to=learning_material_upload_path,
        blank=True,
        null=True,
        verbose_name=_('File'),
        help_text=_('Upload a PDF, JPG, or PNG file'),
    )

    created_date = models.DateTimeField(auto_now_add=True, verbose_name=_('Created Date'))
    updated_date = models.DateTimeField(auto_now=True, verbose_name=_('Updated Date'))

    class Meta:
        verbose_name = _('Learning Material')
        verbose_name_plural = _('Learning Materials')
        ordering = ['-updated_date']
        db_table = "dashboard_learningmaterial"

    def __str__(self):
        return self.title_fr or self.title_en or str(self.pk)

    @property
    def filename(self):
        return os.path.basename(self.file.name) if self.file else ''
