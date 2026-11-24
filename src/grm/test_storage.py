from django.core.files.base import ContentFile
from django.core.files.storage import Storage


class InMemoryStorage(Storage):
    def _open(self, name, mode='rb'):
        return ContentFile(b"")

    def _save(self, name, content):
        return name

    def exists(self, name):
        return False

    def url(self, name):
        return f"/media/{name}"


# Django >= 5.1 configures storages through STORAGES (DEFAULT_FILE_STORAGE was removed).
_STATICFILES = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
IN_MEMORY_STORAGES = {"default": {"BACKEND": "grm.test_storage.InMemoryStorage"}, "staticfiles": _STATICFILES}
FILE_SYSTEM_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": _STATICFILES,
}
