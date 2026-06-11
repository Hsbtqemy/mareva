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
    # Accès média protégé d'une question.
    path("media-question/<str:kind>/<str:code>/", views.media_question, name="media_question"),
    # Éditeur visuel du questionnaire (réservé au staff).
    path("editeur/", editeur.editeur, name="editeur"),
    path("editeur/groupe/", editeur.api_groupe, name="editeur_groupe"),
    path("editeur/groupe/<int:gid>/supprimer/", editeur.api_groupe_supprimer, name="editeur_groupe_supprimer"),
    path("editeur/question/", editeur.api_question, name="editeur_question"),
    path("editeur/question/<int:qid>/supprimer/", editeur.api_question_supprimer, name="editeur_question_supprimer"),
    path("editeur/question/<int:qid>/dupliquer/", editeur.api_question_dupliquer, name="editeur_question_dupliquer"),
    path("editeur/groupe/<int:gid>/dupliquer/", editeur.api_groupe_dupliquer, name="editeur_groupe_dupliquer"),
    path("editeur/ordre/", editeur.api_reordonner, name="editeur_ordre"),
    # Construction dans l'interface du site.
    path("editeur/q/nouveau/", editeur.question_form, name="editeur_question_nouveau"),
    path("editeur/q/<int:qid>/", editeur.question_form, name="editeur_question_form"),
    path("editeur/medias/", editeur.medias, name="editeur_medias"),
    path("editeur/medias/<int:mid>/supprimer/", editeur.media_supprimer, name="editeur_media_supprimer"),
    path("editeur/parametres/", editeur.parametres, name="editeur_parametres"),
    path("editeur/resultats/", editeur.resultats, name="editeur_resultats"),
    path("editeur/export/passages/", editeur.export_passages, name="editeur_export_passages"),
    path("editeur/export/participants/", editeur.export_participants, name="editeur_export_participants"),
    path("editeur/groupe/<int:gid>/apercu/", editeur.apercu_groupe, name="editeur_apercu_groupe"),
    path("editeur/participants/supprimer/", editeur.participants_supprimer, name="editeur_participants_supprimer"),
    path("editeur/participants/vider/", editeur.participants_vider, name="editeur_participants_vider"),
]
