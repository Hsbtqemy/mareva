"""
Admin Django : gestion du contenu (questions, banque vidéo) et des données.

Point clé : l'action 'Exporter en CSV' sur les Jugements repivote le stockage
clé-valeur (table Reponse) en format large : une ligne par jugement, une
colonne par question (en utilisant Question.code comme en-tête).
"""
import csv
import secrets

from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path, reverse

from .models import (
    Question, Choix, Groupe, Media, Enregistrement,
    Participant, Jugement, Reponse, ReponseProfil, CodeAcces, Configuration,
)


class ChoixInline(admin.TabularInline):
    model = Choix
    extra = 3


@admin.register(Groupe)
class GroupeAdmin(admin.ModelAdmin):
    list_display = ("titre", "ordre", "nouvelle_page", "active")
    list_editable = ("ordre", "nouvelle_page", "active")


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ("code", "type_media", "fichier", "titre")
    list_filter = ("type_media",)
    search_fields = ("code", "titre")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "type", "portee", "groupe", "media", "obligatoire", "ordre", "active")
    list_editable = ("ordre", "active")
    list_filter = ("portee", "type", "active", "groupe")
    list_select_related = ("groupe", "media")
    search_fields = ("code", "libelle")
    inlines = [ChoixInline]


@admin.register(Enregistrement)
class EnregistrementAdmin(admin.ModelAdmin):
    list_display = ("code", "categorie", "nb_evaluations", "actif")
    list_editable = ("actif",)
    list_filter = ("categorie", "actif")
    search_fields = ("code", "titre")
    readonly_fields = ("nb_evaluations",)


class ReponseInline(admin.TabularInline):
    model = Reponse
    extra = 0
    readonly_fields = ("question", "valeur")
    can_delete = False


@admin.register(Jugement)
class JugementAdmin(admin.ModelAdmin):
    list_display = ("id", "participant", "enregistrement", "debut", "fin")
    list_filter = ("enregistrement__categorie", "debut")
    search_fields = ("participant__jeton", "enregistrement__code")
    inlines = [ReponseInline]
    actions = ["exporter_csv"]

    @admin.action(description="Exporter en CSV (format large, repivoté)")
    def exporter_csv(self, request, queryset):
        # Deux séries de colonnes, dans l'ordre du questionnaire :
        #   - profil    : réponses du participant (recopiées sur chaque ligne)
        #   - par extrait : réponses propres au jugement
        toutes = Question.objects.order_by("groupe__ordre", "ordre", "id")
        codes_profil = [q.code for q in toutes if q.portee == Question.PROFIL]
        codes_extrait = [q.code for q in toutes if q.portee != Question.PROFIL]

        reponse = HttpResponse(content_type="text/csv")
        reponse["Content-Disposition"] = 'attachment; filename="jugements.csv"'
        writer = csv.writer(reponse)

        entete = [
            "id_jugement", "jeton_participant", "consentement",
            "code_enregistrement", "categorie", "debut", "fin",
        ] + codes_profil + codes_extrait
        writer.writerow(entete)

        # Pré-charge réponses d'extrait ET réponses de profil pour éviter N+1.
        queryset = queryset.select_related("participant", "enregistrement").prefetch_related(
            "reponses__question", "participant__reponses_profil__question",
        )

        for j in queryset:
            par_extrait = {r.question.code: r.valeur for r in j.reponses.all()}
            par_profil = {r.question.code: r.valeur for r in j.participant.reponses_profil.all()}
            ligne = [
                j.id,
                j.participant.jeton,
                j.participant.consentement,
                j.enregistrement.code,
                j.enregistrement.categorie,
                j.debut.isoformat(),
                j.fin.isoformat() if j.fin else "",
            ] + [par_profil.get(c, "") for c in codes_profil] \
              + [par_extrait.get(c, "") for c in codes_extrait]
            writer.writerow(ligne)

        return reponse


@admin.register(CodeAcces)
class CodeAccesAdmin(admin.ModelAdmin):
    """
    Gestion des codes d'accès individuels. Bouton « Générer des codes » sur la
    liste (voir templates/admin/etude/codeacces/change_list.html) pour créer un
    lot d'un coup, sans coder. Ajout manuel possible aussi : laisser le champ
    code vide le fait générer automatiquement.
    """
    list_display = ("code", "collectif", "lien", "note", "actif", "participant", "cree_le")
    list_editable = ("collectif", "actif")
    list_filter = ("collectif", "actif")
    search_fields = ("code", "note")
    readonly_fields = ("lien", "participant", "cree_le")
    change_list_template = "admin/etude/codeacces/change_list.html"

    @admin.display(description="Lien à partager")
    def lien(self, obj):
        if not obj.pk:
            return "(enregistrer d'abord)"
        return reverse("acces_lien", args=[obj.code])

    def get_urls(self):
        custom = [
            path(
                "generer/",
                self.admin_site.admin_view(self.generer),
                name="etude_codeacces_generer",
            ),
        ]
        return custom + super().get_urls()

    def generer(self, request):
        """Crée un lot de 20 codes aléatoires (uniques)."""
        n = 20
        CodeAcces.objects.bulk_create(
            [CodeAcces(code=secrets.token_urlsafe(6)) for _ in range(n)]
        )
        self.message_user(request, f"{n} codes d'accès générés.", messages.SUCCESS)
        return redirect("admin:etude_codeacces_changelist")


class ReponseProfilInline(admin.TabularInline):
    model = ReponseProfil
    extra = 0
    readonly_fields = ("question", "valeur")
    can_delete = False


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("__str__", "consentement", "cree_le")
    inlines = [ReponseProfilInline]


@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    """Configuration unique de l'étude (textes affichés, nom...)."""

    def has_add_permission(self, request):
        # Singleton : pas d'ajout si une configuration existe déjà.
        return not Configuration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# En-têtes neutres ; l'affichage réel reprend le nom de l'étude défini en
# configuration (voir templates/admin/base_site.html).
admin.site.site_header = "Administration"
admin.site.site_title = "Administration"
admin.site.index_title = "Gestion de l'étude"
