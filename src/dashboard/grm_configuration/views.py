"""
"GRM configuration" page for the GRM owner (and superusers), once the setup wizard is finished:
read-only overview of the wizard configuration and maintenance of the categorisation
(types, subtypes, categories). New items reach the mobile app at its next synchronisation.

Nothing that is in use can be deleted: deleting a type, subtype or category would delete
its issues (cascade). Items in use can only be renamed / adjusted.
"""

from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic

from dashboard.grm_configuration.forms import IssueCategoryForm, IssueSubTypeForm, IssueTypeForm
from dashboard.mixins import PageMixin
from issues.models import IssueCategory, IssueSubType, IssueType
from wizard import constants as wizard_cons
from wizard.views import SummaryView

HOME_URL = reverse_lazy("dashboard:grm_configuration:home")


class GrmOwnerPermissionMixin(AccessMixin):
    """Only the GRM owner and superusers manage the GRM configuration."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.grm_owner or request.user.is_superuser):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def blocking_reason(obj):
    """Why ``obj`` cannot be deleted, or None."""
    issues = obj.issues.count()
    if issues:
        return _("used by %(count)s issue(s): it can only be renamed") % {"count": issues}
    if isinstance(obj, IssueType) and obj.children.exists():
        return _("delete its subtypes first")
    if isinstance(obj, IssueSubType) and obj.categories.exists():
        return _("delete its categories first")
    return None


class ConfigurationHomeView(PageMixin, GrmOwnerPermissionMixin, generic.TemplateView):
    template_name = "grm_configuration/home.html"
    title = _("GRM configuration")
    active_level1 = "grm_configuration"
    breadcrumb = [{"url": "", "title": title}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The categorisation is shown (and edited) as a tree below
        categorisation = {str(wizard_cons.ISSUE_TYPES_DISPLAY), str(wizard_cons.CATEGORIES_DISPLAY)}
        context["summary"] = [s for s in SummaryView()._build_summary() if str(s.get("title")) not in categorisation]
        categories = IssueCategory.objects.select_related(
            "assigned_department__department", "assigned_department__administrative_level"
        ).annotate(issue_count=Count("issues", distinct=True))
        subtypes = (
            IssueSubType.objects.annotate(issue_count=Count("issues", distinct=True))
            .prefetch_related(Prefetch("categories", queryset=categories.order_by("name")))
            .order_by("name")
        )
        context["types"] = (
            IssueType.objects.annotate(issue_count=Count("issues", distinct=True))
            .prefetch_related(Prefetch("children", queryset=subtypes))
            .order_by("name")
        )
        context["has_subtypes"] = IssueSubType.objects.exists()
        return context


class ConfigurationFormMixin(PageMixin, GrmOwnerPermissionMixin):
    template_name = "grm_configuration/form.html"
    active_level1 = "grm_configuration"
    success_url = HOME_URL
    success_message = _("Saved. The mobile app gets the change at its next synchronisation.")

    @property
    def breadcrumb(self):
        return [{"url": HOME_URL, "title": _("GRM configuration")}, {"url": "", "title": self.title}]

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.add_message(self.request, messages.SUCCESS, self.success_message, extra_tags="success")
        return response


class InitialParentMixin:
    """Preselect the parent given in the query string (?parent=<id>)."""

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("parent", "").isdigit():
            initial["parent"] = int(self.request.GET["parent"])
        return initial


class IssueTypeCreateView(ConfigurationFormMixin, generic.CreateView):
    model = IssueType
    form_class = IssueTypeForm
    title = _("New type")


class IssueTypeUpdateView(ConfigurationFormMixin, generic.UpdateView):
    model = IssueType
    form_class = IssueTypeForm
    title = _("Edit type")


class IssueSubTypeCreateView(ConfigurationFormMixin, InitialParentMixin, generic.CreateView):
    model = IssueSubType
    form_class = IssueSubTypeForm
    title = _("New subtype")


class IssueSubTypeUpdateView(ConfigurationFormMixin, generic.UpdateView):
    model = IssueSubType
    form_class = IssueSubTypeForm
    title = _("Edit subtype")


class IssueCategoryCreateView(ConfigurationFormMixin, InitialParentMixin, generic.CreateView):
    model = IssueCategory
    form_class = IssueCategoryForm
    title = _("New category")


class IssueCategoryUpdateView(ConfigurationFormMixin, generic.UpdateView):
    model = IssueCategory
    form_class = IssueCategoryForm
    title = _("Edit category")


class ConfigurationDeleteView(PageMixin, GrmOwnerPermissionMixin, generic.TemplateView):
    """Delete an unused type, subtype or category (POST only, after a confirmation page)."""

    template_name = "grm_configuration/confirm_delete.html"
    active_level1 = "grm_configuration"
    models = {"type": IssueType, "subtype": IssueSubType, "category": IssueCategory}
    title = _("Delete")

    @property
    def breadcrumb(self):
        return [{"url": HOME_URL, "title": _("GRM configuration")}, {"url": "", "title": self.title}]

    def get_object(self):
        model = self.models.get(self.kwargs["kind"])
        if model is None:
            raise PermissionDenied
        return get_object_or_404(model, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["obj"] = self.get_object()
        context["blocking_reason"] = blocking_reason(context["obj"])
        return context

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        reason = blocking_reason(obj)
        if reason:
            messages.add_message(
                request,
                messages.ERROR,
                _("« %(name)s » cannot be deleted: %(reason)s.") % {"name": obj, "reason": reason},
                extra_tags="danger",
            )
        else:
            name = str(obj)
            obj.delete()
            messages.add_message(
                request, messages.SUCCESS, _("« %(name)s » was deleted.") % {"name": name}, extra_tags="success"
            )
        return HttpResponseRedirect(reverse("dashboard:grm_configuration:home"))
