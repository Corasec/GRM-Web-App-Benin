from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from authentication.models import User


class Command(BaseCommand):
    help = (
        "Create (or upgrade) the administrator of a new installation: GRM owner (runs the setup wizard), "
        "GRM manager (user management, sees every issue) and Django superuser (admin, reveals complainant "
        "contacts). The dashboard login is the email. The password is asked at the prompt."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="Administrateur")
        parser.add_argument("--last-name", default="MGP")
        parser.add_argument("--phone", default="")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        password = None
        if user is None or input("This email already exists. Reset its password? [y/N] ").strip().lower() == "y":
            password = getpass("Password: ")
            if getpass("Confirm the password: ") != password:
                raise CommandError("The passwords do not match.")
            try:
                validate_password(password)
            except ValidationError as error:
                raise CommandError(" ".join(error.messages))

        created = user is None
        if created:
            user = User(email=email, username=email)
        user.first_name = user.first_name or options["first_name"]
        user.last_name = user.last_name or options["last_name"]
        user.phone_number = user.phone_number or options["phone"]
        user.is_active = True
        user.grm_owner = True
        user.grm_manager = True
        user.is_staff = True
        user.is_superuser = True
        if password:
            user.set_password(password)
        user.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} {email}: GRM owner + GRM manager + superuser. "
                "Log in on the dashboard with this email to run the setup wizard."
            )
        )
