from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "account"  # change to your actual app name

    def ready(self):
        import account.signals  # noqa: F401 — registers all signal handlers