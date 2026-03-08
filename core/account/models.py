"""
models.py — Advanced Auth Models
- UserProfile: extends User with avatar, bio, phone
- AuditLog: tracks every create/edit/delete action
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import os


def avatar_upload_path(instance, filename):
    import time
    ext = filename.rsplit(".", 1)[-1].lower()
    # Timestamp ensures re-uploads never serve a stale cached file
    return f"avatars/user_{instance.user.id}_{int(time.time())}.{ext}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to=avatar_upload_path, null=True, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.username}"

    @property
    def avatar_url(self):
        if self.avatar:
            return self.avatar.url
        return "/static/account/img/default_avatar.png"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("CREATE", "Created"),
        ("UPDATE", "Updated"),
        ("DELETE", "Deleted"),
        ("LOGIN",  "Logged In"),
        ("LOGOUT", "Logged Out"),
        ("PASSWORD_CHANGE", "Password Changed"),
        ("PERMISSION_CHANGE", "Permission Changed"),
    ]

    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name="audit_actions"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_model = models.CharField(max_length=50, blank=True)   # e.g. "User", "Group"
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target_repr = models.CharField(max_length=200, blank=True)   # e.g. "john_doe"
    detail = models.TextField(blank=True)                         # extra context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.actor} → {self.action} {self.target_model}"

    @classmethod
    def log(cls, request, action, target_obj=None, detail=""):
        """Convenience factory method."""
        actor = request.user if request.user.is_authenticated else None
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() \
             or request.META.get("REMOTE_ADDR")
        cls.objects.create(
            actor=actor,
            action=action,
            target_model=target_obj.__class__.__name__ if target_obj else "",
            target_id=target_obj.pk if target_obj else None,
            target_repr=str(target_obj) if target_obj else "",
            detail=detail,
            ip_address=ip or None,
        )


class Notification(models.Model):
    NOTIF_TYPES = [
        ("user_created",        "New user created"),
        ("user_updated",        "User updated"),
        ("user_deleted",        "User deleted"),
        ("password_changed",    "Password changed"),
        ("permission_changed",  "Permission changed"),
        ("login_failed",        "Failed login attempt"),
        ("group_created",       "Group created"),
        ("group_deleted",       "Group deleted"),
        ("profile_updated",     "Profile updated"),
    ]

    recipient   = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    notif_type  = models.CharField(max_length=30, choices=NOTIF_TYPES)
    title       = models.CharField(max_length=200)
    message     = models.TextField(blank=True)
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(default=timezone.now)
    # Optional link to related audit log entry
    audit_log   = models.ForeignKey(
        AuditLog, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="notifications"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.notif_type}] → {self.recipient.username}"

    @classmethod
    def notify_admins(cls, notif_type, title, message="", audit_log=None):
        """Send notification to all active superusers."""
        from django.db.models import Q
        admins = User.objects.filter(
            Q(is_staff=True) | Q(is_superuser=True), is_active=True
        ).distinct()
        notifications = [
            cls(
                recipient=admin,
                notif_type=notif_type,
                title=title,
                message=message,
                audit_log=audit_log,
            )
            for admin in admins
        ]
        cls.objects.bulk_create(notifications)

    @classmethod
    def notify_user(cls, user, notif_type, title, message="", audit_log=None):
        """Send notification to a specific user."""
        cls.objects.create(
            recipient=user,
            notif_type=notif_type,
            title=title,
            message=message,
            audit_log=audit_log,
        )


# ─────────────────────────────────────────────────────────
# OFFICE LOCATIONS
# ─────────────────────────────────────────────────────────

class Office(models.Model):
    name           = models.CharField(max_length=100)
    address        = models.CharField(max_length=255, blank=True)
    latitude       = models.DecimalField(max_digits=10, decimal_places=7)
    longitude      = models.DecimalField(max_digits=10, decimal_places=7)
    allowed_radius = models.PositiveIntegerField(
        default=100,
        help_text="Allowed radius in meters. Employees must be within this distance to check in."
    )
    # ── Work Hours ──────────────────────────────────────────
    work_start = models.TimeField(
        default="09:00",
        help_text="Office opening time. e.g. 09:00"
    )
    work_end = models.TimeField(
        default="17:00",
        help_text="Office closing time. e.g. 17:00. Used as default check-out if employee forgets."
    )
    late_grace_minutes = models.PositiveIntegerField(
        default=15,
        help_text="Minutes after work_start before employee is marked Late. e.g. 15 means 09:01-09:15 = Late."
    )
    half_day_start = models.TimeField(
        default="12:00",
        help_text="Half day window start. Check-in at or after this time = Half Day."
    )
    half_day_end = models.TimeField(
        default="15:00",
        help_text="Half day window end. Check-in after this time = Absent (too late even for half day)."
    )
    # ────────────────────────────────────────────────────────
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name        = "Office"
        verbose_name_plural = "Offices"

    def __str__(self):
        return self.name

    def auto_status(self, check_in_time):
        """
        Given a check-in time, return the correct attendance status.

        Timeline:
          work_start                    → Present on or before
          work_start + grace_minutes    → Late window ends
          half_day_start                → Half Day window begins
          half_day_end                  → After this = Absent (too late)

        Example with 09:00 start, 15min grace, half 12:00-15:00:
          before 09:00  → present
          09:01 - 09:15 → late
          09:16 - 11:59 → late
          12:00 - 15:00 → half
          after  15:00  → absent
        """
        from datetime import datetime, timedelta
        grace_cutoff = (
            datetime.combine(datetime.today(), self.work_start)
            + timedelta(minutes=self.late_grace_minutes)
        ).time()

        if check_in_time <= self.work_start:
            return "present"
        elif check_in_time <= grace_cutoff:
            return "late"
        elif check_in_time < self.half_day_start:
            return "late"
        elif check_in_time <= self.half_day_end:
            return "half"
        else:
            return "absent"

    def distance_to(self, lat, lng):
        """
        Haversine formula — returns distance in meters between
        office location and given lat/lng coordinates.
        """
        import math
        R = 6371000  # Earth radius in metres
        lat1 = math.radians(float(self.latitude))
        lat2 = math.radians(float(lat))
        dlat = math.radians(float(lat) - float(self.latitude))
        dlng = math.radians(float(lng) - float(self.longitude))
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def is_within_radius(self, lat, lng):
        return self.distance_to(lat, lng) <= self.allowed_radius


# ─────────────────────────────────────────────────────────
# ATTENDANCE
# ─────────────────────────────────────────────────────────

class Attendance(models.Model):
    STATUS_CHOICES = [
        ("present", "Present"),
        ("absent",  "Absent"),
        ("leave",   "Leave"),
        ("half",    "Half Day"),
        ("late",    "Late"),
    ]

    employee   = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="attendances"
    )
    office     = models.ForeignKey(
        Office, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="attendances",
        help_text="Which office the employee checked in from"
    )
    date       = models.DateField()
    check_in   = models.TimeField(null=True, blank=True)
    check_out  = models.TimeField(null=True, blank=True)
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default="present")
    note       = models.CharField(max_length=255, blank=True)
    # GPS fields — captured at check-in time
    check_in_lat  = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    check_in_lng  = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    check_out_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    check_out_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_verified = models.BooleanField(
        default=False,
        help_text="True if employee was within allowed radius when checking in"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ["-date", "employee__username"]
        unique_together     = ("employee", "date")
        verbose_name        = "Attendance"
        verbose_name_plural = "Attendances"

    def __str__(self):
        return f"{self.employee.username} — {self.date} ({self.get_status_display()})"

    @property
    def hours_worked(self):
        if self.check_in and self.check_out:
            from datetime import datetime, date
            ci = datetime.combine(date.today(), self.check_in)
            co = datetime.combine(date.today(), self.check_out)
            diff = co - ci
            if diff.total_seconds() > 0:
                total_seconds = int(diff.total_seconds())

                # If half day, cap hours at half_day window length
                if self.status == "half" and self.office:
                    from datetime import timedelta
                    window_start = datetime.combine(date.today(), self.office.half_day_start)
                    window_end   = datetime.combine(date.today(), self.office.half_day_end)
                    cap_seconds  = int((window_end - window_start).total_seconds())
                    if cap_seconds > 0:
                        total_seconds = min(total_seconds, cap_seconds)

                h, rem = divmod(total_seconds, 3600)
                m = rem // 60
                return f"{h}h {m:02d}m"
        return "--"


# ─────────────────────────────────────────────────────────
# LEAVE MANAGEMENT
# ─────────────────────────────────────────────────────────

class LeaveType(models.Model):
    name        = models.CharField(max_length=50, unique=True)  # Sick, Casual, Annual
    description = models.TextField(blank=True)
    max_days    = models.PositiveIntegerField(
        default=15,
        help_text="Maximum days allowed per year for this leave type"
    )
    color       = models.CharField(
        max_length=7, default="#4f7df3",
        help_text="Hex color for display e.g. #ef4444"
    )
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveBalance(models.Model):
    employee    = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="leave_balances"
    )
    leave_type  = models.ForeignKey(
        LeaveType, on_delete=models.CASCADE, related_name="balances"
    )
    year        = models.PositiveIntegerField()
    total_days  = models.PositiveIntegerField(default=0)
    used_days   = models.DecimalField(max_digits=5, decimal_places=1, default=0)

    class Meta:
        unique_together = ("employee", "leave_type", "year")
        ordering        = ["-year", "employee__username"]

    def __str__(self):
        return f"{self.employee.username} — {self.leave_type.name} {self.year}"

    @property
    def remaining_days(self):
        return max(0, self.total_days - float(self.used_days))


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ("pending",  "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled","Cancelled"),
    ]

    employee    = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="leave_requests"
    )
    leave_type  = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="requests"
    )
    start_date  = models.DateField()
    end_date    = models.DateField()
    total_days  = models.DecimalField(max_digits=5, decimal_places=1, default=1)
    reason      = models.TextField(blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_leaves"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.username} — {self.leave_type.name} ({self.start_date} to {self.end_date})"

    def save(self, *args, **kwargs):
        # Auto-calculate total_days
        if self.start_date and self.end_date:
            delta = (self.end_date - self.start_date).days + 1
            self.total_days = max(1, delta)
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────
# NOTICE / ANNOUNCEMENT
# ─────────────────────────────────────────────────────────

class Notice(models.Model):
    PRIORITY_CHOICES = [
        ("normal",  "Normal"),
        ("important","Important"),
        ("urgent",  "Urgent"),
    ]

    title       = models.CharField(max_length=200)
    content     = models.TextField()
    priority    = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="normal"
    )
    posted_by   = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, related_name="notices"
    )
    # Target audience — empty means all employees
    target_users = models.ManyToManyField(
        User, blank=True, related_name="targeted_notices",
        help_text="Leave empty to send to all employees"
    )
    is_active   = models.BooleanField(default=True)
    is_pinned   = models.BooleanField(default=False)
    publish_at  = models.DateTimeField(default=timezone.now)
    expires_at  = models.DateTimeField(
        null=True, blank=True,
        help_text="Leave blank to never expire"
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-publish_at"]

    def __str__(self):
        return self.title

    @property
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @property
    def audience_label(self):
        count = self.target_users.count()
        return f"{count} specific employee(s)" if count else "All Employees"