# Déploiement en production

Pile : **Nginx** (HTTPS, fichiers, médias protégés) → **Gunicorn** (lance Django),
géré par **systemd**. Fichiers d'exemple dans ce dossier — à adapter (domaine,
chemins absolus, utilisateur).

## Déploiement express (ce serveur — VPS Ubuntu Infomaniak)

Contexte : VPS Ubuntu, IPv4 `83.228.221.204`, IPv6 `2001:1600:18:203::242`,
dépôt **public**. Pas de nom de domaine → on utilise **sslip.io**
(`83.228.221.204.sslip.io` résout vers l'IP) pour obtenir un **certificat HTTPS**
Let's Encrypt sans acheter de domaine. (Un vrai domaine reste préférable à terme :
il suffira de relancer certbot avec `-d ton-domaine`.)

**Depuis ton Mac**, connecte-toi en SSH au serveur, puis (en root) :

```bash
sudo git clone https://github.com/Hsbtqemy/mareva.git /opt/etude
sudo EMAIL=ton@mail.fr bash /opt/etude/deploy/deployer.sh
```

Le script `deployer.sh` fait tout : paquets, utilisateur `etude`, venv +
dépendances, `.env` (clé secrète générée, `ALLOWED_HOSTS` = sslip.io + IPs),
`migrate`, `collectstatic`, service systemd, Nginx, et HTTPS via certbot.

Ensuite, **créer le compte admin** :

```bash
sudo -u etude /opt/etude/.venv/bin/python /opt/etude/manage.py createsuperuser
```

Puis ouvrir `https://83.228.221.204.sslip.io/` (admin : `/admin/`, éditeur : `/editeur/`).

**Pré-requis** : ports **80 et 443 ouverts** (sécurité Infomaniak + éventuel `ufw`),
dépôt rendu **public** sur GitHub avant le clone. **Mises à jour** : relancer le
même script (il fait `git pull` + redémarrage). En cas d'erreur, copier la sortie
de l'étape en échec.

---

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

> **HTTPS automatique côté Django** : hors DEBUG, le projet active seul les
> cookies `Secure`, l'en-tête de proxy (`X-Forwarded-Proto`) et
> `CSRF_TRUSTED_ORIGINS` = `https://<chaque domaine de ALLOWED_HOSTS>`. Rien à
> régler de plus que `DJANGO_ALLOWED_HOSTS` pour que les formulaires (consentement,
> soumission, éditeur) fonctionnent en HTTPS.
