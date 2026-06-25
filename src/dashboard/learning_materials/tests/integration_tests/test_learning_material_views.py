import pytest
from django.test import TestCase
from django.urls import reverse

from authentication.factories import UserFactory
from dashboard.models import LearningMaterial
from issues.factories import AdministrativeRegionFactory
from wizard.constants import COMPLETED_CHOICE
from wizard.models import WizardSection

AJAX_HEADER = "HTTP_X_REQUESTED_WITH"


@pytest.mark.django_db
class LmTestCase(TestCase):
    def setUp(self):
        super().setUp()
        WizardSection.objects.update(status=COMPLETED_CHOICE)
        self.root_region = AdministrativeRegionFactory()

    @staticmethod
    def get_context(response):
        ctx = {}
        if hasattr(response, "context") and response.context is not None:
            from django.template import Context

            def flatten(obj):
                if isinstance(obj, dict):
                    yield obj
                elif isinstance(obj, (list, tuple)):
                    for i in obj:
                        yield from flatten(i)
                elif isinstance(obj, Context):
                    try:
                        yield obj.flatten()
                    except Exception:
                        yield dict(obj)
                else:
                    try:
                        yield dict(obj)
                    except Exception:
                        pass

            for mapping in flatten(response.context):
                if isinstance(mapping, dict):
                    ctx.update(mapping)
        if hasattr(response, "context_data") and response.context_data:
            ctx.update(response.context_data)
        return ctx

    def get(self, uri, data=None, user=None, ajax=None, **kwargs):
        if user:
            self.client.force_login(user=user)
        if ajax:
            kwargs[AJAX_HEADER] = "XMLHttpRequest"
        return self.client.get(uri, data, **kwargs)

    def post(self, uri, data, user=None, ajax=None, follow=False, **kwargs):
        if user:
            self.client.force_login(user=user)
        if ajax:
            kwargs[AJAX_HEADER] = "XMLHttpRequest"
        return self.client.post(uri, data, follow=follow, **kwargs)


class LearningMaterialModelTest(LmTestCase):
    def test_create_minimal(self):
        obj = LearningMaterial.objects.create(
            title_fr="Titre",
            category="getting_started",
            content_type="article",
        )
        assert obj.title_fr == "Titre"
        assert obj.title_en == ""
        assert obj.status == LearningMaterial.Status.DRAFT
        assert obj.target_roles == []
        assert obj.languages == []
        assert str(obj) == "Titre"

    def test_str_fallback_to_english(self):
        obj = LearningMaterial.objects.create(
            title_en="Title",
            category="faq",
            content_type="video",
        )
        assert str(obj) == "Title"

    def test_str_fallback_to_pk(self):
        obj = LearningMaterial.objects.create(
            category="faq",
            content_type="article",
        )
        assert str(obj) == str(obj.pk)

    def test_filename_property(self):
        obj = LearningMaterial.objects.create(
            title_fr="Test",
            category="faq",
            content_type="article",
        )
        assert obj.filename == ""


class LearningMaterialListViewTest(LmTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("dashboard:learning_materials:home")
        self.grm_manager = UserFactory(grm_manager=True)
        LearningMaterial.objects.create(
            title_fr="Pub", category="faq", content_type="article", status=LearningMaterial.Status.PUBLISHED
        )
        LearningMaterial.objects.create(
            title_fr="Drf", category="faq", content_type="article", status=LearningMaterial.Status.DRAFT
        )
        LearningMaterial.objects.create(
            title_fr="Arc", category="faq", content_type="article", status=LearningMaterial.Status.ARCHIVED
        )

    def test_requires_grm_manager(self):
        resp = self.get(self.url, user=UserFactory())
        assert resp.status_code == 403

    def test_returns_200_for_grm_manager(self):
        resp = self.get(self.url, user=self.grm_manager)
        assert resp.status_code == 200

    def test_context_kpis(self):
        resp = self.get(self.url, user=self.grm_manager)
        ctx = self.get_context(resp)
        assert ctx["kpi_total"] == 3
        assert ctx["kpi_published"] == 1
        assert ctx["kpi_drafts"] == 1
        assert ctx["kpi_archived"] == 1

    def test_context_choices(self):
        resp = self.get(self.url, user=self.grm_manager)
        ctx = self.get_context(resp)
        assert "categories" in ctx
        assert "content_types" in ctx
        assert "status_choices" in ctx
        assert "role_choices" in ctx

    def test_uses_correct_template(self):
        resp = self.get(self.url, user=self.grm_manager)
        assert "learning_materials/list.html" in [t.name for t in resp.templates]


class LearningMaterialListDataViewTest(LmTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("dashboard:learning_materials:data")
        self.grm_manager = UserFactory(grm_manager=True)

    def test_requires_ajax(self):
        resp = self.get(self.url, user=self.grm_manager)
        assert resp.status_code == 404

    def test_requires_grm_manager(self):
        resp = self.get(self.url, user=UserFactory(), ajax=True)
        assert resp.status_code == 403

    def test_empty_response(self):
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["data"] == []
        assert payload["recordsTotal"] == 0
        assert payload["recordsFiltered"] == 0

    def test_serialize_row_contains_expected_keys(self):
        obj = LearningMaterial.objects.create(
            title_fr="Titre FR",
            title_en="Title EN",
            summary_fr="Résumé",
            summary_en="Summary",
            body_fr="Corps",
            status=LearningMaterial.Status.PUBLISHED,
            category="faq",
            content_type="article",
            target_roles=["citizen", "facilitator"],
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        payload = resp.json()
        row = payload["data"][0]
        assert row["id"] == obj.pk
        assert row["title"] == "Titre FR"
        assert row["title_fr"] == "Titre FR"
        assert row["title_en"] == "Title EN"
        assert row["edit_url"] == reverse("dashboard:learning_materials:update", kwargs={"pk": obj.pk})

    def test_role_chips_rendered(self):
        LearningMaterial.objects.create(
            title_fr="Test",
            category="faq",
            content_type="article",
            target_roles=["citizen", "facilitator", "village_secretary"],
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        row = resp.json()["data"][0]
        assert 'lm-role-chip' in row["roles"]
        assert "Citizen" in row["roles"]
        assert "Facilitator" in row["roles"]
        assert "Village Secretary" in row["roles"]

    def test_role_chips_empty_when_no_roles(self):
        LearningMaterial.objects.create(title_fr="Test", category="faq", content_type="article")
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        assert resp.json()["data"][0]["roles"] == ""

    def test_language_chips_fr_only(self):
        LearningMaterial.objects.create(
            title_fr="Titre",
            summary_en="",
            body_en="",
            category="faq",
            content_type="article",
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        chips = resp.json()["data"][0]["languages"]
        assert 'lm-lang-chip' in chips
        assert "FR" in chips
        assert "EN" not in chips

    def test_language_chips_en_only(self):
        LearningMaterial.objects.create(
            title_en="Title",
            title_fr="",
            category="faq",
            content_type="article",
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        chips = resp.json()["data"][0]["languages"]
        assert "EN" in chips
        assert "FR" not in chips

    def test_language_chips_both(self):
        LearningMaterial.objects.create(
            title_fr="Titre",
            title_en="Title",
            category="faq",
            content_type="article",
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        chips = resp.json()["data"][0]["languages"]
        assert "FR" in chips
        assert "EN" in chips

    def test_status_icon_published(self):
        LearningMaterial.objects.create(
            title_fr="Pub",
            category="faq",
            content_type="article",
            status=LearningMaterial.Status.PUBLISHED,
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        status_html = resp.json()["data"][0]["status"]
        assert "status-published" in status_html
        assert "fa-check-circle" in status_html

    def test_status_icon_draft(self):
        LearningMaterial.objects.create(
            title_fr="Drf",
            category="faq",
            content_type="article",
            status=LearningMaterial.Status.DRAFT,
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        status_html = resp.json()["data"][0]["status"]
        assert "status-draft" in status_html
        assert "fa-pen" in status_html

    def test_status_icon_archived(self):
        LearningMaterial.objects.create(
            title_fr="Arc",
            category="faq",
            content_type="article",
            status=LearningMaterial.Status.ARCHIVED,
        )
        resp = self.get(self.url, user=self.grm_manager, ajax=True)
        status_html = resp.json()["data"][0]["status"]
        assert "status-archived" in status_html
        assert "fa-archive" in status_html

    def test_filter_by_role(self):
        LearningMaterial.objects.create(title_fr="A", category="faq", content_type="article", target_roles=["citizen"])
        LearningMaterial.objects.create(
            title_fr="B", category="faq", content_type="article", target_roles=["facilitator"]
        )
        resp = self.get(self.url, {"role": "citizen"}, user=self.grm_manager, ajax=True)
        assert resp.json()["recordsTotal"] == 1

    def test_filter_by_status(self):
        LearningMaterial.objects.create(title_fr="A", category="faq", content_type="article", status="published")
        LearningMaterial.objects.create(title_fr="B", category="faq", content_type="article", status="draft")
        resp = self.get(self.url, {"status": "published"}, user=self.grm_manager, ajax=True)
        assert resp.json()["recordsTotal"] == 1

    def test_filter_by_category(self):
        LearningMaterial.objects.create(title_fr="A", category="faq", content_type="article")
        LearningMaterial.objects.create(title_fr="B", category="escalation", content_type="article")
        resp = self.get(self.url, {"category": "faq"}, user=self.grm_manager, ajax=True)
        assert resp.json()["recordsTotal"] == 1

    def test_filter_by_content_type(self):
        LearningMaterial.objects.create(title_fr="A", category="faq", content_type="article")
        LearningMaterial.objects.create(title_fr="B", category="faq", content_type="video")
        resp = self.get(self.url, {"content_type": "video"}, user=self.grm_manager, ajax=True)
        assert resp.json()["recordsTotal"] == 1

    def test_search_by_title(self):
        LearningMaterial.objects.create(title_fr="Alpha", category="faq", content_type="article")
        LearningMaterial.objects.create(title_fr="Beta", category="faq", content_type="article")
        resp = self.get(self.url, {"search[value]": "Alpha"}, user=self.grm_manager, ajax=True)
        assert resp.json()["recordsTotal"] == 1

    def test_sort_by_updated(self):
        LearningMaterial.objects.create(title_fr="Older", category="faq", content_type="article")
        resp = self.get(self.url, {"order[0][column]": "6", "order[0][dir]": "desc"}, user=self.grm_manager, ajax=True)
        assert resp.status_code == 200


class LearningMaterialCreateViewTest(LmTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("dashboard:learning_materials:create")
        self.grm_manager = UserFactory(grm_manager=True)

    def test_requires_grm_manager(self):
        resp = self.get(self.url, user=UserFactory())
        assert resp.status_code == 403

    def test_get_returns_200(self):
        resp = self.get(self.url, user=self.grm_manager)
        assert resp.status_code == 200
        assert "learning_materials/form.html" in [t.name for t in resp.templates]

    def test_context_is_create(self):
        resp = self.get(self.url, user=self.grm_manager)
        ctx = self.get_context(resp)
        assert ctx.get("is_create") is True

    def test_post_creates_material(self):
        data = {
            "title_fr": "Nouveau",
            "category": "faq",
            "content_type": "article",
            "status": "draft",
        }
        resp = self.post(self.url, data, user=self.grm_manager)
        assert resp.status_code == 302
        obj = LearningMaterial.objects.get(title_fr="Nouveau")
        assert obj.status == LearningMaterial.Status.DRAFT
        assert obj.category == "faq"
        assert obj.content_type == "article"

    def test_post_with_roles(self):
        data = {
            "title_fr": "Avec rôles",
            "category": "faq",
            "content_type": "article",
            "status": "draft",
            "target_roles": ["citizen", "facilitator"],
        }
        self.post(self.url, data, user=self.grm_manager)
        obj = LearningMaterial.objects.get(title_fr="Avec rôles")
        assert obj.target_roles == ["citizen", "facilitator"]

    def test_post_requires_title_fr(self):
        data = {
            "category": "faq",
            "content_type": "article",
        }
        resp = self.post(self.url, data, user=self.grm_manager)
        assert resp.status_code == 200
        assert "title_fr" in resp.context_data["form"].errors

    def test_post_redirects_on_success(self):
        data = {"title_fr": "Test", "category": "faq", "content_type": "article", "status": "draft"}
        resp = self.post(self.url, data, user=self.grm_manager)
        obj = LearningMaterial.objects.get(title_fr="Test")
        expected = reverse("dashboard:learning_materials:detail", kwargs={"pk": obj.pk})
        assert resp.url == expected

    def test_success_message(self):
        data = {"title_fr": "Message Test", "category": "faq", "content_type": "article", "status": "draft"}
        resp = self.post(self.url, data, user=self.grm_manager, follow=True)
        messages = list(resp.context["messages"])
        assert len(messages) == 1
        assert "created successfully" in str(messages[0])
        assert "Message Test" in str(messages[0])


class LearningMaterialUpdateViewTest(LmTestCase):
    def setUp(self):
        super().setUp()
        self.grm_manager = UserFactory(grm_manager=True)
        self.obj = LearningMaterial.objects.create(
            title_fr="Original",
            category="faq",
            content_type="article",
            status=LearningMaterial.Status.DRAFT,
        )
        self.url = reverse("dashboard:learning_materials:update", kwargs={"pk": self.obj.pk})

    def test_requires_grm_manager(self):
        resp = self.get(self.url, user=UserFactory())
        assert resp.status_code == 403

    def test_get_returns_200(self):
        resp = self.get(self.url, user=self.grm_manager)
        assert resp.status_code == 200

    def test_get_prefills_form(self):
        resp = self.get(self.url, user=self.grm_manager)
        form = resp.context_data["form"]
        assert form.instance.title_fr == "Original"

    def test_post_updates_material(self):
        data = {
            "title_fr": "Mis à jour",
            "category": "escalation",
            "content_type": "video",
            "status": "published",
        }
        resp = self.post(self.url, data, user=self.grm_manager)
        assert (
            resp.status_code == 302
        ), f"Form errors: {resp.context_data.get('form', {}).errors if hasattr(resp, 'context_data') else 'N/A'}"
        self.obj.refresh_from_db()
        assert self.obj.title_fr == "Mis à jour"
        assert self.obj.category == "escalation"
        assert self.obj.content_type == "video"

    def test_post_preserves_unchanged_fields(self):
        data = {"title_fr": "Original", "category": "faq", "content_type": "article", "status": "draft"}
        self.post(self.url, data, user=self.grm_manager)
        self.obj.refresh_from_db()
        assert self.obj.status == LearningMaterial.Status.DRAFT

    def test_success_message(self):
        data = {"title_fr": "Updated", "category": "faq", "content_type": "article", "status": "published"}
        resp = self.post(self.url, data, user=self.grm_manager, follow=True)
        messages = list(resp.context["messages"])
        assert len(messages) == 1
        assert "updated successfully" in str(messages[0])

    def test_post_with_roles(self):
        data = {
            "title_fr": "With Roles",
            "category": "faq",
            "content_type": "article",
            "status": "draft",
            "target_roles": ["citizen", "village_secretary"],
        }
        self.post(self.url, data, user=self.grm_manager)
        self.obj.refresh_from_db()
        assert self.obj.target_roles == ["citizen", "village_secretary"]

    def test_post_languages(self):
        data = {
            "title_fr": "FR",
            "title_en": "EN",
            "category": "faq",
            "content_type": "article",
            "status": "draft",
            "languages": ["fr", "en"],
        }
        self.post(self.url, data, user=self.grm_manager)
        self.obj.refresh_from_db()
        assert self.obj.languages == ["fr", "en"]


class LearningMaterialDeleteViewTest(LmTestCase):
    def setUp(self):
        super().setUp()
        self.grm_manager = UserFactory(grm_manager=True)
        self.obj = LearningMaterial.objects.create(
            title_fr="À supprimer",
            category="faq",
            content_type="article",
        )
        self.url = reverse("dashboard:learning_materials:delete", kwargs={"pk": self.obj.pk})

    def test_requires_grm_manager(self):
        resp = self.get(self.url, user=UserFactory())
        assert resp.status_code == 403

    def test_get_returns_200(self):
        resp = self.get(self.url, user=self.grm_manager)
        assert resp.status_code == 200

    def test_post_deletes_material(self):
        resp = self.post(self.url, {}, user=self.grm_manager)
        assert resp.status_code == 302
        assert LearningMaterial.objects.count() == 0

    def test_success_message(self):
        resp = self.post(self.url, {}, user=self.grm_manager)
        assert resp.status_code == 302
        assert resp.url == reverse("dashboard:learning_materials:home")
