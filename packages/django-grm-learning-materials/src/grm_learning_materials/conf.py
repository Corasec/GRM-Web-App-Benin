from django.conf import settings as django_settings
from django.utils.module_loading import import_string


class GrmLMSettings:
    _prefix = "GRM_LEARNING_MATERIALS"

    def _get(self, key, default=None):
        return getattr(django_settings, self._prefix, {}).get(key, default)

    @property
    def BASE_TEMPLATE(self):
        return self._get("BASE_TEMPLATE", "layouts/base.html")

    @property
    def PERMISSION_CALLBACK(self):
        return self._get("PERMISSION_CALLBACK", None)

    @property
    def UPLOAD_PATH_PREFIX(self):
        return self._get("UPLOAD_PATH_PREFIX", "learning_materials")

    @property
    def URL_NAMESPACE(self):
        return self._get("URL_NAMESPACE", "grm_learning_materials")

    def get_permission_check(self):
        callback_path = self.PERMISSION_CALLBACK
        if callback_path:
            return import_string(callback_path)
        return None


settings = GrmLMSettings()
