from django.test import TestCase, override_settings
from grm_learning_materials.models import LearningMaterial


@override_settings(
    GRM_LEARNING_MATERIALS={
        "PERMISSION_CALLBACK": None,
    },
    ROOT_URLCONF="grm_learning_materials.urls",
)
class LearningMaterialModelTest(TestCase):
    def test_create_minimal(self):
        obj = LearningMaterial.objects.create(
            title_fr="Titre",
            category="getting_started",
            content_type="article",
        )
        self.assertEqual(obj.title_fr, "Titre")
        self.assertEqual(obj.title_en, "")
        self.assertEqual(obj.status, LearningMaterial.Status.DRAFT)
        self.assertEqual(obj.target_roles, [])
        self.assertEqual(obj.languages, [])
        self.assertEqual(str(obj), "Titre")

    def test_str_fallback_to_english(self):
        obj = LearningMaterial.objects.create(
            title_en="Title",
            category="faq",
            content_type="video",
        )
        self.assertEqual(str(obj), "Title")

    def test_str_fallback_to_pk(self):
        obj = LearningMaterial.objects.create(
            category="faq",
            content_type="article",
        )
        self.assertEqual(str(obj), str(obj.pk))

    def test_filename_property(self):
        obj = LearningMaterial.objects.create(
            title_fr="Test",
            category="faq",
            content_type="article",
        )
        self.assertEqual(obj.filename, "")


class LearningMaterialPermissionTest(TestCase):
    def test_anonymous_user_redirected(self):
        resp = self.client.get("/learning-materials/")
        self.assertIn(resp.status_code, (302, 404))
