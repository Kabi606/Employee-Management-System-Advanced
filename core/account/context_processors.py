"""
context_processors.py
Injects notification data into EVERY template automatically.

REQUIRED — add this line to settings.py inside TEMPLATES[0]['OPTIONS']['context_processors']:
    'account.context_processors.notifications',

App name is 'account'.
"""

from .models import Notification


def notifications(request):
    if not request.user.is_authenticated:
        return {
            "notif_unread_count": 0,
            "notif_latest": [],
        }

    try:
        qs = Notification.objects.filter(
            recipient=request.user
        ).select_related("audit_log").order_by("-created_at")

        unread_count = qs.filter(is_read=False).count()
        latest = list(qs[:5])
    except Exception:
        # Table might not exist yet (before migration)
        unread_count = 0
        latest = []

    return {
        "notif_unread_count": unread_count,
        "notif_latest": latest,
    }