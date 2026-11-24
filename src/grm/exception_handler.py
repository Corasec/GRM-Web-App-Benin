from django.http import Http404
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    """
    Keep the documented API error contract for 404 responses: ``{"detail": "Not found."}``.

    Since DRF 3.15, an ``Http404`` raised by ``get_object_or_404`` exposes Django's message
    (e.g. "No Issue matches the given query."), which also leaks model names. The mobile app
    and docs/errors.md rely on the generic message.
    """
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    return drf_exception_handler(exc, context)
