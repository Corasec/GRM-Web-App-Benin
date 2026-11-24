"""Password rule shared by the account import, the mobile password change and the dashboard reset."""

import re

from django.utils.translation import gettext_lazy as _

# At least 8 characters with letters and digits: simple enough for field users, not trivial
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")
PASSWORD_RULE_MESSAGE = _("The password must have at least 8 characters, with letters and digits.")


def is_valid_password(password):
    return bool(password) and PASSWORD_PATTERN.match(password) is not None
