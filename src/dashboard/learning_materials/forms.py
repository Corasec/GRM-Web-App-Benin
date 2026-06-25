from django import forms
from django.utils.translation import gettext_lazy as _

from dashboard.models import LearningMaterial


class LearningMaterialForm(forms.ModelForm):
    target_roles = forms.MultipleChoiceField(
        choices=LearningMaterial.TargetRole.choices,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'role-checkbox'}),
        required=False,
        label=_('Target Roles'),
    )
    languages = forms.MultipleChoiceField(
        choices=[('fr', _('French')), ('en', _('English'))],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'language-checkbox'}),
        required=False,
        label=_('Languages'),
    )
    clear_file = forms.BooleanField(
        required=False,
        label=_('Remove current file'),
    )

    class Meta:
        model = LearningMaterial
        fields = [
            'title_fr',
            'title_en',
            'summary_fr',
            'summary_en',
            'body_fr',
            'body_en',
            'category',
            'content_type',
            'target_roles',
            'languages',
            'status',
            'read_time',
            'file',
        ]
        widgets = {
            'body_fr': forms.Textarea(attrs={'class': 'rich-text-editor', 'rows': 12}),
            'body_en': forms.Textarea(attrs={'class': 'rich-text-editor', 'rows': 12}),
            'summary_fr': forms.Textarea(attrs={'rows': 3}),
            'summary_en': forms.Textarea(attrs={'rows': 3}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'content_type': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'read_time': forms.TextInput(attrs={'placeholder': _('e.g. 4 min')}),
            'file': forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in self.fields:
            field = self.fields[field_name]
            if not isinstance(field.widget, (forms.CheckboxSelectMultiple,)):
                field.widget.attrs.setdefault('class', 'form-control')
                if isinstance(field.widget, forms.Textarea):
                    field.widget.attrs['rows'] = field.widget.attrs.get('rows', 4)

        if self.instance.pk:
            self.fields['target_roles'].initial = self.instance.target_roles
            self.fields['languages'].initial = self.instance.languages

        self.fields['content_type'].widget.choices = LearningMaterial.ContentType.choices

        if not self.instance.pk or not self.instance.file:
            self.fields.pop('clear_file')

    def clean_target_roles(self):
        return list(self.cleaned_data.get('target_roles', []))

    def clean_languages(self):
        return list(self.cleaned_data.get('languages', []))

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('clear_file') and instance.file:
            instance.file.delete(save=False)
            instance.file = None
        if commit:
            instance.save()
        return instance
