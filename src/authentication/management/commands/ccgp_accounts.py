import logging
import os
import re
import unicodedata
from datetime import datetime

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.contrib.auth.hashers import make_password

from authentication.models import GovernmentWorker
from no_sql_client import NoSQLClient
from dashboard.utils import get_administrative_levels_by_level_and_name
from grm.constants import ADMINISTRATIVE_LEVEL_TYPE


User = get_user_model()
DEFAULT_PASSWORD = "ChangeMe123!"
LOG_FILE = "ccgp_accounts_log.txt"


def clean_name(name):
    """Removes accents and special characters from identifiers."""
    if not isinstance(name, str):
        name = str(name)
    name = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("utf-8")
    name = re.sub(r"[^a-zA-Z0-9_]", "", name)
    return name.lower().strip()


class Command(BaseCommand):
    help = "Manage creation and deletion of CCGP village accounts (SQL + CouchDB)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["create", "delete"])
        parser.add_argument("file", nargs="?", type=str, help="Path to Excel file (required for create).")
        parser.add_argument("--dry-run", action="store_true", help="Simulate actions without changes.")

    def handle(self, *args, **options):
        action = options["action"]
        dry_run = options["dry_run"]

        if action == "create":
            file_path = options.get("file")
            if not file_path:
                raise CommandError("File path is required for creation.")
            self.create_ccgp_accounts(file_path, dry_run)
        elif action == "delete":
            self.delete_ccgp_accounts(dry_run)

    # ----------------------------------------------------------
    # CREATE COMMAND
    # ----------------------------------------------------------
    def create_ccgp_accounts(self, file_path, dry_run):
        logger = logging.getLogger(__name__)
        logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

        mode = "(DRY-RUN)" if dry_run else ""
        self.stdout.write(self.style.MIGRATE_HEADING(f"Starting CCGP account creation {mode}..."))

        try:
            data = pd.read_excel(file_path)
        except Exception as e:
            raise CommandError(f"Error reading file: {e}")

        # Prepare output copy
        results = data.copy()
        results["STATUS"] = ""
        results["EMAIL"] = ""
        results["MESSAGE"] = ""

        nsc = NoSQLClient()
        administrative_levels_db = nsc.get_db("administrative_levels")

        saved_count = 0
        skipped_count = 0

        for index, row in data.iterrows():
            try:
                dept_name = str(row["DÉPARTEMENT"]).upper().strip()
                commune_name = str(row["COMMUNE"]).upper().strip()
                arr_name = str(row["ARRONDISSEMENT"]).upper().strip()
                village_name = str(row["VILLAGE"]).upper().strip()
                alt_name = str(row.get("ALTERNATIVE", "")).upper().strip()
            except KeyError:
                raise CommandError("Excel file must contain columns: DÉPARTEMENT, COMMUNE, ARRONDISSEMENT, VILLAGE")

            # Lookup
            try:
                dept = get_administrative_levels_by_level_and_name(
                    administrative_levels_db, ADMINISTRATIVE_LEVEL_TYPE.DÉPARTEMENT, dept_name
                )[0][0]
                commune = get_administrative_levels_by_level_and_name(
                    administrative_levels_db, ADMINISTRATIVE_LEVEL_TYPE.COMMUNE, commune_name
                )[0][0]

                try:
                    village = get_administrative_levels_by_level_and_name(
                        administrative_levels_db, ADMINISTRATIVE_LEVEL_TYPE.VILLAGE, village_name
                    )[0][0]
                except Exception:
                    if alt_name:
                        village = get_administrative_levels_by_level_and_name(
                            administrative_levels_db, ADMINISTRATIVE_LEVEL_TYPE.VILLAGE, alt_name
                        )[0][0]
                        msg = f"Used ALTERNATIVE name '{alt_name}' for line {index+1}."
                        self.stdout.write(self.style.NOTICE(msg))
                        logger.info(msg)
                    else:
                        raise

            except Exception:
                msg = f"Skipped line {index + 1}: Could not match administrative levels ({dept_name}, {commune_name}, {arr_name}, {village_name})."
                logger.warning(msg)
                self.stdout.write(self.style.WARNING(msg))
                skipped_count += 1
                results.loc[index, ["STATUS", "MESSAGE"]] = ["SKIPPED", msg]
                continue

            administrative_id = village["administrative_id"]
            name_chain = f"{dept_name}, {commune_name}, {arr_name}, {village_name}"

            # Clean village name for identifiers
            clean_village = clean_name(village_name)
            username = f"ccgp_{clean_village}"
            base_local = clean_name(village_name)
            base_email = f"ccgp@{base_local}.bj"

            email = base_email
            i = 1
            while User.objects.filter(email=email).exists():
                email = f"ccgp.{i}@{base_local}.bj"
                i += 1

            password_hashed = make_password(DEFAULT_PASSWORD)

            if dry_run:
                msg = f"[DRY-RUN] Would create account for {village_name} ({email})"
                logger.info(msg)
                self.stdout.write(self.style.NOTICE(msg))
                saved_count += 1
                results.loc[index, ["STATUS", "EMAIL", "MESSAGE"]] = ["DRY-RUN", email, "Simulated creation"]
                continue

            # ---- Actual creation ----
            try:
                with transaction.atomic():
                    user, created = User.objects.get_or_create(
                        email=email,
                        defaults={"username": username, "password": password_hashed, "is_active": True},
                    )

                    if not created:
                        msg = f"User with email {email} already exists. Skipped."
                        logger.info(msg)
                        self.stdout.write(self.style.WARNING(msg))
                        skipped_count += 1
                        results.loc[index, ["STATUS", "EMAIL", "MESSAGE"]] = ["SKIPPED", email, msg]
                        continue

                    GovernmentWorker.objects.create(user=user, department=1, administrative_id=administrative_id)

                    doc_properties = {
                        "type": "adl",
                        "name": name_chain,
                        "photo": "https://via.placeholder.com/150",
                        "location": {"lat": None, "long": None},
                        "representative": {
                            "id": user.id,
                            "name": f"CCGP {village_name.title()}",
                            "email": email,
                            "photo": "https://via.placeholder.com/150",
                            "is_active": True,
                        },
                        "representative_id": user.id,
                        "phases": [],
                        "administrative_level": "village",
                        "administrative_region": administrative_id,
                        "department": 1,
                        "unique_region": 0,
                        "village_secretary": 1,
                    }

                    nsc.create_document(administrative_levels_db, doc_properties)

                    msg = f"Created CCGP account for {village_name} ({email})."
                    logger.info(msg)
                    self.stdout.write(self.style.SUCCESS(msg))
                    saved_count += 1
                    results.loc[index, ["STATUS", "EMAIL", "MESSAGE"]] = ["CREATED", email, "Success"]

            except Exception as e:
                msg = f"Error on line {index + 1} ({village_name}): {e}"
                logger.error(msg)
                self.stdout.write(self.style.ERROR(msg))
                skipped_count += 1
                results.loc[index, ["STATUS", "EMAIL", "MESSAGE"]] = ["ERROR", email, str(e)]
                continue

        # Save result file
        output_path = os.path.join(
            os.path.dirname(file_path),
            f"ccgp_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )
        results.to_excel(output_path, index=False)

        summary = (
            f"\nSummary: Created={saved_count}, Skipped={skipped_count} {'(DRY-RUN)' if dry_run else ''}"
            f"\nLog file: {LOG_FILE}\nResults saved to: {output_path}"
        )
        self.stdout.write(self.style.MIGRATE_HEADING(summary))
        logger.info(summary)

    # ----------------------------------------------------------
    # DELETE COMMAND
    # ----------------------------------------------------------
    def delete_ccgp_accounts(self, dry_run):
        logger = logging.getLogger(__name__)
        logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

        mode = "(DRY-RUN)" if dry_run else ""
        self.stdout.write(self.style.MIGRATE_HEADING(f"Starting CCGP account deletion {mode}..."))

        nsc = NoSQLClient()
        administrative_levels_db = nsc.get_db("administrative_levels")

        users = User.objects.filter(email__startswith="ccgp")
        deleted_count = 0
        skipped_count = 0

        for user in users:
            try:
                gov_worker = GovernmentWorker.objects.get(user=user, department=1)
                admin_id = gov_worker.administrative_id

                if dry_run:
                    msg = f"[DRY-RUN] Would delete {user.email} (administrative_id={admin_id})"
                    logger.info(msg)
                    self.stdout.write(self.style.NOTICE(msg))
                    deleted_count += 1
                    continue

                query_result = administrative_levels_db.get_query_result(
                    {"type": "adl", "administrative_region": admin_id}
                )

                if query_result:
                    doc_id = query_result[0]["_id"]
                    nsc.delete_doc(administrative_levels_db, doc_id)

                gov_worker.delete()
                user.delete()

                msg = f"Deleted CCGP account for {user.email}."
                logger.info(msg)
                self.stdout.write(self.style.SUCCESS(msg))
                deleted_count += 1

            except GovernmentWorker.DoesNotExist:
                msg = f"Skipped {user.email}: GovernmentWorker not found."
                logger.warning(msg)
                self.stdout.write(self.style.WARNING(msg))
                skipped_count += 1
            except Exception as e:
                msg = f"Error deleting {user.email}: {e}"
                logger.error(msg)
                self.stdout.write(self.style.ERROR(msg))
                skipped_count += 1

        summary = (
            f"\nSummary: Deleted={deleted_count}, Skipped={skipped_count} {'(DRY-RUN)' if dry_run else ''}"
            f"\nLog file: {LOG_FILE}"
        )
        self.stdout.write(self.style.MIGRATE_HEADING(summary))
        logger.info(summary)
