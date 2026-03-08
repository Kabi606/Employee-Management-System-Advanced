"""
mixins.py — Reusable CBV Mixins
- AuditLogMixin:    auto-logs create/update/delete AND fires notifications
- RoleRequiredMixin: restrict views to users with a specific Group
- OwnerOrAdminMixin: allow only object owner or staff
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect
from .models import AuditLog, Notification


# ─────────────────────────────────────────
# AUDIT LOG MIXIN
# ─────────────────────────────────────────

# Maps model class name → notification type
_NOTIF_TYPE_MAP = {
    ("User",    "CREATE"): ("user_created",   "New user created"),
    ("User",    "UPDATE"): ("user_updated",   "User updated"),
    ("User",    "DELETE"): ("user_deleted",   "User deleted"),
    ("Group",   "CREATE"): ("group_created",  "Group created"),
    ("Group",   "UPDATE"): ("user_updated",   "Group updated"),
    ("Group",   "DELETE"): ("group_deleted",  "Group deleted"),
}


class AuditLogMixin:
    """
    Add to any CreateView / UpdateView / DeleteView.
    Set audit_action = "CREATE" | "UPDATE" | "DELETE" on the view class.
    Automatically fires AuditLog + Notification for every action.
    """
    audit_action: str = ""

    def form_valid(self, form):
        response = super().form_valid(form)
        obj = self.object if hasattr(self, "object") else None
        detail = self._audit_detail(obj)

        # ── Audit log ──
        AuditLog.log(
            request=self.request,
            action=self.audit_action,
            target_obj=obj,
            detail=detail,
        )

        # ── Notification ──
        model_name = obj.__class__.__name__ if obj else ""
        key = (model_name, self.audit_action)
        notif_type, notif_verb = _NOTIF_TYPE_MAP.get(key, ("user_updated", "Action performed"))

        Notification.notify_admins(
            notif_type=notif_type,
            title=f"{notif_verb} — '{obj}'",
            message=detail,
        )

        return response

    def _audit_detail(self, obj):
        return f"{self.audit_action} {obj.__class__.__name__}: {obj}"


class AuditDeleteMixin:
    """Mixin for DeleteView — logs before deletion so we still have the repr."""
    audit_action: str = "DELETE"

    def form_valid(self, form):
        obj = self.get_object()
        model_name = obj.__class__.__name__
        detail = f"Deleted {model_name}: {obj}"

        # ── Audit log ──
        AuditLog.log(self.request, self.audit_action, target_obj=obj, detail=detail)

        # ── Notification ──
        key = (model_name, "DELETE")
        notif_type, notif_verb = _NOTIF_TYPE_MAP.get(key, ("user_deleted", "Item deleted"))

        Notification.notify_admins(
            notif_type=notif_type,
            title=f"{notif_verb} — '{obj}'",
            message=detail,
        )

        return super().form_valid(form)


# ─────────────────────────────────────────
# ROLE REQUIRED MIXIN
# ─────────────────────────────────────────

class RoleRequiredMixin(LoginRequiredMixin):
    """
    Restrict a view to users who belong to one of the required_roles groups.
    Usage:
        class MyView(RoleRequiredMixin, View):
            required_roles = ["Managers", "Admins"]
    """
    required_roles: list = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        user_groups = set(request.user.groups.values_list("name", flat=True))
        allowed = set(self.required_roles)
        if not (user_groups & allowed) and not request.user.is_superuser:
            messages.error(request, "You do not have permission to access this page.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


# ─────────────────────────────────────────
# OWNER OR ADMIN MIXIN
# ─────────────────────────────────────────

class OwnerOrAdminMixin(LoginRequiredMixin):
    """
    Allows access only if request.user == object.user OR user is staff/superuser.
    """
    owner_field: str = "user"

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        owner = getattr(obj, self.owner_field, None)
        if owner != request.user and not request.user.is_staff:
            messages.error(request, "You can only edit your own data.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)