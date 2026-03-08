"""
management command: auto_checkout
----------------------------------
Run this daily at end of work day (e.g. via cron or celery beat).

Does TWO things in one pass:
  1. AUTO CHECKOUT  — employees who checked in but forgot to check out
                      get check_out = office.work_end
  2. MARK ABSENT    — employees who never checked in at all
                      get a new Attendance record with status = "absent"

Cron example (runs at 11:59 PM every day):
  59 23 * * * /path/to/env/bin/python /path/to/manage.py auto_checkout

Usage:
  python manage.py auto_checkout
  python manage.py auto_checkout --date 2026-03-07
  python manage.py auto_checkout --dry-run
  python manage.py auto_checkout --skip-absent     (only do auto checkout)
  python manage.py auto_checkout --skip-checkout   (only mark absent)
"""
from django.core.management.base import BaseCommand
from datetime import date as date_cls


class Command(BaseCommand):
    help = "Auto check-out employees who forgot to check out + mark no-shows as Absent"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Date to process (YYYY-MM-DD). Defaults to today.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without saving anything.",
        )
        parser.add_argument(
            "--skip-absent",
            action="store_true",
            help="Skip marking absent — only run auto checkout.",
        )
        parser.add_argument(
            "--skip-checkout",
            action="store_true",
            help="Skip auto checkout — only mark absent.",
        )

    def handle(self, *args, **options):
        from django.contrib.auth.models import User
        from account.models import Attendance

        # Resolve date
        if options["date"]:
            from datetime import datetime
            target_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            target_date = date_cls.today()

        dry_run       = options["dry_run"]
        skip_absent   = options["skip_absent"]
        skip_checkout = options["skip_checkout"]

        self.stdout.write(self.style.HTTP_INFO(
            f"\n=== auto_checkout running for {target_date}"
            + (" [DRY RUN]" if dry_run else "") + " ==="
        ))

        # ── STEP 1: Auto Checkout ────────────────────────────────────────
        checkout_count = 0
        if not skip_checkout:
            self.stdout.write("\n[1/2] Auto Checkout — employees with no check-out...")

            records = Attendance.objects.filter(
                date=target_date,
                check_in__isnull=False,
                check_out__isnull=True,
                office__isnull=False,
            ).select_related("employee", "office")

            if not records.exists():
                self.stdout.write("      No pending checkouts.")
            else:
                for record in records:
                    work_end = record.office.work_end
                    if dry_run:
                        self.stdout.write(
                            f"      [DRY RUN] {record.employee.username} "
                            f"-> check_out = {work_end} ({record.office.name})"
                        )
                    else:
                        record.check_out = work_end
                        record.note = (
                            (record.note or "") + " | Auto checked-out at office closing time"
                        ).strip(" | ")
                        record.save(update_fields=["check_out", "note", "updated_at"])
                        self.stdout.write(
                            f"      Checked-out: {record.employee.username} "
                            f"at {work_end} ({record.office.name})"
                        )
                    checkout_count += 1

        # ── STEP 2: Mark Absent ──────────────────────────────────────────
        absent_created = 0
        absent_updated = 0
        if not skip_absent:
            self.stdout.write("\n[2/2] Mark Absent — employees who never checked in...")

            employees = User.objects.filter(is_active=True)

            for employee in employees:
                try:
                    record = Attendance.objects.get(employee=employee, date=target_date)
                    # Record exists but check_in is empty — mark absent
                    if not record.check_in and record.status != "absent":
                        if dry_run:
                            self.stdout.write(
                                f"      [DRY RUN] {employee.username} -> absent (record exists, no check-in)"
                            )
                        else:
                            record.status = "absent"
                            record.note = (
                                (record.note or "") + " | Auto marked absent - no check-in"
                            ).strip(" | ")
                            record.save(update_fields=["status", "note", "updated_at"])
                            self.stdout.write(f"      Absent (updated): {employee.username}")
                        absent_updated += 1

                except Attendance.DoesNotExist:
                    # No record at all — create absent
                    if dry_run:
                        self.stdout.write(
                            f"      [DRY RUN] {employee.username} -> absent (no record)"
                        )
                    else:
                        Attendance.objects.create(
                            employee=employee,
                            date=target_date,
                            status="absent",
                            note="Auto marked absent - did not check in",
                        )
                        self.stdout.write(f"      Absent (created): {employee.username}")
                    absent_created += 1

        # ── Summary ──────────────────────────────────────────────────────
        style = self.style.WARNING if dry_run else self.style.SUCCESS
        self.stdout.write(style(
            f"\n=== Done ==="
            f"\n    Auto checkouts : {checkout_count}"
            f"\n    Absent created : {absent_created}"
            f"\n    Absent updated : {absent_updated}"
            + ("\n    (dry run — nothing saved)" if dry_run else "")
        ))