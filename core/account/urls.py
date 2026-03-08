"""
urls.py — Complete Auth URL Configuration
"""

from django.urls import path
from . import views
from . import notification_views as nv

urlpatterns = [
    # ── Auth ────────────────────────────────────────────────
    path("login/",   views.LoginView.as_view(),  name="login"),
    path("logout/",  views.LogoutView.as_view(), name="logout"),

    # ── Dashboard ───────────────────────────────────────────
    path("", views.dashboard, name="dashboard"),
    path("dashboard/", views.dashboard, name="dashboard"),

    # ── Users ───────────────────────────────────────────────
    path("users/",                          views.UserListView.as_view(),           name="user_list"),
    path("users/create/",                   views.UserCreateView.as_view(),         name="user_create"),
    path("users/<int:id>/edit/",            views.UserEditView.as_view(),           name="user_edit"),
    path("users/<int:id>/delete/",          views.UserDeleteView.as_view(),         name="user_delete"),
    path("users/<int:id>/password/",        views.UserChangePasswordView.as_view(), name="change_password"),
    path("users/bulk-delete/",              views.UserBulkDeleteView.as_view(),     name="user_bulk_delete"),

    # ── Profile ─────────────────────────────────────────────
    path("profile/",                        views.UserProfileView.as_view(),        name="user_profile"),
    path("profile/<int:id>/",               views.UserProfileView.as_view(),        name="user_profile_admin"),

    # ── Groups ──────────────────────────────────────────────
    path("groups/",                         views.GroupListView.as_view(),          name="group_list"),
    path("groups/create/",                  views.GroupCreateView.as_view(),        name="group_create"),
    path("groups/<int:id>/edit/",           views.GroupEditView.as_view(),          name="group_edit"),
    path("groups/<int:id>/delete/",         views.GroupDeleteView.as_view(),        name="group_delete"),
    path("groups/bulk-delete/",             views.GroupBulkDeleteView.as_view(),    name="group_bulk_delete"),

    # ── Permissions ─────────────────────────────────────────
    path("permissions/",                    views.GroupPermissionListView.as_view(),  name="group_permission_list"),
    path("permissions/<int:group_id>/edit/",views.GroupPermissionEditView.as_view(),  name="group_permission_edit"),

        # ── Audit Log ───────────────────────────────────────────
    path("audit-log/",                      views.AuditLogListView.as_view(),       name="audit_log"),

    # ── Attendance ──────────────────────────────────────────
    path("attendance/",                   views.AttendanceListView.as_view(),        name="attendance_list"),
    path("attendance/mark/",              views.AttendanceCreateView.as_view(),      name="attendance_create"),
    path("attendance/<int:id>/edit/",     views.AttendanceEditView.as_view(),        name="attendance_edit"),
    path("attendance/<int:id>/delete/",   views.AttendanceDeleteView.as_view(),      name="attendance_delete"),
    path("attendance/report/",            views.AttendanceMonthlyReportView.as_view(),  name="attendance_report"),
    path("attendance/report/weekly/",     views.AttendanceWeeklyReportView.as_view(),   name="attendance_weekly_report"),
    path("attendance/export/csv/",        views.AttendanceExportCSVView.as_view(),      name="attendance_export_csv"),
    path("attendance/export/excel/",      views.AttendanceExportExcelView.as_view(),    name="attendance_export_excel"),
    path("attendance/export/pdf/",        views.AttendanceExportPDFView.as_view(),      name="attendance_export_pdf"),
    # Self check-in (employees)
    path("attendance/checkin/",           views.SelfCheckInView.as_view(),              name="self_checkin"),
    path("attendance/checkin/submit/",    views.CheckInSubmitView.as_view(),            name="checkin_submit"),
    # Office management (admin)
    path("offices/",                      views.OfficeListView.as_view(),               name="office_list"),
    path("offices/add/",                  views.OfficeCreateView.as_view(),             name="office_create"),
    path("offices/<int:id>/edit/",        views.OfficeEditView.as_view(),               name="office_edit"),
    path("offices/<int:id>/delete/",      views.OfficeDeleteView.as_view(),             name="office_delete"),

    # ── Leave Management ─────────────────────────────────────
    path("leave/",                         views.LeaveRequestListView.as_view(),        name="leave_request_list"),
    path("leave/apply/",                   views.LeaveRequestCreateView.as_view(),      name="leave_request_create"),
    path("leave/<int:id>/",                views.LeaveRequestDetailView.as_view(),      name="leave_request_detail"),
    path("leave/<int:id>/cancel/",         views.LeaveRequestCancelView.as_view(),      name="leave_request_cancel"),
    path("leave/<int:id>/review/",         views.LeaveApproveView.as_view(),            name="leave_review"),
    path("leave/balance/",                 views.LeaveBalanceView.as_view(),            name="leave_balance"),
    path("leave/balance/<int:id>/edit/",   views.LeaveBalanceEditView.as_view(),        name="leave_balance_edit"),
    path("leave/types/",                   views.LeaveTypeListView.as_view(),           name="leavetype_list"),
    path("leave/types/add/",               views.LeaveTypeCreateView.as_view(),         name="leavetype_create"),
    path("leave/types/<int:id>/edit/",     views.LeaveTypeEditView.as_view(),           name="leavetype_edit"),
    path("leave/types/<int:id>/delete/",   views.LeaveTypeDeleteView.as_view(),         name="leavetype_delete"),

    # ── Notice / Announcement ────────────────────────────────
    path("notices/",                       views.NoticeListView.as_view(),              name="notice_list"),
    path("notices/post/",                  views.NoticeCreateView.as_view(),            name="notice_create"),
    path("notices/<int:id>/",              views.NoticeDetailView.as_view(),            name="notice_detail"),
    path("notices/<int:id>/edit/",         views.NoticeEditView.as_view(),              name="notice_edit"),
    path("notices/<int:id>/delete/",       views.NoticeDeleteView.as_view(),            name="notice_delete"),

    # ── Notifications ────────────────────────────────────────
    path("notifications/",                          nv.NotificationListView.as_view(),      name="notifications"),
    path("notifications/mark-all-read/",            nv.NotificationMarkAllReadView.as_view(),name="notif_mark_all_read"),
    path("notifications/<int:pk>/mark-read/",       nv.NotificationMarkReadView.as_view(),  name="notif_mark_read"),
    path("notifications/<int:pk>/delete/",          nv.NotificationDeleteView.as_view(),    name="notif_delete"),
    path("notifications/clear-all/",                nv.NotificationClearAllView.as_view(),  name="notif_clear_all"),
]