from unittest.mock import patch

import cryptocode
import pytest
from django.test import TestCase, override_settings
from django.utils import translation

from authentication.models import Cdata
from grm.constants import (
    ALERT_CHOICE,
    ANONYMOUS_CHOICE,
    EMAIL_CHOICE,
    FACILITATOR_CHOICE,
    PHONE_CHOICE,
    WHATSAPP_CHOICE,
)
from grm.notifications import send_issue_notification
from grm.utils import normalize_phone_number, reset_sequences
from issues.factories import IssueFactory, IssueStatusFactory


@pytest.mark.django_db
@override_settings(COUNTRY_CALLING_CODE="229", LANGUAGE_CODE="en-us")
class SendIssueNotificationTest(TestCase):
    """Citizens who asked for direct alerts are notified by SMS (phone / WhatsApp) or email."""

    def setUp(self):
        reset_sequences()
        translation.activate("en")
        self.status = IssueStatusFactory(name="Resolved", final_status=True)

    def tearDown(self):
        translation.deactivate()

    def _issue(self, contact, contact_method=PHONE_CHOICE, contact_medium=ALERT_CHOICE, **kwargs):
        issue = IssueFactory(
            tracking_code="lac286",
            contact_medium=contact_medium,
            contact_method=contact_method,
            contact_information="*",
            status=self.status,
            **kwargs,
        )
        # Contact information is stored encrypted, keyed by the issue id (see Issue.anonymize_issue_data)
        Cdata.objects.create(key=str(issue.id), data=cryptocode.encrypt(contact, str(issue.id)))
        return issue

    @patch("grm.notifications.send_sms")
    def test_sms_sent_to_normalized_number(self, send_sms):
        issue = self._issue("01 97 00 00 00")

        assert send_issue_notification(issue, "created") is True

        send_sms.assert_called_once()
        assert send_sms.call_args.kwargs["to"] == "+2290197000000"
        assert "lac286" in send_sms.call_args.kwargs["body"]

    @patch("grm.notifications.send_sms")
    def test_whatsapp_contact_receives_an_sms(self, send_sms):
        issue = self._issue("+229 01 97 00 00 00", contact_method=WHATSAPP_CHOICE)

        assert send_issue_notification(issue, "created") is True
        assert send_sms.call_args.kwargs["to"] == "+2290197000000"

    @patch("grm.notifications.send_mail_notification")
    def test_email_sent_with_tracking_code(self, send_mail):
        issue = self._issue("citizen@example.com", contact_method=EMAIL_CHOICE)

        assert send_issue_notification(issue, "created") is True

        kwargs = send_mail.call_args.kwargs
        assert kwargs["recipient"] == "citizen@example.com"
        assert "lac286" in kwargs["subject"]
        assert "lac286" in kwargs["message"]

    @patch("grm.notifications.send_mail_notification")
    @patch("grm.notifications.send_sms")
    def test_nothing_sent_when_citizen_does_not_want_to_be_contacted(self, send_sms, send_mail):
        issue = self._issue("01 97 00 00 00", contact_medium=ANONYMOUS_CHOICE)

        assert send_issue_notification(issue, "created") is False
        send_sms.assert_not_called()
        send_mail.assert_not_called()

    @patch("grm.notifications.send_sms")
    def test_nothing_sent_when_citizen_follows_through_the_facilitator(self, send_sms):
        issue = self._issue("01 97 00 00 00", contact_medium=FACILITATOR_CHOICE)

        assert send_issue_notification(issue, "status_changed") is False
        send_sms.assert_not_called()

    @patch("grm.notifications.send_sms")
    def test_resolution_sms_is_not_truncated(self, send_sms):
        resolution = "Le forage du village a ete repare par l'entreprise et remis en service le 12 novembre. " * 3
        issue = self._issue("0197000000", research_result=resolution)

        assert send_issue_notification(issue, "status_changed") is True

        body = send_sms.call_args.kwargs["body"]
        assert body.startswith("GRM - Complaint lac286")
        assert resolution.strip() in body
        assert len(body) > 160

    @patch("grm.notifications.send_sms")
    def test_appeal_notification_is_sent(self, send_sms):
        """Regression: the appeal message referenced {appeal_status} without providing it (KeyError)."""
        issue = self._issue("0197000000", appeal_status=True, appeal_reason="Resolution non satisfaisante")

        assert send_issue_notification(issue, "appealed") is True
        assert "Resolution non satisfaisante" in send_sms.call_args.kwargs["body"]

    @patch("grm.notifications.send_mail_notification")
    def test_appeal_email_is_sent(self, send_mail):
        issue = self._issue("citizen@example.com", contact_method=EMAIL_CHOICE, appeal_status=True, appeal_reason="X")

        assert send_issue_notification(issue, "appealed") is True
        send_mail.assert_called_once()

    @patch("grm.notifications.send_sms")
    def test_french_sms_has_no_accents(self, send_sms):
        """Accents switch SMS to UCS-2 (70 characters per part instead of 160): keep them out."""
        issue = self._issue("0197000000")

        with translation.override("fr"):
            send_issue_notification(issue, "created")

        body = send_sms.call_args.kwargs["body"]
        assert body.startswith("MGP - Plainte lac286")
        assert body.isascii()


@override_settings(COUNTRY_CALLING_CODE="229")
class NormalizePhoneNumberTest(TestCase):
    def test_national_number_gets_country_code(self):
        assert normalize_phone_number("01 97 00 00 00") == "+2290197000000"

    def test_international_formats(self):
        assert normalize_phone_number("+229 01 97 00 00 00") == "+2290197000000"
        assert normalize_phone_number("00229 0197000000") == "+2290197000000"
        assert normalize_phone_number("2290197000000") == "+2290197000000"

    def test_separators_are_removed(self):
        assert normalize_phone_number("01-97.00 00/00") == "+2290197000000"

    def test_country_code_setting_accepts_any_format(self):
        for code in ["229", "+229", "00229"]:
            assert normalize_phone_number("0197000000", country_calling_code=code) == "+2290197000000"

    def test_empty_values(self):
        assert normalize_phone_number("") == ""
        assert normalize_phone_number(None) == ""
