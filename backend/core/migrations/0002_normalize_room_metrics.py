from django.db import migrations, models
from django.db.models import F


def preserve_special_room_capacity(apps, schema_editor):
	Aula = apps.get_model("core", "Aula")
	Aula.objects.exclude(tipo="AULA").filter(capacidad__isnull=False).update(
		capacidad_manual=F("capacidad"),
	)


def restore_special_room_capacity(apps, schema_editor):
	Aula = apps.get_model("core", "Aula")
	Aula.objects.exclude(tipo="AULA").filter(capacidad_manual__isnull=False).update(
		capacidad=F("capacidad_manual"),
	)


class Migration(migrations.Migration):
	dependencies = [
		("core", "0001_initial"),
	]

	operations = [
		migrations.AddField(
			model_name="aula",
			name="capacidad_manual",
			field=models.PositiveIntegerField(
				blank=True,
				help_text="Para laboratorios, auditorios y espacios sin cantidad de sillas registrada.",
				null=True,
				verbose_name="capacidad manual",
			),
		),
		migrations.RunPython(preserve_special_room_capacity, restore_special_room_capacity),
		migrations.RemoveField(
			model_name="aula",
			name="area_m2",
		),
		migrations.RemoveField(
			model_name="aula",
			name="capacidad",
		),
	]