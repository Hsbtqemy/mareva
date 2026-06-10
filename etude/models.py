"""
Modèles de l'étude.

Principe : le questionnaire est un ensemble de GROUPES de questions.
  - Un groupe « profil » est posé une seule fois (âge, genre...).
  - Les groupes « standard » forment le pool tiré dans la boucle : on propose au
    participant un groupe non encore répondu (aléatoire ou ordre fixe) tant qu'il
    souhaite continuer.

Chaque question porte son propre média (audio/vidéo) ; un groupe n'a pas de
fichier commun. Un groupe peut être découpé en plusieurs écrans (« Suivant »)
via le drapeau `saut_de_page` de ses questions.

  - Groupe        : une unité de questions (profil ou standard)
  - Question      : une question (type, média, options) dans un groupe
  - Choix         : options d'une question à choix
  - Media         : fichier audio/vidéo rattaché à une question
  - Participant   : une personne, identifiée par un jeton de session stable
  - Passage       : un participant a répondu à un groupe (= une itération)
  - Reponse       : réponse atomique (un passage, une question, une valeur)
  - ReponseProfil : réponse de profil (un participant, une question)
  - Configuration : paramètres et textes de l'étude (singleton)

L'export CSV (voir admin.py) repivote les réponses en format large.
"""
import secrets

from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.text import slugify
from django.db.models.signals import post_delete
from django.dispatch import receiver


class Groupe(models.Model):
    """
    Groupe de questions = unité tirée par la boucle.

    `portee` distingue le groupe de profil (posé une fois) des groupes standard
    (pool de tirage). `inclure_tirage` permet d'exclure ponctuellement un groupe
    standard du pool. `nb_evaluations` alimente le tirage pondéré.
    """
    PROFIL = "profil"
    STANDARD = "standard"
    PORTEE_CHOICES = [
        (STANDARD, "Standard (tiré dans la boucle)"),
        (PROFIL, "Profil (posé une seule fois au début)"),
    ]

    titre = models.CharField(max_length=200, blank=True, help_text="Titre de section affiché au participant (optionnel).")
    consigne = models.TextField(blank=True, help_text="Consigne / introduction du groupe (optionnel).")
    media = models.ForeignKey(
        "Media", on_delete=models.SET_NULL, null=True, blank=True, related_name="groupes",
        help_text="Vidéo unique du groupe, affichée en permanence à gauche (optionnel).",
    )
    portee = models.CharField(
        max_length=10, choices=PORTEE_CHOICES, default=STANDARD,
        help_text="« Profil » : posé une seule fois au début. « Standard » : tiré dans la boucle.",
    )
    inclure_tirage = models.BooleanField(
        default=True,
        help_text="Si décoché, ce groupe standard est exclu du tirage (utile pour une intro épinglée).",
    )
    ordre = models.IntegerField(default=0, help_text="Ordre (croissant) ; utilisé si le tirage n'est pas aléatoire.")
    active = models.BooleanField(default=True, help_text="Décocher pour masquer le groupe sans le supprimer.")
    nb_evaluations = models.PositiveIntegerField(default=0, help_text="Nombre de fois répondu (sert au tirage pondéré).")

    class Meta:
        ordering = ["ordre", "id"]

    def __str__(self):
        return self.titre or f"Groupe {self.pk}"


class Media(models.Model):
    """
    Média (audio ou vidéo) attaché à une question. Servi par la vue protégée
    media_question().
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
        verbose_name = "média"
        verbose_name_plural = "médias"

    def __str__(self):
        return f"{self.code} ({self.get_type_media_display()})"


@receiver(post_delete, sender=Media)
def _supprimer_fichiers_media(sender, instance, **kwargs):
    """
    Supprime du disque le fichier (et le VTT) d'un Média supprimé, sauf s'il est
    encore référencé par un autre Média (cas d'un fichier partagé). Couvre toutes
    les voies de suppression (page Médias, admin, suppression en lot).
    """
    storage = FileSystemStorage()  # lit settings.MEDIA_ROOT à l'appel
    for chemin in filter(None, {instance.fichier, instance.vtt}):
        encore_utilise = (
            Media.objects.filter(fichier=chemin).exists()
            or Media.objects.filter(vtt=chemin).exists()
        )
        if encore_utilise:
            continue
        try:
            storage.delete(chemin)
        except Exception:
            pass  # fichier déjà absent / chemin invalide : on ignore


class Question(models.Model):
    ECHELLE = "echelle"
    CHOIX = "choix"
    TEXTE = "texte"
    LONGTEXT = "longtext"
    CARTES = "cartes"
    MATRICE = "matrice"
    DRAGDROP = "dragdrop"
    TYPE_CHOICES = [
        (ECHELLE, "Échelle numérique"),
        (CHOIX, "Choix (cases / boutons radio)"),
        (CARTES, "Cartes (choix en cartes détaillées)"),
        (MATRICE, "Matrice (sous-questions × catégories)"),
        (DRAGDROP, "Classement par glisser-déposer"),
        (TEXTE, "Texte court"),
        (LONGTEXT, "Texte long"),
    ]

    code = models.SlugField(
        max_length=40, unique=True,
        help_text="Identifiant court et stable, utilisé comme en-tête de colonne à l'export (ex. q1, age, clarte).",
    )
    libelle = models.CharField(max_length=400, help_text="Texte affiché au participant.")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=ECHELLE)
    aide = models.CharField(max_length=400, blank=True, help_text="Texte d'aide optionnel sous la question.")

    groupe = models.ForeignKey(
        "Groupe", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions",
        help_text="Groupe auquel appartient la question.",
    )
    media = models.ForeignKey(
        "Media", on_delete=models.SET_NULL, null=True, blank=True, related_name="questions",
        help_text="Média audio/vidéo propre à cette question (optionnel).",
    )

    # Pour le type 'echelle'
    min_val = models.IntegerField(null=True, blank=True)
    max_val = models.IntegerField(null=True, blank=True)
    label_min = models.CharField(max_length=80, blank=True, help_text="Libellé sous la borne basse (ex. Pas du tout).")
    label_max = models.CharField(max_length=80, blank=True, help_text="Libellé sous la borne haute (ex. Tout à fait).")

    # Pour les types 'choix' / 'cartes'
    choix_multiple = models.BooleanField(default=False, help_text="Si coché, plusieurs options sélectionnables (choix / cartes).")
    melanger = models.BooleanField(
        default=False,
        help_text="Mélanger l'ordre des options / catégories (rotation) pour chaque participant.",
    )
    # Pour les types 'texte' / 'longtext' : longueur indicative (lignes / max).
    longueur = models.IntegerField(null=True, blank=True, help_text="Longueur indicative pour les champs texte (optionnel).")

    obligatoire = models.BooleanField(default=True)
    saut_de_page = models.BooleanField(
        default=False,
        help_text="Si coché, cette question commence un nouvel écran (un bouton « Suivant » apparaît avant elle).",
    )
    ordre = models.IntegerField(default=0, help_text="Ordre dans le groupe (croissant).")
    active = models.BooleanField(default=True, help_text="Décocher pour retirer la question sans la supprimer.")

    class Meta:
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
    """Option d'une question (choix / cartes) ou catégorie (colonne d'une matrice)."""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choix")
    valeur = models.CharField(
        max_length=80, blank=True,
        help_text="Valeur enregistrée à l'export. Laisser vide = reprend le libellé "
                  "(utile surtout pour des codes, ex. AO01).",
    )
    libelle = models.CharField(max_length=200, help_text="Texte affiché au participant (ex. Oui, tout à fait).")
    description = models.CharField(max_length=300, blank=True, help_text="Détail affiché sous le libellé (cartes).")
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ["ordre", "id"]

    def __str__(self):
        return f"{self.question.code} → {self.libelle}"

    def save(self, *args, **kwargs):
        if not self.valeur and self.libelle:
            self.valeur = self.libelle[:80]
        super().save(*args, **kwargs)


class SousQuestion(models.Model):
    """
    Ligne d'une question matricielle (ex. « Primary Role », « Secondary Role »).
    Son `code` sert d'en-tête de colonne à l'export (équivalent du varName).
    """
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="sous_questions")
    code = models.SlugField(max_length=60, unique=True, blank=True, help_text="Identifiant export (ex. BLUE_SQ001). Laissé vide : généré automatiquement depuis le libellé.")
    libelle = models.CharField(max_length=300, help_text="Intitulé de la ligne (ex. Primary Role).")
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ["ordre", "id"]

    def save(self, *args, **kwargs):
        if not self.code:
            base = (slugify(self.libelle) or "sq")[:55]
            code, i = base, 2
            while SousQuestion.objects.filter(code=code).exclude(pk=self.pk).exists():
                suffixe = f"-{i}"
                code = base[:60 - len(suffixe)] + suffixe
                i += 1
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.question.code} / {self.code}"


class Participant(models.Model):
    jeton = models.CharField(max_length=64, unique=True, db_index=True, help_text="Identifiant anonyme stable de session.")
    consentement = models.BooleanField(default=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    user_agent = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"P-{self.jeton[:8]}"


class CodeAcces(models.Model):
    """
    Code d'accès individuel (un code = un participant) ou lien collectif.
    Le code n'est jamais exporté : la correspondance code → personne reste
    hors de l'outil (chez le chercheur).
    """
    code = models.CharField(
        max_length=64, unique=True, db_index=True, blank=True,
        help_text="Code remis à un participant. Laisser vide pour en générer un automatiquement.",
    )
    note = models.CharField(
        max_length=200, blank=True,
        help_text="Repère interne (destinataire, vague d'envoi...). Jamais montré au participant.",
    )
    collectif = models.BooleanField(
        default=False,
        help_text="Si coché : lien collectif à partager largement (chaque visiteur devient un "
                  "nouveau participant). Sinon : code individuel lié à une personne.",
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


class Passage(models.Model):
    """
    Un participant a abordé un groupe (une itération de la boucle). `fin` non
    nul = groupe terminé. Un participant ne répond qu'une fois à un groupe.
    """
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="passages")
    groupe = models.ForeignKey(Groupe, on_delete=models.PROTECT, related_name="passages")
    debut = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True, help_text="Horodatage de fin du groupe.")

    class Meta:
        unique_together = [("participant", "groupe")]
        ordering = ["debut"]

    def __str__(self):
        return f"{self.participant} × {self.groupe}"


class Reponse(models.Model):
    passage = models.ForeignKey(Passage, on_delete=models.CASCADE, related_name="reponses")
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    # Pour une matrice : une réponse par sous-question (ligne) ; sinon null.
    sous_question = models.ForeignKey(
        SousQuestion, on_delete=models.CASCADE, null=True, blank=True, related_name="reponses",
    )
    # Valeur en texte ; choix multiples / classement : valeurs jointes par '|'.
    valeur = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["passage", "question", "sous_question"],
                name="reponse_unique_passage_question_sousq",
            ),
        ]

    def __str__(self):
        cle = self.sous_question.code if self.sous_question_id else self.question.code
        return f"{self.passage_id}/{cle} = {self.valeur[:30]}"


class ReponseProfil(models.Model):
    """
    Réponse à une question d'un groupe de PROFIL : décrit le participant
    (âge, genre...), posée une seule fois et stockée sur le participant.
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
    Configuration de l'étude, éditable dans l'admin (un seul enregistrement) :
    textes affichés et paramètres de déroulé (aléatoire, nombre de groupes).
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
        help_text="Texte d'introduction de la page de profil.",
    )
    texte_remerciement = models.TextField(
        default=(
            "Merci pour votre participation. Vos réponses ont bien été enregistrées ; "
            "vous pouvez fermer cette page."
        ),
        help_text="Texte de la page de fin.",
    )

    # --- Paramètres de déroulé ---
    ordre_groupes_aleatoire = models.BooleanField(
        default=True,
        help_text="Si coché, les groupes sont proposés dans un ordre aléatoire (pondéré pour "
                  "équilibrer la couverture). Sinon, dans leur ordre défini.",
    )
    max_groupes = models.PositiveIntegerField(
        default=0,
        help_text="Nombre maximal de groupes proposés à un participant (0 = illimité, "
                  "jusqu'à épuisement).",
    )

    class Meta:
        verbose_name = "configuration de l'étude"
        verbose_name_plural = "configuration de l'étude"

    def __str__(self):
        return self.nom_etude

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def charger(cls):
        """Retourne l'unique configuration (la crée avec les valeurs par défaut si besoin)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
