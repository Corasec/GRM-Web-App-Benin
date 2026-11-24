import string
from datetime import datetime
from operator import itemgetter

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection
from django.template.defaultfilters import date as _date
from django.template.defaultfilters import filesizeformat
from django.utils import translation

# from openpyxl import load_workbook
# from openpyxl.utils.cell import range_boundaries
# note that we import 'Workbook' from spire
# keep in mind in case you want to import a class wih the same name from another package
# from spire.xls import *
# from spire.xls.common import *


def sort_dictionary_list_by_field(list_to_be_sorted, field, reverse=False):
    return sorted(list_to_be_sorted, key=itemgetter(field), reverse=reverse)


def get_month_range(start, end=datetime.now(), fmt="Y F"):
    start = start.month + 12 * start.year
    end = end.month + 12 * end.year
    months = list()
    for month in range(start - 1, end):
        y, m = divmod(month, 12)
        months.insert(0, (f"{y}-{m + 1}", _date(datetime(y, m + 1, 1), fmt)))
    return months


def get_choices(query_result, empty_choice=True):
    choices = [(i.id, i.name) for i in query_result]
    if empty_choice:
        choices = [("", "")] + choices
    return choices


def get_choices_select2(query_result, empty_choice=True):
    choices = [{"id": i.id, "value": i.name} for i in query_result]
    if empty_choice:
        choices = [{"id": "", "value": ""}] + choices
    return choices


def get_issue_select_options_choices(model_class, parent_id=None, empty_choice=True):
    from django.apps import apps

    query_result = apps.get_model("issues", model_class).objects.filter(parent=parent_id)
    return get_choices_select2(query_result, empty_choice)


def normalize_phone_number(phone_number, country_calling_code=None):
    """
    Return ``phone_number`` in international format (``+<country code><number>``).

    Accepted inputs (Benin examples): ``+229 01 97 00 00 00``, ``00229 0197000000``,
    ``2290197000000`` and the national format ``01 97 00 00 00``, which gets the country code
    from ``settings.COUNTRY_CALLING_CODE`` (``229``, ``+229`` or ``00229``).
    Returns ``""`` when there is no digit.
    """
    raw = (phone_number or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""

    if raw.startswith("+"):
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"

    code = "".join(ch for ch in str(country_calling_code or settings.COUNTRY_CALLING_CODE or "") if ch.isdigit())
    code = code[2:] if code.startswith("00") else code
    if not code:
        return f"+{digits}"
    # Already prefixed with the country code (longer than a national number)
    if digits.startswith(code) and len(digits) - len(code) >= 8:
        return f"+{digits}"
    return f"+{code}{digits}"


def reset_sequences():
    with connection.cursor() as cursor:
        for table_name in [
            'issues_administrativelevel',
            'issues_issuedepartment',
            'issues_issuedepartmentadministrativelevel',
        ]:
            cursor.execute(
                f"""
                SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), 
                              (SELECT COALESCE(MAX(id), 1) FROM {table_name}));
            """
            )


def email_is_valid(email):
    try:
        validate_email(email)
        return True
    except ValidationError:
        return False


def filesizeformat_en(value):
    """Return file size in English (MB, GB, etc.) regardless of active locale."""
    with translation.override("en"):
        return filesizeformat(value)
