#!/usr/bin/env bash
#
# Déploiement automatique sur un VPS Ubuntu « vierge ».
# À lancer EN ROOT sur le serveur (pas sur ta machine) :
#
#   sudo git clone https://github.com/Hsbtqemy/mareva.git /opt/etude
#   sudo EMAIL=ton@mail.fr bash /opt/etude/deploy/deployer.sh
#
# Variables surchageables : DOMAINE (défaut sslip.io), EMAIL (Let's Encrypt).
# Le script s'arrête à la première erreur ; relançable sans danger (idempotent).
set -euo pipefail

DEPOT="https://github.com/Hsbtqemy/mareva.git"
CHEMIN="/opt/etude"
UTIL="etude"
IP4="83.228.221.204"
IP6="2001:1600:18:203::242"
# Nom d'hôte pour le HTTPS. sslip.io résout <ip>.sslip.io vers l'IP → certificat possible.
DOMAINE="${DOMAINE:-83.228.221.204.sslip.io}"
EMAIL="${EMAIL:-}"   # email Let's Encrypt (sinon HTTPS non configuré, à faire après)

[ "$(id -u)" -eq 0 ] || { echo "À lancer en root (sudo)."; exit 1; }

echo "== 1/8 Paquets =="
apt-get update -y
apt-get install -y python3-venv python3-pip git nginx snapd
snap install --classic certbot 2>/dev/null || true
ln -sf /snap/bin/certbot /usr/bin/certbot 2>/dev/null || true
# Ouvre le pare-feu si ufw est présent (sans l'activer).
command -v ufw >/dev/null 2>&1 && { ufw allow OpenSSH || true; ufw allow 'Nginx Full' || true; }

echo "== 2/8 Utilisateur + code =="
id "$UTIL" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$CHEMIN" --shell /usr/sbin/nologin "$UTIL"
if [ -d "$CHEMIN/.git" ]; then sudo -u "$UTIL" git -C "$CHEMIN" pull --ff-only; else git clone "$DEPOT" "$CHEMIN"; fi
chown -R "$UTIL":www-data "$CHEMIN"

echo "== 3/8 venv + dépendances =="
sudo -u "$UTIL" python3 -m venv "$CHEMIN/.venv"
sudo -u "$UTIL" "$CHEMIN/.venv/bin/pip" install -q --upgrade pip
sudo -u "$UTIL" "$CHEMIN/.venv/bin/pip" install -q -r "$CHEMIN/requirements.txt"

echo "== 4/8 Fichier .env =="
if [ ! -f "$CHEMIN/.env" ]; then
  SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')"
  printf 'DJANGO_DEBUG=0\nDJANGO_SECRET_KEY=%s\nDJANGO_ALLOWED_HOSTS=%s,%s,%s\n' \
    "$SECRET" "$DOMAINE" "$IP4" "$IP6" > "$CHEMIN/.env"
  chown "$UTIL":www-data "$CHEMIN/.env"; chmod 640 "$CHEMIN/.env"
fi

echo "== 5/8 Base + fichiers statiques =="
sudo -u "$UTIL" "$CHEMIN/.venv/bin/python" "$CHEMIN/manage.py" migrate --noinput
sudo -u "$UTIL" "$CHEMIN/.venv/bin/python" "$CHEMIN/manage.py" collectstatic --noinput

echo "== 6/8 Service systemd =="
sed "s|/chemin/absolu/vers/le-projet|$CHEMIN|g" "$CHEMIN/deploy/etude.service" > /etc/systemd/system/etude.service
systemctl daemon-reload
systemctl enable etude
systemctl restart etude

echo "== 7/8 Nginx =="
sed -e "s|/chemin/absolu/vers/le-projet|$CHEMIN|g" -e "s|server_name .*;|server_name $DOMAINE;|" \
  "$CHEMIN/deploy/nginx.conf" > /etc/nginx/sites-available/etude
ln -sf /etc/nginx/sites-available/etude /etc/nginx/sites-enabled/etude
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "== 8/8 HTTPS (Let's Encrypt) =="
if certbot certificates 2>/dev/null | grep -q "$DOMAINE"; then
  # Certificat existant : réinstalle sans email (non-interactif).
  certbot --nginx -d "$DOMAINE" --non-interactive --redirect \
    || echo "!! Réinstallation certbot échouée."
elif [ -n "$EMAIL" ]; then
  certbot --nginx -d "$DOMAINE" --non-interactive --agree-tos -m "$EMAIL" --redirect \
    || echo "!! certbot a échoué — vérifier que $DOMAINE résout vers ce serveur et que le port 80 est ouvert."
else
  echo "!! EMAIL non fourni et aucun certificat existant → lancer : certbot --nginx -d $DOMAINE"
fi

echo
echo ">>> Déploiement terminé."
echo ">>> 1) Créer le compte administrateur :"
echo "      sudo -u $UTIL $CHEMIN/.venv/bin/python $CHEMIN/manage.py createsuperuser"
echo ">>> 2) Ouvrir :  https://$DOMAINE/   (admin : https://$DOMAINE/admin/ , éditeur : /editeur/)"
echo ">>> Mises à jour ultérieures : relancer ce script (git pull + restart inclus)."
