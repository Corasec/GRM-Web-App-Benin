"""
Who can see the complainant's name and contact (COSO rules).

- Mobile app: the committee handling the issue (assignee) and the reporter (e.g. the facilitator
  who registered it) see the name and the contact directly.
- Dashboard: nobody sees them, except superusers and the national committee account, which can
  reveal them on any issue after re-entering its password.

The name and the contact are stored encrypted (Pdata / Cdata, see Issue.anonymize_issue_data);
the issue itself only keeps "*".
"""

import cryptocode

from authentication.models import Cdata, Pdata

ANONYMIZED_VALUE = "*"


def _decrypt(model, issue):
    key = str(issue.id)
    row = model.objects.filter(key=key).first()
    if not row or not row.data:
        return None
    return cryptocode.decrypt(row.data, key) or None


def get_citizen_name(issue):
    """Real name of the complainant ('' when anonymous)."""
    citizen = issue.citizen
    if citizen is None:
        return ""
    if citizen.name != ANONYMIZED_VALUE:
        return citizen.name or ""
    return _decrypt(Pdata, issue) or ""


def get_contact_information(issue):
    """Real contact (phone / email) of the complainant, or '' when none was given."""
    contact = issue.contact_information
    if contact and contact != ANONYMIZED_VALUE:
        return contact
    if contact == ANONYMIZED_VALUE:
        return _decrypt(Cdata, issue) or ""
    return ""


def can_see_complainant_in_app(user, issue):
    """The committee in charge and the reporter see the complainant's name and contact in the app."""
    return bool(user and user.is_authenticated and user.id in (issue.assignee_id, issue.reporter_id))


def is_national_committee(user):
    worker = getattr(user, "governmentworker", None)
    return worker is not None and worker.administrative_region.parent_id is None


def can_reveal_in_dashboard(user):
    """Dashboard: only superusers and the national committee can reveal (with their password)."""
    return bool(user and user.is_authenticated and (user.is_superuser or is_national_committee(user)))
