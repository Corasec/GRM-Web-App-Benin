from django import forms
from django.utils.translation import gettext_lazy as _

from grm.constants import ANONYMOUS_CHOICE, FEWER_ISSUES_CHOICE, LOW_CHOICE
from issues.models import (
    AdministrativeRegion,
    IssueCategory,
    IssueDepartmentAdministrativeLevel,
    IssueSubType,
    IssueType,
)
from wizard.importer import _abbreviation


class CommitteeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.department.name} ({obj.administrative_level.name})"


def appeal_committee():
    """Appeal committee given to new categories (appeals are not used yet): the top-level committee."""
    used = IssueCategory.objects.exclude(assigned_appeal_department=None).values_list(
        "assigned_appeal_department", flat=True
    )
    if used:
        return IssueDepartmentAdministrativeLevel.objects.filter(pk=used[0]).first()
    root = AdministrativeRegion.objects.filter(parent=None).first()
    if root:
        return IssueDepartmentAdministrativeLevel.objects.filter(administrative_level=root.administrative_level).first()
    return None


class IssueTypeForm(forms.ModelForm):
    class Meta:
        model = IssueType
        fields = ["name"]
        labels = {"name": _("Name")}
        help_texts = {"name": _('Answer to "What are you reporting?", e.g. Complaint, Denunciation.')}


class IssueSubTypeForm(forms.ModelForm):
    class Meta:
        model = IssueSubType
        fields = ["parent", "name"]
        labels = {"parent": _("Type"), "name": _("Name")}
        help_texts = {"name": _('Answer to "What type?".')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Moving a subtype would make the type of its existing issues inconsistent
            self.fields["parent"].disabled = True


class IssueCategoryForm(forms.ModelForm):
    sensitive = forms.BooleanField(
        label=_("Sensitive"),
        required=False,
        help_text=_("Sensitive issues are anonymised (e.g. gender-based violence, corruption)."),
    )

    class Meta:
        model = IssueCategory
        fields = ["parent", "name", "assigned_department", "sensitive", "processing_days", "abbreviation"]
        labels = {
            "parent": _("Subtype"),
            "name": _("Name"),
            "assigned_department": _("Committee that receives it"),
            "processing_days": _("Specific processing time (working days)"),
            "abbreviation": _("Abbreviation"),
        }
        help_texts = {
            "name": _('Answer to "What is it about?". Must be unique.'),
            "assigned_department": _(
                "The committee where the issue happened at this level (e.g. the village committee)."
            ),
            "processing_days": _("Leave empty to use the committee processing time."),
            "abbreviation": _("Leave empty to generate it."),
        }
        field_classes = {"assigned_department": CommitteeChoiceField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].required = True
        self.fields["parent"].queryset = IssueSubType.objects.select_related("parent").order_by("parent__name", "name")
        self.fields["parent"].label_from_instance = lambda obj: f"{obj.parent.name} › {obj.name}"
        self.fields["assigned_department"].required = True
        self.fields["assigned_department"].queryset = IssueDepartmentAdministrativeLevel.objects.select_related(
            "department", "administrative_level"
        )
        self.fields["assigned_department"].empty_label = None
        self.initial.setdefault("sensitive", self.instance.confidentiality_level == ANONYMOUS_CHOICE)
        if self.instance.pk:
            # Moving a category would make the type / subtype of its existing issues inconsistent
            self.fields["parent"].disabled = True

    def save(self, commit=True):
        category = super().save(commit=False)
        category.confidentiality_level = ANONYMOUS_CHOICE if self.cleaned_data.get("sensitive") else LOW_CHOICE
        if not category.pk:
            category.assigned_escalation_department = category.assigned_department
            category.assigned_appeal_department = appeal_committee()
            category.redirection_protocol = FEWER_ISSUES_CHOICE
        if not category.abbreviation:
            category.abbreviation = _abbreviation(IssueCategory.objects.count() + 1, category.name)
        if commit:
            category.save()
        return category
