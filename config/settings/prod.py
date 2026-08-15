import os

from dotenv import load_dotenv

from .base import *  # noqa: F401,F403

load_dotenv(os.environ.get("ENV_FILE", "/etc/cmm-emendas/emendas.env"))

DEBUG = os.environ.get("DEBUG", "False") == "True"
SECRET_KEY = os.environ["SECRET_KEY"]
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/var/lib/cmm-emendas/media")
STATIC_ROOT = os.environ.get("STATIC_ROOT", "/var/lib/cmm-emendas/static")

CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# O nginx local fala HTTP com o gunicorn; quem termina TLS é o Apache em 10.3.150.20,
# que precisa enviar X-Forwarded-Proto (ver deploy/apache-10.3.150.20.snippet.conf).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# SECURE_COOKIES=False só deve existir no .env de homologação, enquanto se acessa
# direto por HTTP (sem o Apache/TLS na frente) — cookie Secure não é gravado em HTTP
# puro e derruba o login com "CSRF verification failed". Remover a variável (ou
# voltar para True) assim que o Apache estiver na frente com TLS.
_secure_cookies = os.environ.get("SECURE_COOKIES", "True") == "True"
SESSION_COOKIE_SECURE = _secure_cookies
CSRF_COOKIE_SECURE = _secure_cookies
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
