from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from authentication.importer import AccountsImportError, import_accounts, validate_password


class Command(BaseCommand):
    help = (
        "Create the mobile accounts (committees CCGP / CLGP / national, field staff FC / SC with their villages) "
        "from an Excel workbook. The initial password is asked at the prompt. See docs/excel-import.md."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the .xlsx accounts workbook")

    def handle(self, *args, **options):
        password = getpass("Initial password for every account: ")
        if getpass("Confirm the password: ") != password:
            raise CommandError("The passwords do not match.")
        try:
            validate_password(password)
            with open(options["file"], "rb") as file_obj:
                report = import_accounts(file_obj, password)
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['file']}")
        except AccountsImportError as error:
            raise CommandError("Import refused, nothing was written:\n- " + "\n- ".join(error.errors))
        for label, count in report.counts.items():
            self.stdout.write(f"{label}: {count}")
        for line in report.skipped:
            self.stdout.write(self.style.WARNING(line))
        self.stdout.write(self.style.SUCCESS("Accounts imported."))
