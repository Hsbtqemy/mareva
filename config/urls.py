from django.contrib import admin
from django.urls import path

from etude import views
from etude import editeur

urlpatterns = [
    path("admin/", admin.site.urls),
    path("acces/", views.acces, name="acces"),
    path("acces/<str:code>/", views.acces_lien, name="acces_lien"),
    path("", views.index, name="index"),
    path("profil/", views.profil, name="profil"),
    path("profil/soumettre/", views.soumettre_profil, name="soumettre_profil"),
    path("tache/", views.tache, name="tache"),
    path("soumettre/", views.soumettre, name="soumettre"),
    path("fin/", views.fin, name="fin"),
    # Accès média protégé : clip sujet et média de question.
    path("media/<str:kind>/<str:code>/", views.media_protege, name="media_protege"),
    path("media-question/<str:kind>/<str:code>/", views.media_question, name="media_question"),
    # Éditeur visuel du questionnaire (réservé au staff).
    path("editeur/", editeur.editeur, name="editeur"),
    path("editeur/groupe/", editeur.api_groupe, name="editeur_groupe"),
    path("editeur/groupe/<int:gid>/supprimer/", editeur.api_groupe_supprimer, name="editeur_groupe_supprimer"),
    path("editeur/question/", editeur.api_question, name="editeur_question"),
    path("editeur/question/<int:qid>/supprimer/", editeur.api_question_supprimer, name="editeur_question_supprimer"),
    path("editeur/ordre/", editeur.api_reordonner, name="editeur_ordre"),
]
