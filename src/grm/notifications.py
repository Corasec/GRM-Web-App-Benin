import logging

import cryptocode
from django.utils.translation import gettext as _

from authentication.models import Cdata
from grm.constants import (
    ALERT_CHOICE,
    EMAIL_CHOICE,
    NOTIFICATION_TYPES,
    PHONE_CHOICE,
    WHATSAPP_CHOICE,
)
from grm.utils import normalize_phone_number
from mail_client import send_mail_notification
from sms_client import send_sms

# Twilio splits long SMS into several parts (concatenated on the phone), up to 1600 characters.
SMS_MAX_LENGTH = 1600

logger = logging.getLogger(__name__)


def send_issue_notification(issue, notification_type, message_template=None):
    """
    Send a notification to the issue contact according to the configured contact_method.

    Args:
        issue: Issue model instance
        notification_type: Notification type ('created', 'status_changed', 'appealed', 'assigned')
        message_template: Message template (optional, a default will be generated if not provided)

    Returns:
        bool: True if notification was sent successfully, False otherwise

    Raises:
        ValueError: If notification_type is not supported
    """
    # Validate notification type
    if notification_type not in NOTIFICATION_TYPES:
        raise ValueError(
            f"Unsupported notification_type: '{notification_type}'. "
            f"Supported types: {', '.join(sorted(NOTIFICATION_TYPES))}"
        )

    # Only citizens who asked for direct alerts are notified. Those who chose not to be contacted,
    # or to be kept informed by the facilitator / committee who registered the issue, get nothing.
    if issue.contact_medium != ALERT_CHOICE:
        logger.info(f"Issue {issue.id}: citizen did not ask for direct alerts, skipping notification")
        return False

    if not issue.contact_method:
        logger.info(f"Issue {issue.id}: No contact method specified, skipping notification")
        return False

    # Get decrypted contact from Cdata
    try:
        cdata = Cdata.objects.filter(key=str(issue.id)).first()
        if not cdata:
            logger.warning(f"Issue {issue.id}: No contact information found in Cdata")
            return False

        contact_info = cryptocode.decrypt(cdata.data, str(issue.id))
        if not contact_info:
            logger.warning(f"Issue {issue.id}: Failed to decrypt contact information")
            return False
    except Exception as e:
        logger.error(f"Issue {issue.id}: Error retrieving contact information: {str(e)}")
        return False

    # Send according to contact method
    try:
        if issue.contact_method == EMAIL_CHOICE:
            message = message_template or _generate_default_message(issue, notification_type)
            return _send_email_notification(issue, contact_info, notification_type, message)
        elif issue.contact_method in [PHONE_CHOICE, WHATSAPP_CHOICE]:
            # WhatsApp needs an approved WhatsApp sender: until then, WhatsApp contacts get an SMS.
            message = message_template or _generate_sms_message(issue, notification_type)
            return _send_sms_notification(issue, contact_info, notification_type, message)
        else:
            logger.warning(f"Issue {issue.id}: Unknown contact method '{issue.contact_method}'")
            return False
    except Exception as e:
        logger.error(f"Issue {issue.id}: Error sending notification: {str(e)}")
        return False


def _send_email_notification(issue, email, notification_type, message):
    """
    Send a notification via email.

    Args:
        issue: Issue model instance
        email: Recipient email address
        notification_type: Type of notification
        message: Message body

    Returns:
        bool: True if sent successfully, False otherwise

    Raises:
        Exception: If email sending fails
    """
    subject = _generate_email_subject(issue, notification_type)

    try:
        send_mail_notification(subject=subject, message=message, recipient=email)
        logger.info(f"Issue {issue.id}: Email notification ({notification_type}) sent successfully to {email}")
        return True
    except Exception as e:
        logger.error(f"Issue {issue.id}: Failed to send email ({notification_type}) to {email}: {str(e)}")
        raise


def _send_sms_notification(issue, phone_number, notification_type, message):
    """
    Send a notification via SMS/WhatsApp.

    Args:
        issue: Issue model instance
        phone_number: Recipient phone number
        notification_type: Type of notification
        message: Message body

    Returns:
        bool: True if sent successfully, False otherwise

    Raises:
        Exception: If SMS sending fails
    """
    # Long messages are sent as a multi-part SMS: only cap at the provider limit.
    sms_message = message[:SMS_MAX_LENGTH]

    # International format with the country calling code
    phone = normalize_phone_number(phone_number)

    try:
        send_sms(to=phone, body=sms_message)
        logger.info(f"Issue {issue.id}: SMS notification ({notification_type}) sent successfully to {phone}")
        return True
    except Exception as e:
        logger.error(f"Issue {issue.id}: Failed to send SMS ({notification_type}) to {phone}: {str(e)}")
        raise


def _generate_email_subject(issue, notification_type):
    """
    Generate email subject based on notification type.

    Args:
        issue: Issue model instance
        notification_type: Type of notification

    Returns:
        str: Formatted email subject
    """
    subjects = {
        'created': _("Issue Created - Tracking Code: {tracking_code}"),
        'status_changed': _("Issue Status Updated - Tracking Code: {tracking_code}"),
        'appealed': _("Issue Appealed - Tracking Code: {tracking_code}"),
        'assigned': _("Issue Assigned - Tracking Code: {tracking_code}"),
        'escalated': _("Issue Escalated - Tracking Code: {tracking_code}"),
    }

    subject_template = subjects.get(notification_type, _("Issue Notification - Tracking Code: {tracking_code}"))
    return subject_template.format(tracking_code=issue.tracking_code)


def _generate_default_message(issue, notification_type):
    """
    Generate a default message based on notification type.

    Args:
        issue: Issue model instance
        notification_type: Type of notification

    Returns:
        str: Formatted message body with issue details

    Examples:
        >>> message = _generate_default_message(issue, 'created')
        >>> 'Tracking Code:' in message
        True
    """
    # Base message templates
    messages = {
        'created': _(
            "Dear citizen,\n\n"
            "Your issue has been successfully created.\n"
            "Tracking Code: {tracking_code}\n"
            "Status: {status}\n\n"
            "Thank you for your report."
        ),
        'status_changed': _(
            "Dear citizen,\n\n"
            "The status of your issue has been updated.\n"
            "Tracking Code: {tracking_code}\n"
            "New Status: {status}\n"
            "{additional_info}\n"
            "Thank you for your patience."
        ),
        'appealed': _(
            "Dear citizen,\n\n"
            "Your appeal has been sent.\n"
            "Tracking Code: {tracking_code}\n"
            "Current Status: {status}\n"
            "Appeal Status: {appeal_status}\n"
            "{additional_info}\n"
            "Thank you for your patience."
        ),
        'assigned': _(
            "Dear citizen,\n\n"
            "Your issue has been assigned to a staff member.\n"
            "Tracking Code: {tracking_code}\n"
            "Status: {status}\n\n"
            "We are working on resolving your issue."
        ),
        'escalated': _(
            "Dear citizen,\n\n"
            "Your issue has been forwarded to the committee of the next level for processing.\n"
            "Tracking Code: {tracking_code}\n"
            "Status: {status}\n\n"
            "Thank you for your patience."
        ),
    }

    message_template = messages.get(
        notification_type,
        _("Dear citizen,\n\n" "Your issue has been updated.\n" "Tracking Code: {tracking_code}\n\n" "Thank you."),
    )

    # Build additional info for status_changed and appealed notifications
    additional_info = ""
    if notification_type == 'status_changed':
        if issue.research_result:
            additional_info = _("Resolution: {research_result}\n").format(research_result=issue.research_result)
        elif issue.reject_reason:
            additional_info = _("Reject Reason: {reject_reason}\n").format(reject_reason=issue.reject_reason)
    elif notification_type == 'appealed':
        additional_info = _("Appeal Reason: {appeal_reason}\n").format(appeal_reason=issue.appeal_reason)

    return message_template.format(
        tracking_code=issue.tracking_code,
        status=issue.status.name if issue.status else _("Unknown"),
        appeal_status=_("In progress") if issue.appeal_status else _("Processed"),
        additional_info=additional_info,
    )


def _generate_sms_message(issue, notification_type):
    """
    Short SMS text: the tracking code comes first so it is never lost, followed by the
    resolution / reject reason / appeal reason when relevant (never truncated at 160 characters).
    French translations avoid accents on purpose: an SMS with accents is sent in UCS-2
    (70 characters per part instead of 160), which doubles its cost.
    """
    status = issue.status.name if issue.status else _("Unknown")
    messages = {
        'created': _("GRM - Complaint {tracking_code} registered. Keep this code to follow your case."),
        'status_changed': _("GRM - Complaint {tracking_code}: new status \"{status}\"."),
        'appealed': _("GRM - Complaint {tracking_code}: your appeal has been registered."),
        'assigned': _("GRM - Complaint {tracking_code}: taken in charge by the committee."),
        'escalated': _("GRM - Complaint {tracking_code}: forwarded to the committee of the next level."),
    }
    message = messages.get(notification_type, _("GRM - Complaint {tracking_code} updated.")).format(
        tracking_code=issue.tracking_code, status=status
    )

    if notification_type == 'status_changed':
        if issue.research_result:
            message += " " + _("Resolution: {text}").format(text=issue.research_result)
        elif issue.reject_reason:
            message += " " + _("Reason: {text}").format(text=issue.reject_reason)
    elif notification_type == 'appealed' and issue.appeal_reason:
        message += " " + _("Reason: {text}").format(text=issue.appeal_reason)
    return message
