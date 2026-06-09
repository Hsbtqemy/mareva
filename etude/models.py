"""
Modèles de l'étude.

Schéma clé-valeur pour les réponses :
  - Question : une question du protocole (gérée via l'admin Django)
  - Choix    : options d'une question à choix multiple
  - Enregistrement : un clip vidéo de la banque (+ sous-titres VTT)
  - Participant    : une personne, identifiée par un jeton de session stable
  - Jugement       : une évaluation = (un participant, un enregistrement, un horodatage)
  - Reponse        : une réponse atomique = (un jugement, une question, une valeur)

L'export CSV (voir admin.py) repivote les Reponses en format large :
une ligne par Jugement, une colonne par Question.
"""
import secrets

from django.db import models


class Groupe(models.Model):
    """
    Groupe (section) de questions dans le questionnaire posé autour du clip
    tiré. Sert à organiser l'affichage : titre, consigne, et surtout la mise
    en page (un groupe peut commencer une nouvelle page). Ordre configurable.
    """
    titre = models.CharField(max_length=200, blank=True, help_text="Titre de section affiché au participant (optionnel).")
    consigne = models.TextField(blank=True, help_text="Consigne / texte d'introduction du groupe (optionnel).")
    ordre = models.IntegerField(default=0, help_text="Ordre d'affichage croissant.")
    nouvelle_page = models.BooleanField(
        default=False,
        help_text="Si coché, ce groupe commence une nouvelle page (sinon il suit le précédent sur la même page).",
    )
    active = models.BooleanField(default=True, help_text="Décocher pour masquer le groupe sans le supprimer.")

    class Meta:
        ordering = ["ordre", "id"]

    def __str__(self):
        return self.titre or f"Groupe {self.pk}"


class Media(models.Model):
    """
    Média (audio ou vidéo) attaché à une question. Bibliothèque DISTINCTE du
    vivier de tirage (Enregistrement) : un média de question ne doit jamais
    être tiré comme clip sujet. Servi par la vue protégée media_question().
    """
    VIDEO = "video"
    AUDIO = "audio"
    TYPE_CHOICES = [(VIDEO, "Vidéo"), (AUDIO, "Audio")]

    code = models.SlugField(max_length=60, unique=True, help_text="Identifiant court du média.")
    titre = models.CharField(max_length=200, blank=True, help_text="Usage interne.")
    type_media = models.CharField(max_length=10, choices=TYPE_CHOICES, default=VIDEO)
    fichier = models.CharField(max_length=300, help_text="Chemin relatif sous MEDIA_ROOT, ex. medias/q_voix.mp3")
    vtt = models.CharField(max_length=300, blank=True, help_text="Chemin relatif du sous-titre WebVTT (optionnel).")

    class Meta:
        ordering = ["code"]
        verbose_name = "média de question"
        verbose_name_plural = "médias de question"

    def __str__(self):
        return f"{self.code} ({self.get_type_media_display()})"


class Question(models.Model):
    ECHELLE = "echelle"
    CHOIX = "choix"
    TEXTE = "texte"
    TYPE_CHOICES = [
        (ECHELLE, "Échelle numérique"),
        (CHOIX, "Choix (une ou plusieurs options)"),
        (TEXTE, "Texte libre"),
    ]

    PROFIL = "profil"
    EXTRAIT = "extrait"
    PORTEE_CHOICES = [
        (EXTRAIT, "Par extrait (rattachée à chaque jugement)"),
        (PROFIL, "Profil participant (posée une seule fois)"),
    ]

    code = models.SlugField(
        max_length=40, unique=True,
        help_text="Identifiant court et stable, utilisé comme en-tête de colonne à l'export (ex. q1, age, clarte).",
    )
    libelle = models.CharField(max_length=400, help_text="Texte affiché au participant.")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=ECHELLE)
    aide = models.CharField(max_length=400, blank=True, help_text="Texte d'aide optionnel sous la question.")

    # Organisation et média (gérés dans l'éditeur visuel).
    groupe = models.ForeignKey(
        "Groupe", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions",
        help_text="Groupe (section) auquel appartient la question.",
    )
    media = models.ForeignKey(
        "Media", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions",
        help_text="Média audio/vidéo propre à cette question (optionnel).",
    )

    # Pour le type 'echelle'
    min_val = models.IntegerField(null=True, blank=True)
    max_val = models.IntegerField(null=True, blank=True)
    label_min = models.CharField(max_length=80, blank=True, help_text="Libellé sous la borne basse (ex. Pas du tout clair).")
    label_max = models.CharField(max_length=80, blank=True, help_text="Libellé sous la borne haute (ex. Très clair).")

    # Pour le type 'choix'
    choix_multiple = models.BooleanField(default=False, help_text="Si coché, plusieurs options sélectionnables.")

    portee = models.CharField(
        max_length=10, choices=PORTEE_CHOICES, default=EXTRAIT,
        help_text="« Profil » : posée une fois au participant (âge, genre...). "
                  "« Par extrait » : posée pour chaque extrait évalué.",
    )
    obligatoire = models.BooleanField(default=True)
    ordre = models.IntegerField(default=0, help_text="Ordre dans le groupe (croissant).")
    active = models.BooleanField(default=True, help_text="Décocher pour retirer la question sans la supprimer.")

    class Meta:
        # Tri par groupe puis ordre interne ; les questions sans groupe (legacy)
        # passent en premier (groupe_id NULL).
        ordering = ["groupe__ordre", "ordre", "id"]

    def __str__(self):
        return f"[{self.code}] {self.libelle[:50]}"

    @property
    def plage(self):
        """Liste des graduations pour une question d'échelle (ex. [1,2,3,4,5,6,7])."""
        if self.type == self.ECHELLE and self.min_val is not None and self.max_val is not None:
            return range(self.min_val, self.max_val + 1)
        return []


class Choix(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choix")
    valeur = models.CharField(max_length=80, help_text="Valeur enregistrée (ex. voix).")
    libelle = models.CharField(max_length=200, help_text="Texte affiché (ex. Une voix humaine).")
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ["ordre", "id"]

    def __str__(self):
        return f"{self.question.code} → {self.libelle}"


class Enregistrement(models.Model):
    code = models.SlugField(max_length=60, unique=True, help_text="Identifiant du clip (export).")
    titre = models.CharField(max_length=200, blank=True, help_text="Usage interne uniquement, non montré au participant.")
    # On stocke un chemin RELATIF à MEDIA_ROOT. Les fichiers ne sont PAS servis
    # directement : l'accès passe par une vue protégée (voir views.media_protege).
    fichier_video = models.CharField(max_length=300, help_text="Chemin relatif sous MEDIA_ROOT, ex. videos/clip_042.mp4")
    fichier_vtt = models.CharField(max_length=300, blank=True, help_text="Chemin relatif du sous-titre WebVTT, ex. videos/clip_042.vtt")

    categorie = models.CharField(max_length=80, blank=True, help_text="Métadonnée libre pour l'analyse (condition, source...).")
    actif = models.BooleanField(default=True, help_text="Décocher pour exclure du tirage.")
    nb_evaluations = models.PositiveIntegerField(default=0, help_text="Compteur mis à jour à chaque jugement (sert au tirage pondéré).")

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} (n={self.nb_evaluations})"


class Participant(models.Model):
    jeton = models.CharField(max_length=64, unique=True, db_index=True, help_text="Identifiant anonyme stable de session.")
    consentement = models.BooleanField(default=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    # Métadonnées d'écoute potentiellement utiles à l'analyse.
    user_agent = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"P-{self.jeton[:8]}"


class CodeAcces(models.Model):
    """
    Code d'accès individuel (un code = un participant). Le chercheur génère un
    lot de codes dans l'admin et en distribue un par personne invitée. À la
    première saisie, le code est lié à un Participant ; les saisies suivantes
    du même code restaurent la session de CE participant (reprise possible).

    Le code n'est jamais exporté avec les données : la correspondance
    code → personne reste hors de l'outil (chez le chercheur).
    """
    code = models.CharField(
        max_length=64, unique=True, db_index=True,
        blank=True,  # laissé vide à la création → généré automatiquement
        help_text="Code remis à un participant. Laisser vide pour en générer un automatiquement.",
    )
    note = models.CharField(
        max_length=200, blank=True,
        help_text="Repère interne (destinataire, vague d'envoi...). Jamais montré au participant.",
    )
    collectif = models.BooleanField(
        default=False,
        help_text="Si coché : lien collectif à partager largement (chaque visiteur "
                  "devient un nouveau participant). Sinon : code individuel lié à une personne.",
    )
    actif = models.BooleanField(default=True, help_text="Décocher pour révoquer l'accès.")
    cree_le = models.DateTimeField(auto_now_add=True)
    participant = models.OneToOneField(
        "Participant", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="code_acces",
        help_text="Participant associé, pour un code individuel (vide pour un lien collectif).",
    )

    class Meta:
        ordering = ["code"]
        verbose_name = "code d'accès"
        verbose_name_plural = "codes d'accès"

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = secrets.token_urlsafe(6)
        super().save(*args, **kwargs)


class Jugement(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="jugements")
    enregistrement = models.ForeignKey(Enregistrement, on_delete=models.PROTECT, related_name="jugements")
    debut = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True, help_text="Horodatage de soumission des réponses.")

    class Meta:
        # Un participant ne juge pas deux fois le même enregistrement.
        unique_together = [("participant", "enregistrement")]
        ordering = ["debut"]

    def __str__(self):
        return f"{self.participant} × {self.enregistrement.code}"


class Reponse(models.Model):
    jugement = models.ForeignKey(Jugement, on_delete=models.CASCADE, related_name="reponses")
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    # Valeur stockée en texte ; pour les choix multiples, valeurs jointes par '|'.
    valeur = models.TextField(blank=True)

    class Meta:
        unique_together = [("jugement", "question")]

    def __str__(self):
        return f"{self.jugement_id}/{self.question.code} = {self.valeur[:30]}"


class ReponseProfil(models.Model):
    """
    Réponse à une question de PORTÉE PROFIL : décrit le participant (âge,
    genre...), posée une seule fois et stockée au niveau du participant, pas
    sur un jugement (qui ne concerne qu'un extrait).
    """
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="reponses_profil")
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    valeur = models.TextField(blank=True)

    class Meta:
        unique_together = [("participant", "question")]

    def __str__(self):
        return f"{self.participant_id}/{self.question.code} = {self.valeur[:30]}"


class Configuration(models.Model):
    """
    Configuration de l'étude, éditable dans l'admin (un seul enregistrement).
    Centralise les textes affichés au participant pour que l'étude soit
    neutre et entièrement paramétrable, sans rien coder en dur.
    """
    nom_etude = models.CharField(
        max_length=200, default="Étude",
        help_text="Nom de l'étude (titres de page, en-tête de l'administration).",
    )
    titre_accueil = models.CharField(
        max_length=200, default="Bienvenue",
        help_text="Titre affiché sur la page de consentement.",
    )
    description = models.TextField(
        default=(
            "Vous allez participer à une étude. Lisez les informations ci-dessous, "
            "puis indiquez votre consentement pour commencer.\n\n"
            "Vos réponses sont enregistrées de façon anonyme et utilisées uniquement "
            "dans le cadre de cette recherche."
        ),
        help_text="Texte de présentation / consentement (sauts de ligne respectés).",
    )
    bouton_consentement = models.CharField(
        max_length=100, default="Je consens et je commence",
        help_text="Libellé du bouton de consentement.",
    )
    intro_profil = models.TextField(
        blank=True,
        default=(
            "Ces questions ne sont posées qu'une seule fois et servent uniquement "
            "aux statistiques de l'étude. Vos réponses restent anonymes."
        ),
        help_text="Texte d'introduction de la page de profil (questions posées une fois).",
    )
    texte_remerciement = models.TextField(
        default=(
            "Merci pour votre participation. Vos réponses ont bien été enregistrées ; "
            "vous pouvez fermer cette page."
        ),
        help_text="Texte de la page de fin.",
    )

    class Meta:
        verbose_name = "configuration de l'étude"
        verbose_name_plural = "configuration de l'étude"

    def __str__(self):
        return self.nom_etude

    def save(self, *args, **kwargs):
        # Singleton : on force toujours la même ligne.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def charger(cls):
        """Retourne l'unique configuration (la crée avec les valeurs par défaut si besoin)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
