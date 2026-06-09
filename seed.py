import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from etude.models import (Question, Choix, Enregistrement, CodeAcces, Groupe, Media,
    Participant, Jugement, Reponse, ReponseProfil)

# Réinitialisation des données de démo, dans l'ordre des dépendances
# (Reponse/ReponseProfil pointent vers Question en PROTECT).
Reponse.objects.all().delete(); ReponseProfil.objects.all().delete()
Jugement.objects.all().delete(); Participant.objects.all().delete()
Question.objects.all().delete(); Enregistrement.objects.all().delete()
Groupe.objects.all().delete(); Media.objects.all().delete()

# Groupe de profil : questions posées une seule fois (statistiques).
g0 = Groupe.objects.create(titre="À propos de vous", ordre=0)
Question.objects.create(code="age", libelle="Quel âge avez-vous ?", type="texte",
    portee="profil", groupe=g0, ordre=0)
qg = Question.objects.create(code="genre", libelle="Genre", type="choix",
    portee="profil", groupe=g0, ordre=1)
for i,(v,l) in enumerate([("f","Femme"),("h","Homme"),("a","Autre"),("ns","Préfère ne pas dire")]):
    Choix.objects.create(question=qg, valeur=v, libelle=l, ordre=i)

# Deux groupes par extrait pour illustrer la mise en page (g2 = nouvelle page).
g1 = Groupe.objects.create(titre="Écoute globale", ordre=1)
g2 = Groupe.objects.create(titre="Détail", ordre=2, nouvelle_page=True,
    consigne="Réécoutez l'extrait audio ci-dessous avant de répondre.")
m = Media.objects.create(code="exemple_audio", type_media="audio", fichier="medias/exemple.mp3")

q1 = Question.objects.create(code="q1", libelle="Question d'exemple (échelle)", type="echelle",
    min_val=1, max_val=7, label_min="Pas du tout", label_max="Tout à fait", groupe=g1, ordre=0)
q2 = Question.objects.create(code="q2", libelle="Question d'exemple (choix)",
    type="choix", choix_multiple=True, groupe=g1, ordre=1)
for i,(v,l) in enumerate([("a","Option A"),("b","Option B"),("c","Option C")]):
    Choix.objects.create(question=q2, valeur=v, libelle=l, ordre=i)
q3 = Question.objects.create(code="q3", libelle="Question d'exemple (texte libre)", type="texte",
    obligatoire=False, groupe=g2, ordre=0, media=m)

for i in range(1,4):
    Enregistrement.objects.create(code=f"clip_{i:03d}", fichier_video="videos/clip_001.mp4",
        fichier_vtt="videos/clip_001.vtt", categorie="test")

# Accès de démonstration (à supprimer avant une vraie collecte) :
#   - "demo"   : code individuel (lié à un participant à la 1re utilisation)
#   - "ouvert" : lien collectif à partager (/acces/ouvert/)
CodeAcces.objects.get_or_create(code="demo", defaults={"note": "code individuel de démo"})
CodeAcces.objects.get_or_create(code="ouvert", defaults={"collectif": True, "note": "lien collectif de démo"})
print("Seed OK :", Question.objects.count(), "questions dans", Groupe.objects.count(),
      "groupes,", Enregistrement.objects.count(),
      "clips. Code individuel : demo — Lien collectif : /acces/ouvert/ — Éditeur : /editeur/")
