from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models
import django.db.models.deletion


def move_dimensions_to_sections(apps, schema_editor):
	Aula = apps.get_model("core", "Aula")
	AulaSeccion = apps.get_model("core", "AulaSeccion")
	database = schema_editor.connection.alias

	for aula in Aula.objects.using(database).all().iterator():
		if aula.largo_m is not None and aula.ancho_m is not None:
			AulaSeccion.objects.using(database).create(
				aula_id=aula.pk,
				numero=1,
				largo_m=aula.largo_m,
				ancho_m=aula.ancho_m,
			)


def move_first_section_back(apps, schema_editor):
	Aula = apps.get_model("core", "Aula")
	AulaSeccion = apps.get_model("core", "AulaSeccion")
	database = schema_editor.connection.alias

	for section in AulaSeccion.objects.using(database).filter(numero=1).iterator():
		Aula.objects.using(database).filter(pk=section.aula_id).update(
			largo_m=section.largo_m,
			ancho_m=section.ancho_m,
		)


class Migration(migrations.Migration):
	dependencies = [
		("core", "0002_normalize_room_metrics"),
	]

	operations = [
		migrations.CreateModel(
			name="AulaSeccion",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("numero", models.PositiveSmallIntegerField(default=1)),
				("largo_m", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
				("ancho_m", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
				("aula", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="secciones", to="core.aula")),
			],
			options={"ordering": ["aula", "numero"]},
		),
		migrations.AddConstraint(
			model_name="aulaseccion",
			constraint=models.UniqueConstraint(fields=("aula", "numero"), name="uniq_aula_seccion_numero"),
		),
		migrations.AddField(
			model_name="aula",
			name="espacio_por_silla",
			field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
		),
		migrations.AddField(
			model_name="aula",
			name="mesas_aplicables",
			field=models.BooleanField(blank=True, null=True),
		),
		migrations.RunPython(move_dimensions_to_sections, move_first_section_back),
		migrations.RemoveField(model_name="aula", name="largo_m"),
		migrations.RemoveField(model_name="aula", name="ancho_m"),
	]