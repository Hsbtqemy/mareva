"""
Configuration Gunicorn (serveur WSGI de production).

Lancement :
    gunicorn -c deploy/gunicorn.conf.py config.wsgi

Nginx fait le proxy vers le port ci-dessous (voir deploy/nginx.conf).
"""

# Adresse interne écoutée par Gunicorn ; Nginx proxifie vers elle.
bind = "127.0.0.1:8001"

# Nombre de workers : ~ (2 × cœurs CPU) + 1. Ajuster selon le serveur.
workers = 3

# Délai généreux pour le téléversement de médias volumineux (jusqu'à 1 Go).
timeout = 120

# Journalisation vers la sortie standard (récupérée par systemd/journald).
accesslog = "-"
errorlog = "-"

# Rappel : avec plusieurs workers, le cache anti-flood par défaut est PAR
# PROCESS. Pour une limite globale, configurer un cache partagé
# (Redis/Memcached, ou `manage.py createcachetable` + cache base de données).
