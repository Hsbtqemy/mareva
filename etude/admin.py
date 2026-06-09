"""
Admin Django : construction des questions, agencement, données et export.

La construction d'une question (type, média, options, échelle) se fait ici
(formulaire standard + ChoixInline) ; l'agencement (ordre, groupes, pages) se
fait dans l'éditeur visuel (/editeur/).

L'action « Exporter en CSV » sur les Passages repivote le stockage clé-valeur
en format large : une ligne par passage (participant × groupe), colonnes profil
(recopiées) puis colonnes des questions standard.
"""
import csv
import secrets

from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path, reverse

from .models import (
    Question, Choix, SousQuestion, Groupe, Media,
    Participant, Passage, Reponse, ReponseProfil, CodeAcces, Configuration,
)


class ChoixInline(admin.TabularInline):
    model = Choix
    extra = 3
    fields = ("ordre", "valeur", "libelle", "description")


class SousQuestionInline(admin.TabularInline):
    model = SousQuestion
    extra = 0
    fields = ("ordre", "code", "libelle")


@admin.register(Groupe)
class GroupeAdmin(admin.ModelAdmin):
    list_display = ("titre", "portee", "media", "inclure_tirage", "ordre", "active", "nb_evaluations")
    list_editable = ("portee", "inclure_tirage", "ordre", "active")
    list_filter = ("portee", "active")
    readonly_fields = ("nb_evaluations",)


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ("code", "type_media", "fichier", "titre")
    list_filter = ("type_media",)
    search_fields = ("code", "titre")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "type", "groupe", "media", "obligatoire", "saut_de_page", "ordre", "active")
    list_editable = ("ordre", "active")
    list_filter = ("type", "active", "groupe")
    list_select_related = ("groupe", "media")
    search_fields = ("code", "libelle")
    inlines = [ChoixInline, SousQuestionInline]
    fieldsets = (
        (None, {"fields": ("code", "libelle", "type", "aide", "groupe", "media")}),
        ("Options d'affichage", {"fields": ("obligatoire", "saut_de_page", "melanger", "ordre", "active")}),
        ("Échelle", {"fields": ("min_val", "max_val", "label_min", "label_max"), "classes": ("collapse",)}),
        ("Texte (longueur)", {"fields": ("longueur",), "classes": ("collapse",)}),
        ("Choix / cartes", {"fields": ("choix_multiple",), "classes": ("collapse",),
                            "description": "Les options se règlent dans « Choix » ci-dessous. "
                                           "Pour une matrice : « Choix » = catégories (colonnes), "
                                           "« Sous-questions » = lignes."}),
    )


class ReponseInline(admin.TabularInline):
    model = Reponse
    extra = 0
    readonly_fields = ("question", "valeur")
    can_delete = False


@admin.register(Passage)
class PassageAdmin(admin.ModelAdmin):
    list_display = ("id", "participant", "groupe", "debut", "fin")
    list_filter = ("groupe", "debut")
    search_fields = ("participant__jeton", "groupe__titre")
    inlines = [ReponseInline]
    actions = ["exporter_csv"]

    @staticmethod
    def _colonnes(questions):
        """Une colonne par question, sauf matrice → une colonne par sous-question (code)."""
        cols = []
        for q in questions:
            if q.type == Question.MATRICE:
                cols.extend(sq.code for sq in q.sous_questions.all())
            else:
                cols.append(q.code)
        return cols

    @staticmethod
    def _par_code(reponses):
        """Réponses indexées par code de colonne (sous-question si matrice, sinon question)."""
        d = {}
        for r in reponses:
            sq = getattr(r, "sous_question", None)
            d[sq.code if sq else r.question.code] = r.valeur
        return d

    @admin.action(description="Exporter en CSV (format large, repivoté)")
    def exporter_csv(self, request, queryset):
        toutes = list(
            Question.objects.select_related("groupe").prefetch_related("sous_questions")
            .order_by("groupe__ordre", "ordre", "id")
        )
        q_profil = [q for q in toutes if q.groupe and q.groupe.portee == Groupe.PROFIL]
        q_standard = [q for q in toutes if not (q.groupe and q.groupe.portee == Groupe.PROFIL)]
        cols_profil = self._colonnes(q_profil)
        cols_standard = self._colonnes(q_standard)

        reponse = HttpResponse(content_type="text/csv")
        reponse["Content-Disposition"] = 'attachment; filename="passages.csv"'
        writer = csv.writer(reponse)
        writer.writerow([
            "id_passage", "jeton_participant", "consentement",
            "code_groupe", "debut", "fin",
        ] + cols_profil + cols_standard)

        queryset = queryset.select_related("participant", "groupe").prefetch_related(
            "reponses__question", "reponses__sous_question",
            "participant__reponses_profil__question",
        )
        for p in queryset:
            par_reponse = self._par_code(p.reponses.all())
            par_profil = self._par_code(p.participant.reponses_profil.all())
            ligne = [
                p.id, p.participant.jeton, p.participant.consentement,
                p.groupe.titre or p.groupe_id,
                p.debut.isoformat(), p.fin.isoformat() if p.fin else "",
            ] + [par_profil.get(c, "") for c in cols_profil] \
              + [par_reponse.get(c, "") for c in cols_standard]
            writer.writerow(ligne)
        return reponse


@admin.register(CodeAcces)
class CodeAccesAdmin(admin.ModelAdmin):
    """
    Codes d'accès individuels ou liens collectifs. Bouton « Générer 20 codes »
    sur la liste ; ajout manuel possible (code vide → généré automatiquement).
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
            path("generer/", self.admin_site.admin_view(self.generer), name="etude_codeacces_generer"),
        ]
        return custom + super().get_urls()

    def generer(self, request):
        n = 20
        CodeAcces.objects.bulk_create([CodeAcces(code=secrets.token_urlsafe(6)) for _ in range(n)])
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
    """Configuration unique de l'étude : textes affichés et paramètres de déroulé."""

    def has_add_permission(self, request):
        return not Configuration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# En-têtes neutres ; l'affichage reprend le nom de l'étude (base_site.html).
admin.site.site_header = "Administration"
admin.site.site_title = "Administration"
admin.site.index_title = "Gestion de l'étude"
