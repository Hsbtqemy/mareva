from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("etude", "0002_alter_choix_libelle_alter_choix_valeur"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sousquestion",
            name="code",
            field=models.SlugField(
                blank=True,
                max_length=60,
                unique=True,
                help_text="Identifiant export (ex. BLUE_SQ001). Laissé vide : généré automatiquement depuis le libellé.",
            ),
        ),
    ]
