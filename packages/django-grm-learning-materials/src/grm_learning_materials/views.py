from django.contrib import messages
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic

from .conf import settings
from .forms import LearningMaterialForm
from .mixins import AJAXPermissionMixin, DataTableMixin, PageMixin, PermissionMixin
from .models import LearningMaterial


class LearningMaterialListView(PageMixin, PermissionMixin, generic.TemplateView):
    template_name = "grm_learning_materials/list.html"
    title = ""
    active_level1 = "learning_materials"
    breadcrumb = []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        qs = LearningMaterial.objects.all()

        total = qs.count()
        published = qs.filter(status=LearningMaterial.Status.PUBLISHED).count()
        drafts = qs.filter(status=LearningMaterial.Status.DRAFT).count()
        archived = qs.filter(status=LearningMaterial.Status.ARCHIVED).count()

        context['kpi_total'] = total
        context['kpi_published'] = published
        context['kpi_drafts'] = drafts
        context['kpi_archived'] = archived

        context['categories'] = LearningMaterial.Category.choices
        context['content_types'] = LearningMaterial.ContentType.choices
        context['status_choices'] = LearningMaterial.Status.choices
        context['role_choices'] = LearningMaterial.TargetRole.choices

        ns = settings.URL_NAMESPACE
        context['lm_url_create'] = reverse_lazy(f"{ns}:create")
        context['lm_url_data'] = reverse_lazy(f"{ns}:data")

        return context


class LearningMaterialListDataView(AJAXPermissionMixin, DataTableMixin, generic.View):
    def get_column_key_from_index(self, idx):
        map = {0: 'title', 1: 'category', 2: 'content_type', 3: 'roles', 4: 'languages', 5: 'status', 6: 'updated'}
        return map.get(idx)

    def get_sort_map(self):
        return {
            'title': 'title_fr',
            'category': 'category',
            'content_type': 'content_type',
            'status': 'status',
            'updated': 'updated_date',
        }

    def get_base_queryset(self, request):
        return LearningMaterial.objects.all()

    def apply_filters(self, qs, params):
        search = params['raw'].get('search[value]', '')
        if search:
            qs = qs.filter(
                Q(title_fr__icontains=search)
                | Q(title_en__icontains=search)
                | Q(summary_fr__icontains=search)
                | Q(summary_en__icontains=search)
            )

        role = params['raw'].get('role', '')
        if role:
            qs = qs.filter(target_roles__contains=[role])

        status = params['raw'].get('status', '')
        if status:
            qs = qs.filter(status=status)

        category = params['raw'].get('category', '')
        if category:
            qs = qs.filter(category=category)

        content_type = params['raw'].get('content_type', '')
        if content_type:
            qs = qs.filter(content_type=content_type)

        return qs

    def serialize_row(self, obj):
        role_labels = {
            'citizen': _('Citizen'),
            'facilitator': _('Facilitator'),
            'village_secretary': _('Village Secretary'),
        }
        lang_labels = {'fr': 'FR', 'en': 'EN'}

        role_dots = ''.join(
            f'<span class="lm-role-chip">{role_labels.get(r, r)}</span>' for r in (obj.target_roles or [])
        )
        lang_tags = ''
        for language, prefix in [('fr', 'fr'), ('en', 'en')]:
            has_content = bool(
                getattr(obj, f'title_{prefix}', '')
                or getattr(obj, f'summary_{prefix}', '')
                or getattr(obj, f'body_{prefix}', '')
            )
            if has_content:
                lang_tags += f'<span class="lm-lang-chip">{lang_labels.get(language, language)}</span>'

        status_icon = {
            'published': 'fa-check-circle',
            'draft': 'fa-pen',
            'archived': 'fa-archive',
        }.get(obj.status, 'fa-circle')

        ns = settings.URL_NAMESPACE

        return {
            'id': obj.pk,
            'title': obj.title_fr or obj.title_en,
            'title_fr': obj.title_fr,
            'title_en': obj.title_en,
            'summary_fr': obj.summary_fr,
            'summary_en': obj.summary_en,
            'category': dict(LearningMaterial.Category.choices).get(obj.category, obj.category),
            'content_type': dict(LearningMaterial.ContentType.choices).get(obj.content_type, obj.content_type),
            'content_type_key': obj.content_type,
            'roles': role_dots,
            'languages': lang_tags,
            'status': f'<span class="lm-badge status-{obj.status}"><i class="fas {status_icon}"></i>{dict(LearningMaterial.Status.choices).get(obj.status, obj.status)}</span>',
            'status_key': obj.status,
            'updated': obj.updated_date.strftime('%Y-%m-%d') if obj.updated_date else '',
            'edit_url': reverse_lazy(f'{ns}:update', kwargs={'pk': obj.pk}),
        }

    def get(self, request, *args, **kwargs):
        return self.handle(request, *args, **kwargs)


class LearningMaterialCreateView(PageMixin, PermissionMixin, generic.CreateView):
    template_name = "grm_learning_materials/form.html"
    form_class = LearningMaterialForm
    model = LearningMaterial
    title = _("New Learning Material")
    active_level1 = "learning_materials"
    breadcrumb = []

    def get_success_url(self):
        ns = settings.URL_NAMESPACE
        return reverse_lazy(f"{ns}:detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            _('Learning material "%(title)s" created successfully.')
            % {'title': self.object.title_fr or self.object.title_en},
            extra_tags="success",
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_create'] = True
        ns = settings.URL_NAMESPACE
        context['lm_url_home'] = reverse_lazy(f"{ns}:home")
        return context


class LearningMaterialUpdateView(PageMixin, PermissionMixin, generic.UpdateView):
    template_name = "grm_learning_materials/form.html"
    form_class = LearningMaterialForm
    model = LearningMaterial
    title = ""
    active_level1 = "learning_materials"
    breadcrumb = []

    def get_success_url(self):
        ns = settings.URL_NAMESPACE
        return reverse_lazy(f"{ns}:detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            _('Learning material "%(title)s" updated successfully.')
            % {'title': self.object.title_fr or self.object.title_en},
            extra_tags="success",
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ns = settings.URL_NAMESPACE
        context['lm_url_home'] = reverse_lazy(f"{ns}:home")
        context['lm_url_update'] = reverse_lazy(f"{ns}:update", kwargs={"pk": self.object.pk})
        return context


class LearningMaterialDetailView(PermissionMixin, generic.RedirectView):
    def get_redirect_url(self, *args, **kwargs):
        ns = settings.URL_NAMESPACE
        return reverse_lazy(f'{ns}:update', kwargs={'pk': kwargs['pk']})


class LearningMaterialDeleteView(PageMixin, PermissionMixin, generic.DeleteView):
    template_name = "grm_learning_materials/confirm_delete.html"
    model = LearningMaterial
    context_object_name = "material"
    title = _("Delete Learning Material")
    active_level1 = "learning_materials"
    breadcrumb = []

    def get_success_url(self):
        ns = settings.URL_NAMESPACE
        return reverse_lazy(f"{ns}:home")

    def get_title(self):
        obj = self.object
        return _('Delete "%(title)s"') % {'title': obj.title_fr or obj.title_en or str(obj.pk)}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = self.get_title()
        ns = settings.URL_NAMESPACE
        context['lm_url_home'] = reverse_lazy(f"{ns}:home")
        context['lm_url_detail'] = reverse_lazy(f"{ns}:detail", kwargs={"pk": self.object.pk})
        return context

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        title = obj.title_fr or obj.title_en or str(obj.pk)
        response = super().delete(request, *args, **kwargs)
        messages.success(
            request,
            _('Learning material "%(title)s" deleted successfully.') % {'title': title},
            extra_tags="success",
        )
        return response
