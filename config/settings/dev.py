from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = "django-insecure-apenas-para-desenvolvimento-local"
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

MEDIA_ROOT = BASE_DIR / "media"  # noqa: F405
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
