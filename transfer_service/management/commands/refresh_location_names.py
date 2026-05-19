"""
Refresh source_location_name on InboundDelivery and SourceLocationAuthorization
from SAP ByD's khlocation/LocationCollection.

InboundDelivery rows created before the SAP lookup landed contain hardcoded
"Warehouse <id>" placeholders. The SCD backfill migration propagated those
placeholders to SourceLocationAuthorization. Run this once after deploying to
replace them with the real names; safe to re-run any time SAP names change.
"""
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from byd_service.rest import RESTServices
from transfer_service.models import InboundDelivery, SourceLocationAuthorization

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Refresh source_location_name from SAP for all known warehouses."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        location_ids = list(
            InboundDelivery.objects
                .exclude(source_location_id="")
                .values_list("source_location_id", flat=True)
                .distinct()
        )
        # Also pick up any IDs only present in the auth table.
        location_ids = list(set(location_ids) | set(
            SourceLocationAuthorization.objects
                .exclude(source_location_id="")
                .values_list("source_location_id", flat=True)
        ))

        if not location_ids:
            self.stdout.write("No source locations to refresh.")
            return

        self.stdout.write(f"Refreshing {len(location_ids)} location(s) from SAP...")

        byd = RESTServices()
        resolved = {}
        for loc_id in location_ids:
            try:
                location = byd.get_location_by_id(loc_id)
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"  {loc_id}: SAP fetch failed ({e}), skipping"))
                continue

            name = (location or {}).get("Name", "").strip()
            if not name:
                self.stderr.write(self.style.WARNING(f"  {loc_id}: SAP returned no Name, skipping"))
                continue

            resolved[loc_id] = name
            self.stdout.write(f"  {loc_id} -> {name}")

        if not resolved:
            self.stdout.write(self.style.WARNING("Nothing resolved; aborting."))
            return

        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry run — no writes."))
            return

        with transaction.atomic():
            updated_deliveries = 0
            updated_auths = 0
            for loc_id, name in resolved.items():
                updated_deliveries += InboundDelivery.objects.filter(
                    source_location_id=loc_id,
                ).exclude(source_location_name=name).update(source_location_name=name)

                updated_auths += SourceLocationAuthorization.objects.filter(
                    source_location_id=loc_id,
                ).exclude(source_location_name=name).update(source_location_name=name)

        self.stdout.write(self.style.SUCCESS(
            f"Done. Updated {updated_deliveries} InboundDelivery row(s) and "
            f"{updated_auths} SourceLocationAuthorization row(s)."
        ))
