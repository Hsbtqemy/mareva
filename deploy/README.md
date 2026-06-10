# Déploiement en production

Pile : **Nginx** (HTTPS, fichiers, médias protégés) → **Gunicorn** (lance Django),
géré par **systemd**. Fichiers d'exemple dans ce dossier — à adapter (domaine,
chemins absolus, utilisateur).

## Prérequis
- Serveur Linux, **Python 3.11+**, **Nginx**.
- Un nom de domaine pointant vers le serveur (pour HTTPS).

## Étapes

1. **Récupérer le code + dépendances**
   ```bash
   git clone <dépôt> /chemin/absolu/vers/le-projet
   cd /chemin/absolu/vers/le-projet
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configurer l'environnement** : copier `deploy/.env.example` en `.env` (racine)
   et renseigner `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`.
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"   # clé secrète
   ```

3. **Base, statiques, admin**
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser
   ```

4. **Gunicorn en service** : adapter `deploy/etude.service` (chemins, utilisateur), puis
   ```bash
   sudo cp deploy/etude.service /etc/systemd/system/etude.service
   sudo systemctl daemon-reload && sudo systemctl enable --now etude
   ```

5. **Nginx** : adapter `deploy/nginx.conf` (domaine, chemins), puis
   ```bash
   sudo cp deploy/nginx.conf /etc/nginx/sites-available/etude
   sudo ln -s /etc/nginx/sites-available/etude /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

6. **HTTPS** : `sudo certbot --nginx -d mon-domaine.fr`

7. **Contenu** : se connecter à `/admin/`, puis composer le questionnaire et
   téléverser les médias via `/editeur/`.

8. **Sauvegardes** : planifier la commande (cron), p. ex. tous les jours :
   ```cron
   0 3 * * *  cd /chemin/absolu/vers/le-projet && .venv/bin/python manage.py sauvegarde --sortie /backups
   ```

## Mises à jour
```bash
git pull && . .venv/bin/activate && pip install -r requirements.txt
python manage.py migrate && python manage.py collectstatic --noinput
sudo systemctl restart etude
```

## Multi-workers : cache partagé
La limitation anti-flood des codes utilise le cache. Avec plusieurs workers
Gunicorn, le cache par défaut est **par-process** → configurer un cache **partagé**
(Redis/Memcached, ou `python manage.py createcachetable` + cache base de données)
pour que la limite soit globale.

## Sécurité (rappels)
- `DJANGO_DEBUG=0`, `SECRET_KEY` unique et secrète, `ALLOWED_HOSTS` restreint.
- HTTPS actif (certbot). Le dossier `media/` n'est **jamais** servi directement.
- Sauvegarder `db.sqlite3` + `media/` régulièrement (cf. étape 8).
