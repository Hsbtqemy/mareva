import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from etude.models import (Question, Choix, SousQuestion, CodeAcces, Groupe, Media,
    Participant, Passage, Reponse, ReponseProfil)

# Réinitialisation des données de démo, dans l'ordre des dépendances.
Reponse.objects.all().delete(); ReponseProfil.objects.all().delete()
Passage.objects.all().delete(); Participant.objects.all().delete()
SousQuestion.objects.all().delete()
Question.objects.all().delete(); Groupe.objects.all().delete(); Media.objects.all().delete()

# --- Groupe de PROFIL (posé une seule fois) ---
g0 = Groupe.objects.create(titre="À propos de vous", portee="profil", ordre=0)
Question.objects.create(code="age", libelle="Quel âge avez-vous ?", type="texte", groupe=g0, ordre=0)
qg = Question.objects.create(code="genre", libelle="Genre", type="choix", groupe=g0, ordre=1)
for i,(v,l) in enumerate([("f","Femme"),("h","Homme"),("a","Autre"),("ns","Préfère ne pas dire")]):
    Choix.objects.create(question=qg, valeur=v, libelle=l, ordre=i)

# --- Groupe STANDARD avec UNE vidéo (à gauche) + matrice + drag&drop + textes ---
clip = Media.objects.create(code="clip_demo", type_media="video", fichier="videos/demo.mp4")
g1 = Groupe.objects.create(titre="Analyse de l'extrait", portee="standard", ordre=1, media=clip,
    consigne="Regardez la vidéo à gauche, puis répondez.")

# Matrice : rôles (sous-questions = participants) × catégories (rôle)
qm = Question.objects.create(code="roles", libelle="Rôle de chaque participant",
    type="matrice", melanger=True, groupe=g1, ordre=0)
for i,(v,l) in enumerate([("AO01","Socializer"),("AO02","Achiever"),("AO03","Explorer"),
                          ("AO04","Griefer"),("AO05","Politician"),("AO06","None")]):
    Choix.objects.create(question=qm, valeur=v, libelle=l, ordre=i)
for i,(c,l) in enumerate([("BLUE_role","Participant BLUE"),("PINK_role","Participant PINK"),
                          ("GREEN_role","Participant GREEN")]):
    SousQuestion.objects.create(question=qm, code=c, libelle=l, ordre=i)

# Justification (texte long) — sur un NOUVEL écran.
Question.objects.create(code="justif", libelle="Justification", type="longtext", longueur=400,
    obligatoire=False, saut_de_page=True, groupe=g1, ordre=1)

# Classement par glisser-déposer — encore un écran.
qd = Question.objects.create(code="classement", libelle="Classez ces aspects par importance",
    type="dragdrop", saut_de_page=True, groupe=g1, ordre=2)
for i,(v,l) in enumerate([("son","Le son"),("image","L'image"),("rythme","Le rythme"),("contenu","Le contenu")]):
    Choix.objects.create(question=qd, valeur=v, libelle=l, ordre=i)

# --- Groupe STANDARD en cartes (sans vidéo) ---
g2 = Groupe.objects.create(titre="Ressenti", portee="standard", ordre=2)
qc = Question.objects.create(code="ressenti", libelle="Quelle ambiance domine ?",
    type="cartes", groupe=g2, ordre=0)
for i,(v,l,d) in enumerate([("calme","Calme","Posé, détendu"),("tendu","Tendu","Stress, urgence"),
                            ("joyeux","Joyeux","Léger, enjoué"),("neutre","Neutre","Sans tonalité marquée")]):
    Choix.objects.create(question=qc, valeur=v, libelle=l, description=d, ordre=i)

CodeAcces.objects.get_or_create(code="demo", defaults={"note": "code individuel de démo"})
CodeAcces.objects.get_or_create(code="ouvert", defaults={"collectif": True, "note": "lien collectif de démo"})
print("Seed OK :", Question.objects.count(), "questions dans", Groupe.objects.count(),
      "groupes. Code : demo — Éditeur : /editeur/")
