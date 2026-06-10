"""
Configuration Django de l'étude.

Avant production :
  - mettre DEBUG = False
  - renseigner SECRET_KEY via variable d'environnement
  - renseigner ALLOWED_HOSTS
  - configurer Nginx pour X-Accel-Redirect (voir README.md)
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# En production : os.environ["DJANGO_SECRET_KEY"]
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-clef-a-remplacer-en-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Limitation des tentatives de code d'accès (anti-flood). Deux niveaux :
#   - par navigateur (session) : seuil principal, n'affecte pas les autres
#     participants partageant la même IP ;
#   - par IP : garde-fou anti-flood, seuil élevé, remis à zéro à chaque succès.
# Les codes étant des jetons à haute entropie, le brute-force est de toute façon
# irréaliste. Mettre un seuil à 0 désactive ce niveau.
ACCES_MAX_SESSION = int(os.environ.get("ACCES_MAX_SESSION", "8"))
ACCES_MAX_IP = int(os.environ.get("ACCES_MAX_IP", "100"))
ACCES_FENETRE = int(os.environ.get("ACCES_FENETRE", "600"))  # secondes

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "etude",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Dossier de templates projet (recherché avant ceux des apps) : sert à
        # surcharger des gabarits de l'admin (voir templates/admin/base_site.html).
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "etude.context.configuration",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Cible de `collectstatic` en production (fichiers statiques de l'admin).
# En développement (DEBUG=True), Django les sert automatiquement.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Les fichiers média ne sont PAS exposés directement : ils sont servis
# par la vue protégée media_protege(). MEDIA_URL n'est donc pas câblé
# dans urls.py vers un service statique.
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
