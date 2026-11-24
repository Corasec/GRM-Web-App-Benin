from django.core.management.base import BaseCommand, CommandError

from wizard.importer import ConfigurationImportError, import_configuration


class Command(BaseCommand):
    help = (
        "Import the whole wizard configuration (levels, hierarchy, committees, types / subtypes / categories, "
        "statuses, age groups, components) from an Excel workbook. See docs/excel-import.md."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to the .xlsx configuration workbook")

    def handle(self, *args, **options):
        try:
            with open(options["file"], "rb") as file_obj:
                report = import_configuration(file_obj)
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['file']}")
        except ConfigurationImportError as error:
            raise CommandError("Import refused, nothing was written:\n- " + "\n- ".join(error.errors))
        for label, count in report.counts.items():
            self.stdout.write(f"{label}: {count}")
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING(warning))
        self.stdout.write(
            self.style.SUCCESS("Configuration imported. Review the wizard summary and validate it to finish.")
        )
