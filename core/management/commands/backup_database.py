import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

BACKUP_RETENTION_DAYS = 14


class Command(BaseCommand):
    help = (
        "Nightly: pg_dump the database and upload to S3, pruning backups older "
        "than 14 days (solution-plan.md Step 12). boto3 (requirements/prod.txt) "
        "is imported lazily so a dev checkout without it can still load this "
        "command; BACKUP_S3_BUCKET unset is a no-op."
    )

    def handle(self, *args, **options):
        bucket = os.environ.get("BACKUP_S3_BUCKET")
        if not bucket:
            self.stdout.write("backup_database: BACKUP_S3_BUCKET not set, skipping")
            return

        prefix = os.environ.get("BACKUP_S3_PREFIX", "gtd-backups/")
        db = settings.DATABASES["default"]
        timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        key = f"{prefix}gtd-{timestamp}.dump"

        with tempfile.TemporaryDirectory() as tmp_dir:
            dump_path = os.path.join(tmp_dir, "gtd.dump")
            self._run_pg_dump(db, dump_path)
            self._upload(bucket, key, dump_path)

        pruned = self._prune_old_backups(bucket, prefix)
        self.stdout.write(f"backup_database: uploaded {key} to s3://{bucket} ({pruned} old backup(s) pruned)")

    def _run_pg_dump(self, db, dump_path):
        env = os.environ.copy()
        if db.get("PASSWORD"):
            env["PGPASSWORD"] = db["PASSWORD"]
        cmd = [
            "pg_dump",
            "-Fc",  # custom format: compressed, supports selective/parallel restore
            "-h", db.get("HOST") or "localhost",
            "-p", str(db.get("PORT") or 5432),
            "-U", db.get("USER") or "",
            "-f", dump_path,
            db["NAME"],
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            event_id = self._log_failure("pg_dump", result.stderr)
            raise CommandError(f"pg_dump failed [event_id={event_id}]: {result.stderr}")

    def _upload(self, bucket, key, dump_path):
        import boto3

        try:
            boto3.client("s3").upload_file(dump_path, bucket, key)
        except Exception as exc:
            event_id = self._log_failure("s3 upload", str(exc))
            raise CommandError(f"S3 upload failed [event_id={event_id}]: {exc}") from exc

    def _prune_old_backups(self, bucket, prefix):
        import boto3

        s3 = boto3.client("s3")
        cutoff = datetime.now(dt_timezone.utc) - timedelta(days=BACKUP_RETENTION_DAYS)
        pruned = 0
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < cutoff:
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    pruned += 1
        return pruned

    def _log_failure(self, stage, detail):
        import uuid

        event_id = uuid.uuid4().hex[:12]
        logger.error("backup_database %s failed [event_id=%s]: %s", stage, event_id, detail)
        return event_id
