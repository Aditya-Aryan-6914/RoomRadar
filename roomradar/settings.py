import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "facilities",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "roomradar.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "facilities.context.campus",
    ]},
}]

WSGI_APPLICATION = "roomradar.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"   # change to your campus time zone
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "my_campus"
LOGOUT_REDIRECT_URL = "home"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Timetable reading --------------------------------------------------------------------------
# Built-in rules read timetables with no setup. To let a small LLM read messy cells instead, set:
#   TIMETABLE_LLM_PROVIDER = anthropic | openai      (openai = any OpenAI-compatible server)
#   TIMETABLE_LLM_MODEL    = e.g. claude-haiku-5-5 | qwen2.5:3b (Ollama) | llama-3.1-8b-instant (Groq)
#   TIMETABLE_LLM_API_KEY  = key (not needed for a local Ollama server)  [ANTHROPIC_API_KEY also works]
#   TIMETABLE_LLM_BASE_URL = e.g. http://localhost:11434/v1 (Ollama), https://api.groq.com/openai/v1
# Only the text of the timetable cells is sent to the model, never the PDF itself.
TIMETABLE_LLM = {
    "provider": os.environ.get("TIMETABLE_LLM_PROVIDER", "none"),
    "model": os.environ.get("TIMETABLE_LLM_MODEL", ""),
    "api_key": os.environ.get("TIMETABLE_LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""),
    "base_url": os.environ.get("TIMETABLE_LLM_BASE_URL", ""),
}
