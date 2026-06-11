"""
Formulaires de l'éditeur (construction du questionnaire dans l'interface du site).
"""
from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory

from .models import Question, Choix, SousQuestion, Media, Configuration


class StyleMixin:
    """Ajoute une classe CSS aux widgets pour le style du site."""
    def _styler(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = (w.attrs.get("class", "") + " case").strip()
            else:
                w.attrs["class"] = (w.attrs.get("class", "") + " champ").strip()


class QuestionForm(StyleMixin, forms.ModelForm):
    class Meta:
        model = Question
        fields = [
            "groupe", "code", "libelle", "type", "aide", "media",
            "obligatoire", "saut_de_page", "melanger", "active",
            "min_val", "max_val", "label_min", "label_max",
            "choix_multiple", "longueur",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._styler()


class MediaForm(StyleMixin, forms.ModelForm):
    class Meta:
        model = Media
        fields = ["code", "titre", "type_media", "fichier", "vtt"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._styler()


class MediaUploadForm(StyleMixin, forms.Form):
    """Téléversement d'un fichier média (enregistré sous MEDIA_ROOT)."""
    TAILLE_MAX = 1024 * 1024 * 1024  # 1 Go

    fichier = forms.FileField(label="Fichier vidéo ou audio")
    vtt = forms.FileField(label="Sous-titres .vtt (optionnel)", required=False)
    code = forms.SlugField(label="Code (optionnel)", required=False)
    titre = forms.CharField(label="Titre interne (optionnel)", required=False, max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._styler()

    def clean_fichier(self):
        f = self.cleaned_data["fichier"]
        if f.size > self.TAILLE_MAX:
            raise forms.ValidationError("Fichier trop volumineux (maximum 1 Go).")
        return f

    def clean_vtt(self):
        f = self.cleaned_data.get("vtt")
        if f and not f.name.lower().endswith(".vtt"):
            raise forms.ValidationError("Le sous-titre doit être un fichier .vtt.")
        return f


class ConfigurationForm(StyleMixin, forms.ModelForm):
    class Meta:
        model = Configuration
        fields = [
            "nom_etude", "titre_accueil", "description", "bouton_consentement",
            "intro_profil", "texte_remerciement",
            "continuer_titre", "continuer_texte_suite",
            "continuer_bouton_continuer", "continuer_bouton_arreter",
            "continuer_texte_fin", "continuer_bouton_terminer",
            "ordre_groupes_aleatoire", "max_groupes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._styler()


ChoixFormSet = inlineformset_factory(
    Question, Choix,
    fields=["ordre", "valeur", "libelle", "description"],
    extra=0, can_delete=True,
)

SousQuestionFormSet = inlineformset_factory(
    Question, SousQuestion,
    fields=["ordre", "code", "libelle"],
    extra=0, can_delete=True,
)
