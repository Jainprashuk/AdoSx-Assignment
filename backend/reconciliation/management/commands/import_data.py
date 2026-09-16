"""Load the bundled sample CSVs into a batch."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from reconciliation.ingest import (
    LOCATIONS_FILE, SYSTEM_A_FILE, SYSTEM_B_FILE, ImportAborted, import_batch,
)
from reconciliation.models import Batch

# Fixed label, so re-running replaces this command's own batch instead of
# stacking up copies. Uploaded batches are labelled by time and never touched.
SEED_LABEL = "Seeded sample data"

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class Command(BaseCommand):
    help = "Import locations.csv, system_a.csv and system_b.csv as one batch."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir", type=Path, default=DEFAULT_DATA_DIR,
            help=f"Directory holding the three CSVs (default: {DEFAULT_DATA_DIR}).",
        )
        parser.add_argument(
            "--label", default=SEED_LABEL,
            help="Batch label. Re-running with the same label replaces that batch.",
        )

    def handle(self, *args, **options):
        data_dir: Path = options["data_dir"]
        label: str = options["label"]

        paths = {name: data_dir / name for name in (LOCATIONS_FILE, SYSTEM_A_FILE, SYSTEM_B_FILE)}
        missing = [str(path) for path in paths.values() if not path.exists()]
        if missing:
            raise CommandError("missing file(s): " + ", ".join(missing))

        # Idempotent by replacement rather than by upsert: the batch is a closed
        # world, so there is nothing to merge -- the old one goes and a new one
        # takes its place.
        replaced = Batch.objects.filter(label=label).count()
        Batch.objects.filter(label=label).delete()

        # utf-8-sig so a byte-order mark from a spreadsheet export does not end
        # up glued to the first column name.
        opened = {}
        try:
            for name, path in paths.items():
                opened[name] = path.open(newline="", encoding="utf-8-sig")
            summary = import_batch(
                label,
                opened[LOCATIONS_FILE],
                opened[SYSTEM_A_FILE],
                opened[SYSTEM_B_FILE],
            )
        except ImportAborted as exc:
            raise CommandError(str(exc)) from exc
        finally:
            for handle in opened.values():
                handle.close()

        if options["verbosity"] == 0:
            return

        if replaced:
            self.stdout.write(f"Replaced {replaced} existing batch labelled {label!r}.")
        self.stdout.write(f"Batch {summary.batch_id}: {summary.label}")
        for file_summary in summary.files:
            self.stdout.write(
                f"  {file_summary.name:16} read {file_summary.rows_read:4}  "
                f"written {file_summary.rows_written:4}  issues {file_summary.issues:4}"
            )
        self.stdout.write(self.style.SUCCESS(
            f"{summary.total_issues} issue(s) logged. No rows dropped."
        ))
