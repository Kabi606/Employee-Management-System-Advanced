from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.utils import timezone
from django.db.models import Count, Q
from .models import UserProfile, AuditLog, Notification, Office, Attendance


# ═══════════════════════════════════════════════════════════
# USER PROFILE — inline inside User admin
# ═══════════════════════════════════════════════════════════

class UserProfileInline(admin.StackedInline):
    model          = UserProfile
    can_delete     = False
    verbose_name   = "Profile"
    fields         = ("avatar", "phone", "bio")
    extra          = 0


class UserAdmin(BaseUserAdmin):
    inlines        = (UserProfileInline,)
    list_display   = ("username", "email", "get_full_name", "is_active", "is_staff", "is_superuser", "date_joined")
    list_filter    = ("is_active", "is_staff", "is_superuser", "groups")
    search_fields  = ("username", "email", "first_name", "last_name")
    ordering       = ("username",)
    list_per_page  = 30

    def get_full_name(self, obj):
        return obj.get_full_name() or "--"
    get_full_name.short_description = "Full Name"


# Re-register User with the extended admin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ═══════════════════════════════════════════════════════════
# USER PROFILE
# ═══════════════════════════════════════════════════════════

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display   = ("user", "phone", "created_at", "updated_at")
    search_fields  = ("user__username", "user__email", "phone")
    readonly_fields = ("created_at", "updated_at")
    list_per_page  = 30


# ═══════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display   = ("timestamp", "actor", "action_badge", "target_model", "target_repr", "ip_address")
    list_filter    = ("action", "target_model")
    search_fields  = ("actor__username", "target_repr", "detail", "ip_address")
    readonly_fields = ("actor", "action", "target_model", "target_id", "target_repr", "detail", "ip_address", "timestamp")
    ordering       = ("-timestamp",)
    list_per_page  = 50
    date_hierarchy = "timestamp"

    def action_badge(self, obj):
        colors = {
            "CREATE":           "#22c55e",
            "UPDATE":           "#4f7df3",
            "DELETE":           "#ef4444",
            "LOGIN":            "#0891b2",
            "LOGOUT":           "#94a3b8",
            "PASSWORD_CHANGE":  "#f59e0b",
            "PERMISSION_CHANGE":"#8b5cf6",
        }
        color = colors.get(obj.action, "#94a3b8")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">{}</span>',
            color, obj.action
        )
    action_badge.short_description = "Action"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ═══════════════════════════════════════════════════════════
# NOTIFICATION
# ═══════════════════════════════════════════════════════════

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display   = ("title", "recipient", "notif_type", "is_read", "created_at")
    list_filter    = ("is_read", "notif_type")
    search_fields  = ("title", "message", "recipient__username")
    readonly_fields = ("created_at",)
    ordering       = ("-created_at",)
    list_per_page  = 50
    actions        = ["mark_as_read", "mark_as_unread"]

    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} notification(s) marked as read.")
    mark_as_read.short_description = "Mark selected as read"

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f"{updated} notification(s) marked as unread.")
    mark_as_unread.short_description = "Mark selected as unread"


# ═══════════════════════════════════════════════════════════
# OFFICE
# ═══════════════════════════════════════════════════════════

@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display   = (
        "name", "address", "allowed_radius",
        "work_hours", "late_grace_minutes",
        "half_day_window", "is_active", "created_at"
    )
    list_filter    = ("is_active",)
    search_fields  = ("name", "address")
    readonly_fields = ("created_at",)
    ordering       = ("name",)
    list_per_page  = 20

    fieldsets = (
        ("Basic Info", {
            "fields": ("name", "address", "is_active")
        }),
        ("GPS Location", {
            "fields": ("latitude", "longitude", "allowed_radius"),
            "description": "Right-click on Google Maps to get coordinates."
        }),
        ("Working Hours", {
            "fields": ("work_start", "work_end")
        }),
        ("Attendance Rules", {
            "fields": ("late_grace_minutes", "half_day_start", "half_day_end"),
            "description": (
                "late_grace_minutes: minutes after work_start before marking Late. "
                "half_day_start/end: check-in within this window = Half Day."
            )
        }),
        ("Timestamps", {
            "fields": ("created_at",),
            "classes": ("collapse",)
        }),
    )

    def work_hours(self, obj):
        return format_html(
            '<span style="font-family:monospace;">{} &ndash; {}</span>',
            obj.work_start.strftime("%H:%M"),
            obj.work_end.strftime("%H:%M"),
        )
    work_hours.short_description = "Work Hours"

    def half_day_window(self, obj):
        return format_html(
            '<span style="font-family:monospace;">{} &ndash; {}</span>',
            obj.half_day_start.strftime("%H:%M"),
            obj.half_day_end.strftime("%H:%M"),
        )
    half_day_window.short_description = "Half Day Window"


# ═══════════════════════════════════════════════════════════
# ATTENDANCE
# ═══════════════════════════════════════════════════════════

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display   = (
        "employee", "date", "office",
        "check_in_fmt", "check_out_fmt", "get_hours_worked",
        "status_badge", "location_verified", "note_short"
    )
    list_filter    = ("status", "location_verified", "office", "date")
    search_fields  = ("employee__username", "employee__first_name", "employee__last_name", "note")
    readonly_fields = (
        "created_at", "updated_at",
        "check_in_lat", "check_in_lng",
        "check_out_lat", "check_out_lng",
        "location_verified",
    )
    ordering       = ("-date", "employee__username")
    date_hierarchy = "date"
    list_per_page  = 50
    actions        = ["mark_present", "mark_absent", "mark_leave", "mark_late", "mark_half"]

    fieldsets = (
        ("Employee & Date", {
            "fields": ("employee", "office", "date")
        }),
        ("Times", {
            "fields": ("check_in", "check_out", "status", "note")
        }),
        ("GPS Info", {
            "fields": (
                "location_verified",
                "check_in_lat", "check_in_lng",
                "check_out_lat", "check_out_lng",
            ),
            "classes": ("collapse",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    # ── Custom display columns ───────────────────────────

    def check_in_fmt(self, obj):
        if obj.check_in:
            val = obj.check_in.strftime("%H:%M")
            return format_html('<code>{}</code>', val)
        return "–"
    check_in_fmt.short_description = "Check In"

    def check_out_fmt(self, obj):
        if obj.check_out:
            val = obj.check_out.strftime("%H:%M")
            return format_html('<code>{}</code>', val)
        return "–"
    check_out_fmt.short_description = "Check Out"

    def status_badge(self, obj):
        colors = {
            "present": "#22c55e",
            "absent":  "#ef4444",
            "leave":   "#f59e0b",
            "half":    "#8b5cf6",
            "late":    "#0891b2",
        }
        color = colors.get(obj.status, "#94a3b8")
        label = obj.get_status_display()
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:20px;font-size:11px;font-weight:700;">{}</span>',
            color, label
        )
    status_badge.short_description = "Status"

    def note_short(self, obj):
        if obj.note:
            text = obj.note[:40] + ("..." if len(obj.note) > 40 else "")
            return text
        return "–"
    note_short.short_description = "Note"

    def get_hours_worked(self, obj):
        val = obj.hours_worked
        return val if val else "–"
    get_hours_worked.short_description = "Hours"

    # ── Bulk actions ─────────────────────────────────────

    def mark_present(self, request, queryset):
        updated = queryset.update(status="present")
        self.message_user(request, f"{updated} record(s) marked Present.")
    mark_present.short_description = "Mark selected as Present"

    def mark_absent(self, request, queryset):
        updated = queryset.update(status="absent")
        self.message_user(request, f"{updated} record(s) marked Absent.")
    mark_absent.short_description = "Mark selected as Absent"

    def mark_leave(self, request, queryset):
        updated = queryset.update(status="leave")
        self.message_user(request, f"{updated} record(s) marked Leave.")
    mark_leave.short_description = "Mark selected as Leave"

    def mark_late(self, request, queryset):
        updated = queryset.update(status="late")
        self.message_user(request, f"{updated} record(s) marked Late.")
    mark_late.short_description = "Mark selected as Late"

    def mark_half(self, request, queryset):
        updated = queryset.update(status="half")
        self.message_user(request, f"{updated} record(s) marked Half Day.")
    mark_half.short_description = "Mark selected as Half Day"

    # ── Optimise queries ─────────────────────────────────

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("employee", "office")


# ═══════════════════════════════════════════════════════════
# ADMIN SITE CUSTOMISATION
# ═══════════════════════════════════════════════════════════

admin.site.site_header  = "Doer Services PLC"
admin.site.site_title   = "Doer Services PLC"
admin.site.index_title  = "Welcom to Dashboard"