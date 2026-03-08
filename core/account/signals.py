"""
signals.py — Django Signals
- Auto-creates UserProfile when a User is created
- Logs login / logout / failed login to AuditLog
- Fires Notifications to admins on key events
"""

from django.db.models.signals import post_save
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import UserProfile, AuditLog, Notification


# ── Auto-create UserProfile ───────────────────────────────────

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


# ── New user created → notify all admins ─────────────────────

@receiver(post_save, sender=User)
def notify_user_created(sender, instance, created, **kwargs):
    if created:
        # Notify superusers and staff — exclude the new user themselves
        admins = User.objects.filter(
            is_active=True
        ).filter(
            is_superuser=True
        ).exclude(pk=instance.pk)

        for admin in admins:
            Notification.objects.create(
                recipient=admin,
                notif_type="user_created",
                title=f"New user registered — '{instance.username}'",
                message=f"A new user account '{instance.username}' has been created.",
            )


# ── Login ─────────────────────────────────────────────────────

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    AuditLog.log(request, "LOGIN", target_obj=user,
                 detail=f"User '{user.username}' logged in.")


# ── Logout ────────────────────────────────────────────────────

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if user:
        AuditLog.log(request, "LOGOUT", target_obj=user,
                     detail=f"User '{user.username}' logged out.")


# ── Failed login → notify all admins ─────────────────────────

@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "unknown")
    ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR", "unknown")
    )

    # Write to audit log
    log = AuditLog.objects.create(
        actor=None,
        action="LOGIN",
        target_model="User",
        target_repr=username,
        detail=f"Failed login attempt for '{username}' from {ip}.",
        ip_address=ip or None,
    )

    # Notify all active superusers
    admins = User.objects.filter(is_active=True, is_superuser=True)
    for admin in admins:
        Notification.objects.create(
            recipient=admin,
            notif_type="login_failed",
            title=f"Failed login — '{username}'",
            message=f"Someone tried to log in as '{username}' from IP {ip}.",
            audit_log=log,
        )