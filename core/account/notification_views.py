"""
notification_views.py — Notification endpoints
Add these to urls.py
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import redirect, get_object_or_404
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from .models import Notification


class NotificationListView(LoginRequiredMixin, View):
    """Full notifications page."""

    def get(self, request):
        from django.shortcuts import render
        notifications = Notification.objects.filter(
            recipient=request.user
        ).select_related("audit_log")
        # Mark all as read when page is opened
        notifications.filter(is_read=False).update(is_read=True)
        return render(request, "account/notifications.html", {
            "notifications": notifications,
        })


class NotificationMarkReadView(LoginRequiredMixin, View):
    """Mark a single notification as read, then redirect."""

    def post(self, request, pk):
        notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notif.is_read = True
        notif.save(update_fields=["is_read"])
        return redirect(request.META.get("HTTP_REFERER", "dashboard"))


class NotificationMarkAllReadView(LoginRequiredMixin, View):
    """Mark ALL notifications as read via AJAX or form POST."""

    def post(self, request):
        Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True)
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "ok"})
        return redirect("notifications")


class NotificationDeleteView(LoginRequiredMixin, View):
    """Delete a single notification."""

    def post(self, request, pk):
        Notification.objects.filter(pk=pk, recipient=request.user).delete()
        return redirect("notifications")


class NotificationClearAllView(LoginRequiredMixin, View):
    """Delete ALL notifications for this user."""

    def post(self, request):
        Notification.objects.filter(recipient=request.user).delete()
        return redirect("notifications")