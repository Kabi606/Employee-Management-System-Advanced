"""
views.py — Advanced Django Auth (CBV Edition)
Features:
  ✅ Class-Based Views (ListView, CreateView, UpdateView, DeleteView)
  ✅ ModelForms with full validation (no raw request.POST)
  ✅ RBAC: PermissionRequiredMixin + RoleRequiredMixin
  ✅ User Profile with avatar upload
  ✅ Audit log on every create / update / delete / password change
  ✅ Login / Logout with session management
  ✅ Group permission management
"""

from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.db.models import Q
from django.utils import timezone
from django.http import JsonResponse
from django.http import HttpResponse, Http404
from django.views.generic import (
    ListView, CreateView, UpdateView, DeleteView, View, DetailView, TemplateView
)

from .forms import UserCreateForm, UserEditForm, UserProfileForm, GroupForm, AttendanceForm, OfficeForm
from .models import UserProfile, AuditLog, Notification, Attendance, Office, LeaveType, LeaveBalance, LeaveRequest, Notice
from .mixins import AuditLogMixin, AuditDeleteMixin, RoleRequiredMixin
from datetime import date, timedelta, datetime as dt
import calendar
import json
import csv
import io

# Excel
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# PDF
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# ═══════════════════════════════════════════
# AUTH — Login / Logout
# ═══════════════════════════════════════════

class LoginView(View):
    """
    Session-based login. Uses Django's built-in AuthenticationForm.
    Signals in signals.py handle audit logging automatically.
    """
    template_name = "account/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return render(request, self.template_name, {"form": AuthenticationForm()})

    def post(self, request):
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.GET.get("next", "dashboard")
            return redirect(next_url)
        messages.error(request, "Invalid username or password.")
        return render(request, self.template_name, {"form": form})


class LogoutView(LoginRequiredMixin, View):
    """POST-only logout for CSRF safety."""
    def post(self, request):
        logout(request)
        messages.success(request, "You have been logged out.")
        return redirect("login")


# ═══════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════

@login_required
def dashboard(request):
    from .models import Notification
    context = {
        "total_users":   User.objects.count(),
        "total_groups":  Group.objects.count(),
        "recent_logs":   AuditLog.objects.select_related("actor")[:10],
        # Pass notification count directly as fallback
        # (in case context processor isn't registered yet)
        "notif_unread_count": Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count() if request.user.is_authenticated else 0,
    }
    return render(request, "dashboard/dashboard.html", context)


# ═══════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════

class UserListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = User
    template_name = "account/user_list.html"
    context_object_name = "users"
    permission_required = "auth.view_user"
    paginate_by = 20
    ordering = ["username"]

    def get_queryset(self):
        qs = super().get_queryset()
        q      = self.request.GET.get("q",      "").strip()
        role   = self.request.GET.get("role",   "").strip()
        status = self.request.GET.get("status", "").strip()

        if q:
            qs = qs.filter(
                Q(username__icontains=q)   |
                Q(email__icontains=q)      |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q)
            )

        if role == "no_role":
            qs = qs.filter(groups__isnull=True)
        elif role:
            qs = qs.filter(groups__id=role)

        if status == "active":
            qs = qs.filter(is_active=True, is_superuser=False)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        elif status == "superuser":
            qs = qs.filter(is_superuser=True)

        return qs.prefetch_related("groups", "profile").distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["all_groups"]      = Group.objects.order_by("name")
        ctx["selected_role"]   = self.request.GET.get("role",   "")
        ctx["selected_status"] = self.request.GET.get("status", "")
        ctx["active_count"]    = User.objects.filter(is_active=True).count()
        ctx["inactive_count"]  = User.objects.filter(is_active=False).count()
        return ctx


class UserCreateView(LoginRequiredMixin, PermissionRequiredMixin, AuditLogMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "account/user_form.html"
    permission_required = "auth.add_user"
    success_url = reverse_lazy("user_list")
    audit_action = "CREATE"

    def form_valid(self, form):
        messages.success(self.request, f"User '{form.cleaned_data['username']}' created.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please fix the errors below.")
        return super().form_invalid(form)


class UserEditView(LoginRequiredMixin, PermissionRequiredMixin, AuditLogMixin, UpdateView):
    model = User
    form_class = UserEditForm
    template_name = "account/user_edit.html"
    permission_required = "auth.change_user"
    success_url = reverse_lazy("user_list")
    pk_url_kwarg = "id"
    audit_action = "UPDATE"

    def get_form_kwargs(self):
        # Ensure the form is always bound to the existing User instance
        # so all fields (username, email, etc.) are pre-populated on GET
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_object()
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f"User '{form.instance.username}' updated successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please fix the errors below.")
        return super().form_invalid(form)


class UserDeleteView(LoginRequiredMixin, PermissionRequiredMixin, AuditDeleteMixin, DeleteView):
    model = User
    template_name = "account/user_confirm_delete.html"
    permission_required = "auth.delete_user"
    success_url = reverse_lazy("user_list")
    pk_url_kwarg = "id"

    def form_valid(self, form):
        messages.success(self.request, "User deleted.")
        return super().form_valid(form)


class UserBulkDeleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "auth.delete_user"

    def post(self, request):
        ids = request.POST.getlist("selected_users")
        if ids:
            users = User.objects.filter(id__in=ids)
            count = users.count()
            usernames = list(users.values_list('username', flat=True))
            for u in users:
                AuditLog.log(request, "DELETE", target_obj=u, detail=f"Bulk deleted user '{u.username}'")
            users.delete()
            Notification.notify_admins(
                notif_type="user_deleted",
                title=f"{count} user(s) bulk deleted",
                message=f"Deleted: {', '.join(usernames)}",
            )
            messages.success(request, f"{count} user(s) deleted.")
        else:
            messages.warning(request, "No users selected.")
        return redirect("user_list")


class UserChangePasswordView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "auth.change_user"
    template_name = "account/change_password.html"

    def get(self, request, id):
        user = get_object_or_404(User, id=id)
        return render(request, self.template_name, {"form": SetPasswordForm(user), "target_user": user})

    def post(self, request, id):
        user = get_object_or_404(User, id=id)
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, user)
            AuditLog.log(request, "PASSWORD_CHANGE", target_obj=user,
                         detail=f"Password changed for '{user.username}' by '{request.user.username}'")
            Notification.notify_admins(
                notif_type="password_changed",
                title=f"Password changed — '{user.username}'",
                message=f"Password was changed for '{user.username}' by '{request.user.username}'.",
            )
            messages.success(request, f"Password updated for '{user.username}'.")
            return redirect("user_list")
        messages.error(request, "Please fix the errors below.")
        return render(request, self.template_name, {"form": form, "target_user": user})


# ═══════════════════════════════════════════
# USER PROFILE
# ═══════════════════════════════════════════

class UserProfileView(LoginRequiredMixin, View):
    """View and edit your own profile + avatar."""
    template_name = "account/profile.html"

    def _get_profile(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    def get(self, request, id=None):
        # Admins can view anyone's profile; others only their own
        if id and request.user.has_perm("auth.change_user"):
            user = get_object_or_404(User, id=id)
        else:
            user = request.user
        profile = self._get_profile(user)
        form = UserProfileForm(instance=profile)
        return render(request, self.template_name, {"form": form, "profile": profile, "target_user": user})

    def post(self, request, id=None):
        if id and request.user.has_perm("auth.change_user"):
            user = get_object_or_404(User, id=id)
        else:
            user = request.user
        profile = self._get_profile(user)
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            AuditLog.log(request, "UPDATE", target_obj=profile,
                         detail=f"Profile updated for '{user.username}'")
            Notification.notify_admins(
                notif_type="profile_updated",
                title=f"Profile updated — '{user.username}'",
                message=f"'{user.username}' updated their profile.",
            )
            # Also notify the user themselves
            Notification.notify_user(
                user=user,
                notif_type="profile_updated",
                title="Your profile was updated",
                message="Your profile information has been saved successfully.",
            )
            messages.success(request, "Profile updated successfully.")
            return redirect("user_profile")
        messages.error(request, "Please fix the errors below.")
        return render(request, self.template_name, {"form": form, "profile": profile, "target_user": user})


# ═══════════════════════════════════════════
# GROUPS
# ═══════════════════════════════════════════

class GroupListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Group
    template_name = "account/group_list.html"
    context_object_name = "groups"
    permission_required = "auth.view_group"

    def get_queryset(self):
        # Order in get_queryset — avoids conflict between class-level ordering and prefetch_related
        return Group.objects.prefetch_related("permissions").order_by("name")


class GroupCreateView(LoginRequiredMixin, PermissionRequiredMixin, AuditLogMixin, CreateView):
    model = Group
    form_class = GroupForm
    template_name = "account/group_form.html"
    permission_required = "auth.add_group"
    success_url = reverse_lazy("group_list")
    audit_action = "CREATE"

    def form_valid(self, form):
        messages.success(self.request, f"Group '{form.cleaned_data['name']}' created.")
        return super().form_valid(form)


class GroupEditView(LoginRequiredMixin, PermissionRequiredMixin, AuditLogMixin, UpdateView):
    model = Group
    form_class = GroupForm
    template_name = "account/group_form.html"
    permission_required = "auth.change_group"
    success_url = reverse_lazy("group_list")
    pk_url_kwarg = "id"
    audit_action = "UPDATE"

    def form_valid(self, form):
        messages.success(self.request, f"Group '{self.object.name}' updated.")
        return super().form_valid(form)


class GroupDeleteView(LoginRequiredMixin, PermissionRequiredMixin, AuditDeleteMixin, DeleteView):
    model = Group
    template_name = "account/group_confirm_delete.html"
    permission_required = "auth.delete_group"
    success_url = reverse_lazy("group_list")
    pk_url_kwarg = "id"

    def form_valid(self, form):
        messages.success(self.request, "Group deleted.")
        return super().form_valid(form)


class GroupBulkDeleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "auth.delete_group"

    def post(self, request):
        ids = request.POST.getlist("ids")
        if ids:
            groups = Group.objects.filter(id__in=ids)
            count = groups.count()
            names = list(groups.values_list('name', flat=True))
            for g in groups:
                AuditLog.log(request, "DELETE", target_obj=g, detail=f"Bulk deleted group '{g.name}'")
            groups.delete()
            Notification.notify_admins(
                notif_type="group_deleted",
                title=f"{count} group(s) bulk deleted",
                message=f"Deleted: {', '.join(names)}",
            )
            messages.success(request, f"{count} group(s) deleted.")
        else:
            messages.warning(request, "No groups selected.")
        return redirect("group_list")


# ═══════════════════════════════════════════
# PERMISSIONS
# ═══════════════════════════════════════════

class GroupPermissionListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Group
    template_name = "account/group_permission_list.html"
    context_object_name = "groups"
    permission_required = "auth.change_group"


class GroupPermissionEditView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "auth.change_group"
    template_name = "account/group_permission_edit.html"

    def _sidebar_grouped_permissions(self):
        """
        Reads sidebar items from sidebar_config.py — fully dynamic.
        Add a new item to SIDEBAR_ITEMS and it appears here automatically.
        """
        from .sidebar_config import SIDEBAR_ITEMS, ICON_PATHS

        all_perms = list(
            Permission.objects.select_related("content_type")
            .order_by("content_type__model", "codename")
        )

        # Collect all model names assigned to sidebar items
        assigned_models = set(
            m for item in SIDEBAR_ITEMS for m in item.get("models", [])
        )

        # Build buckets per sidebar item name
        buckets = {item["name"]: [] for item in SIDEBAR_ITEMS}
        buckets["Other"] = []

        for perm in all_perms:
            model = perm.content_type.model.lower()
            placed = False
            for item in SIDEBAR_ITEMS:
                if model in item.get("models", []):
                    buckets[item["name"]].append(perm)
                    placed = True
                    break
            if not placed:
                buckets["Other"].append(perm)

        # Build result — skip items with no permissions
        result = []
        for item in SIDEBAR_ITEMS:
            perms = buckets[item["name"]]
            if perms:
                result.append({
                    "name":     item["name"],
                    "icon":     item.get("icon", "other"),
                    "iconpath": ICON_PATHS.get(item.get("icon", "other"), ICON_PATHS["other"]),
                    "perms":    perms,
                    "total":    len(perms),
                })

        # Add catch-all "Other" section if needed
        other_perms = buckets["Other"]
        if other_perms:
            result.append({
                "name":     "Other",
                "icon":     "other",
                "iconpath": ICON_PATHS["other"],
                "perms":    other_perms,
                "total":    len(other_perms),
            })

        return result


    def get(self, request, group_id):
        group = get_object_or_404(Group, id=group_id)
        return render(request, self.template_name, {
            "group":            group,
            "sidebar_sections": self._sidebar_grouped_permissions(),
            "group_permissions": set(group.permissions.values_list("id", flat=True)),
        })

    def post(self, request, group_id):
        group = get_object_or_404(Group, id=group_id)
        selected = request.POST.getlist("permissions")
        old_perms = set(group.permissions.values_list("codename", flat=True))
        group.permissions.set(selected)   # selected = list of permission IDs
        new_perms = set(group.permissions.values_list("codename", flat=True))
        AuditLog.log(request, "PERMISSION_CHANGE", target_obj=group,
                     detail=f"Permissions changed for '{group.name}'. "
                            f"Added: {new_perms - old_perms}, Removed: {old_perms - new_perms}")
        Notification.notify_admins(
            notif_type="permission_changed",
            title=f"Permissions changed — '{group.name}'",
            message=f"Added: {new_perms - old_perms} | Removed: {old_perms - new_perms}",
        )
        messages.success(request, f"Permissions updated for '{group.name}'.")
        return redirect("group_permission_list")


# ═══════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════

class AuditLogListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """View the audit trail — admin eyes only."""
    model = AuditLog
    template_name = "account/audit_log.html"
    context_object_name = "logs"
    permission_required = "auth.view_user"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        action = self.request.GET.get("action")
        actor = self.request.GET.get("actor")
        if action:
            qs = qs.filter(action=action)
        if actor:
            qs = qs.filter(actor__username__icontains=actor)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action_choices"] = AuditLog.ACTION_CHOICES
        return ctx


# ═══════════════════════════════════════════════════════════
# ATTENDANCE VIEWS
# ═══════════════════════════════════════════════════════════



class AttendanceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model               = Attendance
    template_name       = "attendance/attendance_list.html"
    context_object_name = "records"
    permission_required = "account.view_attendance"
    paginate_by         = 30

    def get_queryset(self):
        qs    = Attendance.objects.select_related("employee", "office").all()
        today = date.today()

        q         = self.request.GET.get("q",      "").strip()
        status    = self.request.GET.get("status", "").strip()
        view_mode = self.request.GET.get("view",   "today")
        date_from = self.request.GET.get("from",   "").strip()
        date_to   = self.request.GET.get("to",     "").strip()
        month     = self.request.GET.get("month",  "").strip()
        year_str  = self.request.GET.get("year",   "").strip()

        if view_mode == "today":
            qs = qs.filter(date=today)
        elif view_mode == "week":
            week_start = today - timedelta(days=today.weekday())
            week_end   = week_start + timedelta(days=6)
            qs = qs.filter(date__gte=week_start, date__lte=week_end)
        elif view_mode == "month":
            m = int(month) if month else today.month
            y = int(year_str) if year_str else today.year
            qs = qs.filter(date__month=m, date__year=y)
        elif view_mode == "custom":
            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)

        if q:
            qs = qs.filter(
                Q(employee__username__icontains=q)   |
                Q(employee__first_name__icontains=q) |
                Q(employee__last_name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)

        return qs.order_by("-date", "employee__username")

    def get_context_data(self, **kwargs):
        ctx   = super().get_context_data(**kwargs)
        today = date.today()
        view_mode  = self.request.GET.get("view", "today")
        week_start = today - timedelta(days=today.weekday())
        week_end   = week_start + timedelta(days=6)

        ctx["today"]           = today
        ctx["view_mode"]       = view_mode
        ctx["week_start"]      = week_start
        ctx["week_end"]        = week_end
        ctx["month_choices"]   = [(i, calendar.month_name[i]) for i in range(1, 13)]
        ctx["current_month"]   = self.request.GET.get("month",  str(today.month))
        ctx["current_year"]    = self.request.GET.get("year",   str(today.year))
        ctx["selected_status"] = self.request.GET.get("status", "")
        ctx["year_range"]      = range(today.year - 3, today.year + 1)
        ctx["date_from"]       = self.request.GET.get("from", "")
        ctx["date_to"]         = self.request.GET.get("to",   "")
        qs = self.get_queryset()
        ctx["count_present"] = qs.filter(status="present").count()
        ctx["count_absent"]  = qs.filter(status="absent").count()
        ctx["count_leave"]   = qs.filter(status="leave").count()
        ctx["count_half"]    = qs.filter(status="half").count()
        ctx["count_late"]    = qs.filter(status="late").count()
        ctx["count_total"]   = qs.count()

        # Today's summary — always shown regardless of filter
        today_qs = Attendance.objects.filter(date=today)
        ctx["today_present"] = today_qs.filter(status="present").count()
        ctx["today_absent"]  = today_qs.filter(status="absent").count()
        ctx["today_leave"]   = today_qs.filter(status="leave").count()
        ctx["today_half"]    = today_qs.filter(status="half").count()
        ctx["today_late"]    = today_qs.filter(status="late").count()
        ctx["today_total"]   = today_qs.count()
        return ctx


class AttendanceCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model               = Attendance
    form_class          = AttendanceForm
    template_name       = "attendance/attendance_form.html"
    permission_required = "account.add_attendance"
    success_url         = reverse_lazy("attendance_list")

    def get_initial(self):
        return {"date": date.today()}

    def form_valid(self, form):
        AuditLog.log(self.request, "CREATE", form.instance, f"Attendance marked for {form.instance.employee.username} on {form.instance.date}")
        messages.success(self.request, "Attendance marked successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Mark Attendance"
        ctx["action"]     = "Mark"
        return ctx


class AttendanceEditView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model               = Attendance
    form_class          = AttendanceForm
    template_name       = "attendance/attendance_form.html"
    permission_required = "account.change_attendance"
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("attendance_list")

    def form_valid(self, form):
        AuditLog.log(self.request, "UPDATE", form.instance, f"Attendance updated for {form.instance.employee.username} on {form.instance.date}")
        messages.success(self.request, "Attendance updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Attendance"
        ctx["action"]     = "Update"
        return ctx


class AttendanceDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model               = Attendance
    permission_required = "account.delete_attendance"
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("attendance_list")
    template_name       = "attendance/attendance_confirm_delete.html"

    def form_valid(self, form):
        AuditLog.log(self.request, "DELETE", self.object, f"Attendance deleted for {self.object.employee.username} on {self.object.date}")
        messages.success(self.request, "Attendance record deleted.")
        return super().form_valid(form)


class AttendanceMonthlyReportView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name       = "attendance/attendance_report.html"
    permission_required = "account.view_attendance"

    def get_context_data(self, **kwargs):
        ctx   = super().get_context_data(**kwargs)
        today = date.today()

        month    = int(self.request.GET.get("month", today.month))
        year     = int(self.request.GET.get("year",  today.year))
        emp_id   = self.request.GET.get("employee", "")

        # All days in selected month
        _, days_in_month = calendar.monthrange(year, month)
        all_days = [date(year, month, d) for d in range(1, days_in_month + 1)]

        # All employees who have attendance in this month
        employees = User.objects.filter(
            attendances__date__month=month,
            attendances__date__year=year
        ).distinct().order_by("username")

        if emp_id:
            employees = employees.filter(id=emp_id)

        # Build report matrix: {employee: {date: attendance_obj}}
        report = []
        for emp in employees:
            records = {
                a.date: a
                for a in Attendance.objects.filter(
                    employee=emp, date__month=month, date__year=year
                )
            }
            present = sum(1 for a in records.values() if a.status == "present")
            absent  = sum(1 for a in records.values() if a.status == "absent")
            leave   = sum(1 for a in records.values() if a.status == "leave")
            half    = sum(1 for a in records.values() if a.status == "half")
            late    = sum(1 for a in records.values() if a.status == "late")
            report.append({
                "employee": emp,
                "records":  records,
                "present":  present,
                "absent":   absent,
                "leave":    leave,
                "half":     half,
                "late":     late,
                "total":    len(records),
            })

        ctx["report"]        = report
        ctx["all_days"]      = all_days
        ctx["month"]         = month
        ctx["year"]          = year
        ctx["month_name"]    = calendar.month_name[month]
        ctx["month_choices"] = [(i, calendar.month_name[i]) for i in range(1, 13)]
        ctx["year_range"]    = range(today.year - 3, today.year + 1)
        ctx["all_employees"] = User.objects.filter(is_active=True).order_by("username")
        ctx["selected_emp"]  = emp_id
        ctx["days_in_month"] = days_in_month
        return ctx


class AttendanceWeeklyReportView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name       = "attendance/attendance_weekly_report.html"
    permission_required = "account.view_attendance"

    def get_context_data(self, **kwargs):
        ctx   = super().get_context_data(**kwargs)
        today = date.today()

        # Which week? Default = current week (Mon-Sun)
        # Allow navigating via ?week_start=YYYY-MM-DD
        week_start_str = self.request.GET.get("week_start", "")
        if week_start_str:
            try:
                week_start = dt.strptime(week_start_str, "%Y-%m-%d").date()
                # Snap to Monday
                week_start = week_start - timedelta(days=week_start.weekday())
            except ValueError:
                week_start = today - timedelta(days=today.weekday())
        else:
            week_start = today - timedelta(days=today.weekday())

        week_end  = week_start + timedelta(days=6)
        week_days = [week_start + timedelta(days=i) for i in range(7)]

        prev_week = week_start - timedelta(days=7)
        next_week = week_start + timedelta(days=7)

        emp_id = self.request.GET.get("employee", "")

        # Employees with records this week
        employees = User.objects.filter(
            attendances__date__gte=week_start,
            attendances__date__lte=week_end,
        ).distinct().order_by("username")

        if emp_id:
            employees = employees.filter(id=emp_id)

        # Build report matrix
        report = []
        for emp in employees:
            rec_dict = {
                a.date: a
                for a in Attendance.objects.filter(
                    employee=emp,
                    date__gte=week_start,
                    date__lte=week_end,
                )
            }
            # Build ordered list matching week_days — None if no record
            day_records = [rec_dict.get(d) for d in week_days]

            present = sum(1 for a in rec_dict.values() if a.status == "present")
            absent  = sum(1 for a in rec_dict.values() if a.status == "absent")
            leave   = sum(1 for a in rec_dict.values() if a.status == "leave")
            half    = sum(1 for a in rec_dict.values() if a.status == "half")
            late    = sum(1 for a in rec_dict.values() if a.status == "late")
            report.append({
                "employee":    emp,
                "day_records": day_records,
                "present":     present,
                "absent":      absent,
                "leave":       leave,
                "half":        half,
                "late":        late,
                "total":       len(rec_dict),
            })

        ctx["report"]        = report
        ctx["week_days"]     = week_days
        ctx["week_start"]    = week_start
        ctx["week_end"]      = week_end
        ctx["prev_week"]     = prev_week
        ctx["next_week"]     = next_week
        ctx["today"]         = today

        # Today's summary — always shown at top
        today_qs = Attendance.objects.filter(date=today)
        ctx["today_present"] = today_qs.filter(status="present").count()
        ctx["today_absent"]  = today_qs.filter(status="absent").count()
        ctx["today_leave"]   = today_qs.filter(status="leave").count()
        ctx["today_half"]    = today_qs.filter(status="half").count()
        ctx["today_late"]    = today_qs.filter(status="late").count()
        ctx["today_total"]   = today_qs.count()
        ctx["all_employees"] = User.objects.filter(is_active=True).order_by("username")
        ctx["selected_emp"]  = emp_id
        return ctx


# ═══════════════════════════════════════════════════════════
# REPORT EXPORT HELPERS
# ═══════════════════════════════════════════════════════════

def _get_attendance_queryset(request):
    """
    Shared helper — builds a filtered Attendance queryset from GET params.
    Params: report_type (monthly|weekly|custom), month, year, week_start,
            from, to, employee
    """
    qs      = Attendance.objects.select_related("employee", "office").all()
    today   = date.today()
    rtype   = request.GET.get("report_type", "monthly")
    emp_id  = request.GET.get("employee", "")

    if rtype == "monthly":
        month = int(request.GET.get("month", today.month))
        year  = int(request.GET.get("year",  today.year))
        qs    = qs.filter(date__month=month, date__year=year)
    elif rtype == "weekly":
        ws_str = request.GET.get("week_start", "")
        try:
            week_start = dt.strptime(ws_str, "%Y-%m-%d").date()
            week_start = week_start - timedelta(days=week_start.weekday())
        except (ValueError, TypeError):
            week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        qs = qs.filter(date__gte=week_start, date__lte=week_end)
    elif rtype == "custom":
        date_from = request.GET.get("from", "")
        date_to   = request.GET.get("to",   "")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

    if emp_id:
        qs = qs.filter(employee_id=emp_id)

    return qs.order_by("date", "employee__username")


def _report_label(request):
    """Human-readable label for the selected report period."""
    today  = date.today()
    rtype  = request.GET.get("report_type", "monthly")
    if rtype == "monthly":
        month = int(request.GET.get("month", today.month))
        year  = int(request.GET.get("year",  today.year))
        return f"{calendar.month_name[month]}_{year}"
    elif rtype == "weekly":
        ws_str = request.GET.get("week_start", "")
        try:
            week_start = dt.strptime(ws_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return f"Week_{week_start.strftime('%d%b')}_{week_end.strftime('%d%b%Y')}"
    else:
        date_from = request.GET.get("from", "")
        date_to   = request.GET.get("to",   "")
        return f"{date_from}_to_{date_to}" if date_from else "Custom"


# ── CSV Export ───────────────────────────────────────────

class AttendanceExportCSVView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "account.view_attendance"

    def get(self, request):
        qs    = _get_attendance_queryset(request)
        label = _report_label(request)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="attendance_{label}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Date", "Employee", "Full Name",
            "Check In", "Check Out", "Hours Worked",
            "Status", "Office", "Location Verified", "Note"
        ])
        for rec in qs:
            writer.writerow([
                rec.date.strftime("%Y-%m-%d"),
                rec.employee.username,
                rec.employee.get_full_name(),
                rec.check_in.strftime("%H:%M")  if rec.check_in  else "",
                rec.check_out.strftime("%H:%M") if rec.check_out else "",
                rec.hours_worked,
                rec.get_status_display(),
                rec.office.name if rec.office else "",
                "Yes" if rec.location_verified else "No",
                rec.note,
            ])
        return response


# ── Excel Export ─────────────────────────────────────────

class AttendanceExportExcelView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "account.view_attendance"

    def get(self, request):
        qs    = _get_attendance_queryset(request)
        label = _report_label(request)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Attendance"

        # ── Styles ──
        header_font    = Font(bold=True, color="FFFFFF", size=11)
        header_fill    = PatternFill("solid", fgColor="1e40af")
        center         = Alignment(horizontal="center", vertical="center")
        thin           = Side(style="thin", color="D1D5DB")
        border         = Border(left=thin, right=thin, top=thin, bottom=thin)

        status_fills = {
            "present": PatternFill("solid", fgColor="DCFCE7"),
            "absent":  PatternFill("solid", fgColor="FEE2E2"),
            "leave":   PatternFill("solid", fgColor="FEF3C7"),
            "half":    PatternFill("solid", fgColor="EDE9FE"),
            "late":    PatternFill("solid", fgColor="CFFAFE"),
        }

        # ── Title row ──
        ws.merge_cells("A1:J1")
        title_cell = ws["A1"]
        title_cell.value = f"Attendance Report — {label.replace('_', ' ')}"
        title_cell.font      = Font(bold=True, size=13, color="1e293b")
        title_cell.alignment = center
        ws.row_dimensions[1].height = 28

        # ── Header row ──
        headers = [
            "Date", "Employee", "Full Name",
            "Check In", "Check Out", "Hours Worked",
            "Status", "Office", "Location Verified", "Note"
        ]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=2, column=col, value=h)
            cell.font      = header_font
            cell.fill      = header_fill
            cell.alignment = center
            cell.border    = border
        ws.row_dimensions[2].height = 22

        # ── Data rows ──
        for row_idx, rec in enumerate(qs, 3):
            values = [
                rec.date.strftime("%Y-%m-%d"),
                rec.employee.username,
                rec.employee.get_full_name(),
                rec.check_in.strftime("%H:%M")  if rec.check_in  else "–",
                rec.check_out.strftime("%H:%M") if rec.check_out else "–",
                rec.hours_worked,
                rec.get_status_display(),
                rec.office.name if rec.office else "–",
                "Yes" if rec.location_verified else "No",
                rec.note or "",
            ]
            status_fill = status_fills.get(rec.status)
            for col, val in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col, value=val)
                cell.border    = border
                cell.alignment = Alignment(vertical="center")
                if status_fill and col in (1, 7):
                    cell.fill = status_fill
            ws.row_dimensions[row_idx].height = 18

        # ── Column widths ──
        col_widths = [14, 16, 22, 10, 10, 14, 12, 18, 18, 30]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # ── Freeze header ──
        ws.freeze_panes = "A3"

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        response = HttpResponse(
            buffer,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="attendance_{label}.xlsx"'
        return response


# ── PDF Export ───────────────────────────────────────────

class AttendanceExportPDFView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "account.view_attendance"

    def get(self, request):
        qs    = _get_attendance_queryset(request)
        label = _report_label(request)

        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=1.5*cm,  bottomMargin=1.5*cm,
        )

        styles  = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title", parent=styles["Heading1"],
            fontSize=14, textColor=rl_colors.HexColor("#1e293b"),
            spaceAfter=6, alignment=TA_LEFT,
        )
        sub_style = ParagraphStyle(
            "Sub", parent=styles["Normal"],
            fontSize=9, textColor=rl_colors.HexColor("#64748b"),
            spaceAfter=12,
        )
        cell_style = ParagraphStyle(
            "Cell", parent=styles["Normal"],
            fontSize=8, leading=10,
        )

        # ── Status colors ──
        status_colors = {
            "present": rl_colors.HexColor("#DCFCE7"),
            "absent":  rl_colors.HexColor("#FEE2E2"),
            "leave":   rl_colors.HexColor("#FEF3C7"),
            "half":    rl_colors.HexColor("#EDE9FE"),
            "late":    rl_colors.HexColor("#CFFAFE"),
        }

        elements = []
        elements.append(Paragraph(f"Attendance Report", title_style))
        elements.append(Paragraph(label.replace("_", " "), sub_style))

        # ── Table data ──
        col_headers = [
            "Date", "Employee", "Full Name",
            "Check In", "Check Out", "Hours",
            "Status", "Office", "GPS", "Note"
        ]
        data = [col_headers]
        row_status = []

        for rec in qs:
            data.append([
                rec.date.strftime("%d %b %Y"),
                rec.employee.username,
                rec.employee.get_full_name() or "–",
                rec.check_in.strftime("%H:%M")  if rec.check_in  else "–",
                rec.check_out.strftime("%H:%M") if rec.check_out else "–",
                rec.hours_worked,
                rec.get_status_display(),
                rec.office.name if rec.office else "–",
                "Yes" if rec.location_verified else "No",
                (rec.note[:30] + "...") if rec.note and len(rec.note) > 30 else (rec.note or "–"),
            ])
            row_status.append(rec.status)

        col_widths = [2.2*cm, 2.5*cm, 3.5*cm, 1.8*cm, 1.8*cm,
                      1.8*cm, 1.8*cm, 3*cm,   1.5*cm, 4.5*cm]

        table = Table(data, colWidths=col_widths, repeatRows=1)

        # Base style
        style_cmds = [
            ("BACKGROUND",   (0,0), (-1,0), rl_colors.HexColor("#1e40af")),
            ("TEXTCOLOR",    (0,0), (-1,0), rl_colors.white),
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,0), 8),
            ("ALIGN",        (0,0), (-1,0), "CENTER"),
            ("BOTTOMPADDING",(0,0), (-1,0), 6),
            ("TOPPADDING",   (0,0), (-1,0), 6),
            ("FONTNAME",     (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",     (0,1), (-1,-1), 7.5),
            ("ALIGN",        (0,1), (-1,-1), "LEFT"),
            ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",   (0,1), (-1,-1), 4),
            ("BOTTOMPADDING",(0,1), (-1,-1), 4),
            ("ROWBACKGROUNDS",(0,1), (-1,-1),
             [rl_colors.white, rl_colors.HexColor("#F8FAFC")]),
            ("GRID",         (0,0), (-1,-1), 0.4, rl_colors.HexColor("#E2E8F0")),
            ("LINEBELOW",    (0,0), (-1,0), 1.2, rl_colors.HexColor("#1e40af")),
        ]

        # Per-row status background on Status column (col 6)
        for i, status in enumerate(row_status, 1):
            bg = status_colors.get(status)
            if bg:
                style_cmds.append(("BACKGROUND", (6, i), (6, i), bg))

        table.setStyle(TableStyle(style_cmds))
        elements.append(table)

        # ── Summary footer ──
        elements.append(Spacer(1, 0.4*cm))
        total   = len(row_status)
        summary = "  |  ".join([
            f"Total: {total}",
            f"Present: {row_status.count('present')}",
            f"Absent: {row_status.count('absent')}",
            f"Leave: {row_status.count('leave')}",
            f"Half Day: {row_status.count('half')}",
            f"Late: {row_status.count('late')}",
        ])
        elements.append(Paragraph(summary, sub_style))

        doc.build(elements)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="attendance_{label}.pdf"'
        return response


# ═══════════════════════════════════════════════════════════
# SELF CHECK-IN / CHECK-OUT  (employee uses this)
# ═══════════════════════════════════════════════════════════

class SelfCheckInView(LoginRequiredMixin, TemplateView):
    """
    Page the employee opens to check in or check out.
    Browser captures GPS → JS sends to CheckInSubmitView.
    """
    template_name = "attendance/self_checkin.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = date.today()
        ctx["today"] = today

        # Has the employee already checked in today?
        try:
            record = Attendance.objects.get(
                employee=self.request.user, date=today
            )
            ctx["record"]       = record
            ctx["checked_in"]   = record.check_in is not None
            ctx["checked_out"]  = record.check_out is not None
        except Attendance.DoesNotExist:
            ctx["record"]      = None
            ctx["checked_in"]  = False
            ctx["checked_out"] = False

        # Active offices for the map display
        ctx["offices"] = Office.objects.filter(is_active=True)
        return ctx


class CheckInSubmitView(LoginRequiredMixin, View):
    """
    AJAX POST endpoint.
    Receives: { action: "checkin"|"checkout", lat, lng, office_id }
    Returns:  JSON { success, message, distance, allowed_radius }
    """

    def post(self, request, *args, **kwargs):
        try:
            data      = json.loads(request.body)
            action    = data.get("action")           # "checkin" or "checkout"
            lat       = float(data.get("lat", 0))
            lng       = float(data.get("lng", 0))
            office_id = data.get("office_id")
        except (ValueError, TypeError, json.JSONDecodeError):
            return JsonResponse({"success": False, "message": "Invalid data."}, status=400)

        today = date.today()
        now   = timezone.localtime().time()

        # ── Resolve office ──────────────────────────────────
        if office_id:
            office = get_object_or_404(Office, id=office_id, is_active=True)
        else:
            # Auto-pick nearest active office
            offices  = Office.objects.filter(is_active=True)
            if not offices.exists():
                return JsonResponse({
                    "success": False,
                    "message": "No offices configured. Contact your administrator."
                })
            office = min(offices, key=lambda o: o.distance_to(lat, lng))

        # ── GPS validation ──────────────────────────────────
        distance = round(office.distance_to(lat, lng))
        if not office.is_within_radius(lat, lng):
            return JsonResponse({
                "success":       False,
                "message":       (
                    f"You are {distance}m away from {office.name}. "
                    f"You must be within {office.allowed_radius}m to mark attendance."
                ),
                "distance":      distance,
                "allowed_radius": office.allowed_radius,
                "office":        office.name,
            })

        # ── Check In ────────────────────────────────────────
        if action == "checkin":
            auto_status = office.auto_status(now)
            record, created = Attendance.objects.get_or_create(
                employee=request.user,
                date=today,
                defaults={
                    "office":            office,
                    "check_in":          now,
                    "check_in_lat":      lat,
                    "check_in_lng":      lng,
                    "location_verified": True,
                    "status":            auto_status,
                }
            )
            if not created:
                if record.check_in:
                    return JsonResponse({
                        "success": False,
                        "message": f"You already checked in today at {record.check_in.strftime('%H:%M')}."
                    })
                # Record exists (admin created it) but no check_in time — fill it
                record.check_in          = now
                record.check_in_lat      = lat
                record.check_in_lng      = lng
                record.location_verified = True
                record.office            = office
                record.status            = auto_status
                record.save()

            AuditLog.log(
                request, "CREATE", record,
                f"{request.user.username} checked in at {office.name} ({distance}m away)"
            )
            status_labels = {
                "present": "On Time",
                "late":    "Late",
                "half":    "Half Day",
            }
            status_msg = status_labels.get(auto_status, "")
            return JsonResponse({
                "success":  True,
                "message":  f"Checked in at {now.strftime('%H:%M')} — {office.name} ({status_msg})",
                "time":     now.strftime("%H:%M"),
                "distance": distance,
                "office":   office.name,
                "status":   auto_status,
                "status_label": status_msg,
            })

        # ── Check Out ───────────────────────────────────────
        elif action == "checkout":
            try:
                record = Attendance.objects.get(employee=request.user, date=today)
            except Attendance.DoesNotExist:
                return JsonResponse({
                    "success": False,
                    "message": "You have not checked in today yet."
                })

            if record.check_out:
                return JsonResponse({
                    "success": False,
                    "message": f"You already checked out at {record.check_out.strftime('%H:%M')}."
                })

            record.check_out     = now
            record.check_out_lat = lat
            record.check_out_lng = lng
            record.save()

            AuditLog.log(
                request, "UPDATE", record,
                f"{request.user.username} checked out from {office.name}"
            )
            return JsonResponse({
                "success":  True,
                "message":  f"Checked out at {now.strftime('%H:%M')}",
                "time":     now.strftime("%H:%M"),
                "distance": distance,
                "office":   office.name,
            })

        return JsonResponse({"success": False, "message": "Invalid action."}, status=400)


# ═══════════════════════════════════════════════════════════
# OFFICE MANAGEMENT  (admin uses this)
# ═══════════════════════════════════════════════════════════



class OfficeListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model               = Office
    template_name       = "attendance/office_list.html"
    context_object_name = "offices"
    permission_required = "account.view_office"

    def get_queryset(self):
        return Office.objects.all()


class OfficeCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model               = Office
    form_class          = OfficeForm
    template_name       = "attendance/office_form.html"
    permission_required = "account.add_office"
    success_url         = reverse_lazy("office_list")

    def form_valid(self, form):
        AuditLog.log(self.request, "CREATE", form.instance, f"Office created: {form.instance.name}")
        messages.success(self.request, f"Office '{form.instance.name}' added.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Add Office"
        ctx["action"]     = "Add"
        return ctx


class OfficeEditView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model               = Office
    form_class          = OfficeForm
    template_name       = "attendance/office_form.html"
    permission_required = "account.change_office"
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("office_list")

    def form_valid(self, form):
        AuditLog.log(self.request, "UPDATE", form.instance, f"Office updated: {form.instance.name}")
        messages.success(self.request, f"Office '{form.instance.name}' updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Office"
        ctx["action"]     = "Update"
        return ctx


class OfficeDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model               = Office
    permission_required = "account.delete_office"
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("office_list")
    template_name       = "attendance/office_confirm_delete.html"

    def form_valid(self, form):
        AuditLog.log(self.request, "DELETE", self.object, f"Office deleted: {self.object.name}")
        messages.success(self.request, f"Office '{self.object.name}' deleted.")
        return super().form_valid(form)


# ═══════════════════════════════════════════════════════════
# LEAVE MANAGEMENT
# ═══════════════════════════════════════════════════════════

class LeaveTypeListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model               = LeaveType
    template_name       = "leave/leavetype_list.html"
    context_object_name = "leave_types"
    permission_required = "account.view_leavetype"

    def get_queryset(self):
        return LeaveType.objects.all()


class LeaveTypeCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model               = LeaveType
    template_name       = "leave/leavetype_form.html"
    permission_required = "account.add_leavetype"
    fields              = ["name", "description", "max_days", "color", "is_active"]
    success_url         = reverse_lazy("leavetype_list")

    def form_valid(self, form):
        messages.success(self.request, "Leave type created.")
        return super().form_valid(form)


class LeaveTypeEditView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model               = LeaveType
    template_name       = "leave/leavetype_form.html"
    permission_required = "account.change_leavetype"
    fields              = ["name", "description", "max_days", "color", "is_active"]
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("leavetype_list")

    def form_valid(self, form):
        messages.success(self.request, "Leave type updated.")
        return super().form_valid(form)


class LeaveTypeDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model               = LeaveType
    template_name       = "leave/leavetype_confirm_delete.html"
    permission_required = "account.delete_leavetype"
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("leavetype_list")

    def form_valid(self, form):
        messages.success(self.request, "Leave type deleted.")
        return super().form_valid(form)


# ── Leave Requests ──────────────────────────────────────

class LeaveRequestListView(LoginRequiredMixin, ListView):
    model               = LeaveRequest
    template_name       = "leave/leaverequest_list.html"
    context_object_name = "requests"
    paginate_by         = 20

    def get_queryset(self):
        qs = LeaveRequest.objects.select_related("employee", "leave_type", "reviewed_by")

        # Managers/staff see all; employees see only their own
        if not self.request.user.has_perm("account.view_leaverequest"):
            qs = qs.filter(employee=self.request.user)

        status   = self.request.GET.get("status", "")
        lt       = self.request.GET.get("leave_type", "")
        emp_id   = self.request.GET.get("employee", "")
        q        = self.request.GET.get("q", "").strip()

        if status:
            qs = qs.filter(status=status)
        if lt:
            qs = qs.filter(leave_type_id=lt)
        if emp_id and self.request.user.has_perm("account.view_leaverequest"):
            qs = qs.filter(employee_id=emp_id)
        if q:
            qs = qs.filter(
                Q(employee__username__icontains=q) |
                Q(reason__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["leave_types"]    = LeaveType.objects.filter(is_active=True)
        ctx["all_employees"]  = User.objects.filter(is_active=True).order_by("username")
        ctx["selected_status"]= self.request.GET.get("status", "")
        ctx["selected_lt"]    = self.request.GET.get("leave_type", "")
        ctx["selected_emp"]   = self.request.GET.get("employee", "")
        ctx["count_pending"]  = self.get_queryset().filter(status="pending").count()
        ctx["count_approved"] = self.get_queryset().filter(status="approved").count()
        ctx["count_rejected"] = self.get_queryset().filter(status="rejected").count()
        return ctx


class LeaveRequestCreateView(LoginRequiredMixin, CreateView):
    model          = LeaveRequest
    template_name  = "leave/leaverequest_form.html"
    fields         = ["leave_type", "start_date", "end_date", "reason"]
    success_url    = reverse_lazy("leave_request_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["leave_type"].queryset = LeaveType.objects.filter(is_active=True)
        return form

    def form_valid(self, form):
        form.instance.employee = self.request.user
        messages.success(self.request, "Leave request submitted successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = date.today()
        # Show leave balances for current user
        ctx["balances"] = LeaveBalance.objects.filter(
            employee=self.request.user, year=today.year
        ).select_related("leave_type")
        return ctx


class LeaveRequestDetailView(LoginRequiredMixin, View):
    def get(self, request, id):
        obj = get_object_or_404(LeaveRequest, id=id)
        # Employees can only see their own
        if not request.user.has_perm("account.view_leaverequest") and obj.employee != request.user:
            messages.error(request, "You do not have permission to view this request.")
            return redirect("leave_request_list")
        return render(request, "leave/leaverequest_detail.html", {"obj": obj})


class LeaveRequestCancelView(LoginRequiredMixin, View):
    def post(self, request, id):
        obj = get_object_or_404(LeaveRequest, id=id, employee=request.user)
        if obj.status == "pending":
            obj.status = "cancelled"
            obj.save()
            messages.success(request, "Leave request cancelled.")
        else:
            messages.error(request, "Only pending requests can be cancelled.")
        return redirect("leave_request_list")


class LeaveApproveView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "account.change_leaverequest"

    def post(self, request, id):
        obj         = get_object_or_404(LeaveRequest, id=id)
        action      = request.POST.get("action")      # approve | reject
        review_note = request.POST.get("review_note", "")

        if action == "approve":
            obj.status    = "approved"
            # Update leave balance
            balance, _ = LeaveBalance.objects.get_or_create(
                employee=obj.employee,
                leave_type=obj.leave_type,
                year=obj.start_date.year,
                defaults={"total_days": obj.leave_type.max_days}
            )
            balance.used_days = float(balance.used_days) + float(obj.total_days)
            balance.save()
            messages.success(request, f"Leave approved for {obj.employee.username}.")
        elif action == "reject":
            obj.status = "rejected"
            messages.warning(request, f"Leave rejected for {obj.employee.username}.")

        obj.reviewed_by  = request.user
        obj.reviewed_at  = timezone.now()
        obj.review_note  = review_note
        obj.save()
        return redirect("leave_request_list")


# ── Leave Balance ────────────────────────────────────────

class LeaveBalanceView(LoginRequiredMixin, TemplateView):
    template_name = "leave/leave_balance.html"

    def get_context_data(self, **kwargs):
        ctx       = super().get_context_data(**kwargs)
        today     = date.today()
        emp_id    = self.request.GET.get("employee", "")
        year      = int(self.request.GET.get("year", today.year))

        # Managers see all; employees see own
        if self.request.user.has_perm("account.view_leavebalance") and emp_id:
            employee = get_object_or_404(User, id=emp_id)
        else:
            employee = self.request.user

        balances   = LeaveBalance.objects.filter(
            employee=employee, year=year
        ).select_related("leave_type")

        # Fill in missing leave types
        all_types  = LeaveType.objects.filter(is_active=True)
        bal_dict   = {b.leave_type_id: b for b in balances}
        balance_rows = []
        for lt in all_types:
            if lt.id in bal_dict:
                balance_rows.append(bal_dict[lt.id])
            else:
                balance_rows.append(LeaveBalance(
                    employee=employee, leave_type=lt,
                    year=year, total_days=lt.max_days, used_days=0
                ))

        ctx["balance_rows"]   = balance_rows
        ctx["employee"]       = employee
        ctx["year"]           = year
        ctx["year_range"]     = range(today.year - 2, today.year + 2)
        ctx["all_employees"]  = User.objects.filter(is_active=True).order_by("username") if self.request.user.has_perm("account.view_leavebalance") else []
        ctx["selected_emp"]   = emp_id

        # Recent approved leave requests
        ctx["recent_leaves"]  = LeaveRequest.objects.filter(
            employee=employee, start_date__year=year, status="approved"
        ).select_related("leave_type").order_by("-start_date")[:10]
        return ctx


class LeaveBalanceEditView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "account.change_leavebalance"

    def get(self, request, id):
        balance = get_object_or_404(LeaveBalance, id=id)
        return render(request, "leave/leave_balance_edit.html", {"balance": balance})

    def post(self, request, id):
        balance            = get_object_or_404(LeaveBalance, id=id)
        balance.total_days = int(request.POST.get("total_days", balance.total_days))
        balance.used_days  = float(request.POST.get("used_days", balance.used_days))
        balance.save()
        messages.success(request, "Leave balance updated.")
        return redirect("leave_balance")


# ═══════════════════════════════════════════════════════════
# NOTICE / ANNOUNCEMENT
# ═══════════════════════════════════════════════════════════

class NoticeListView(LoginRequiredMixin, ListView):
    model               = Notice
    template_name       = "notice/notice_list.html"
    context_object_name = "notices"
    paginate_by         = 15

    def get_queryset(self):
        now = timezone.now()
        qs  = Notice.objects.filter(is_active=True, publish_at__lte=now)

        # Filter expired
        qs = qs.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))

        # Non-staff only see notices targeted to them or all
        if not self.request.user.is_staff:
            qs = qs.filter(
                Q(target_users=self.request.user) | Q(target_users__isnull=True)
            ).distinct()

        priority = self.request.GET.get("priority", "")
        q        = self.request.GET.get("q", "").strip()
        if priority:
            qs = qs.filter(priority=priority)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q))

        return qs.select_related("posted_by").prefetch_related("target_users")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["selected_priority"] = self.request.GET.get("priority", "")
        ctx["pinned_notices"]    = self.get_queryset().filter(is_pinned=True)[:3]
        return ctx


class NoticeCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model               = Notice
    template_name       = "notice/notice_form.html"
    permission_required = "account.add_notice"
    fields              = ["title", "content", "priority", "target_users",
                           "is_pinned", "publish_at", "expires_at"]
    success_url         = reverse_lazy("notice_list")

    def form_valid(self, form):
        form.instance.posted_by = self.request.user
        messages.success(self.request, "Notice posted successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Post Notice"
        ctx["all_employees"] = User.objects.filter(is_active=True).order_by("username")
        ctx["selected_user_ids"] = set()
        return ctx


class NoticeEditView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model               = Notice
    template_name       = "notice/notice_form.html"
    permission_required = "account.change_notice"
    fields              = ["title", "content", "priority", "target_users",
                           "is_pinned", "is_active", "publish_at", "expires_at"]
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("notice_list")

    def form_valid(self, form):
        messages.success(self.request, "Notice updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Edit Notice"
        ctx["all_employees"] = User.objects.filter(is_active=True).order_by("username")
        ctx["selected_user_ids"] = set(
            self.object.target_users.values_list("id", flat=True)
        )
        return ctx


class NoticeDetailView(LoginRequiredMixin, View):
    def get(self, request, id):
        now    = timezone.now()
        notice = get_object_or_404(Notice, id=id)
        # Non-staff can only view active, published, non-expired notices for them
        if not request.user.is_staff:
            if not notice.is_active or notice.publish_at > now:
                raise Http404
            if notice.is_expired:
                raise Http404
            targets = notice.target_users.all()
            if targets.exists() and request.user not in targets:
                raise Http404
        return render(request, "notice/notice_detail.html", {"notice": notice})


class NoticeDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model               = Notice
    template_name       = "notice/notice_confirm_delete.html"
    permission_required = "account.delete_notice"
    pk_url_kwarg        = "id"
    success_url         = reverse_lazy("notice_list")

    def form_valid(self, form):
        messages.success(self.request, "Notice deleted.")
        return super().form_valid(form)