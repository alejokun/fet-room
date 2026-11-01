from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
	dependencies = [
		("core", "0004_profesor_identificador"),
	]

	operations = [
		migrations.RenameField(
			model_name="profesor",
			old_name="identificador",
			new_name="codigo",
		),
		migrations.RenameField(
			model_name="profesor",
			old_name="departamento",
			new_name="programa",
		),
		migrations.AlterField(
			model_name="profesor",
			name="programa",
			field=models.CharField(
				choices=[
					("ING_SOFTWARE", "Ingeniería de Software"),
					("ING_AMBIENTAL", "Ingeniería Ambiental"),
					("ING_ALIMENTOS", "Ingeniería de Alimentos"),
					("SST", "SST"),
					("ING_ELECTRICA", "Ingeniería Eléctrica"),
				],
				max_length=20,
			),
		),
		migrations.AddField(
			model_name="profesor",
			name="materia",
			field=models.CharField(blank=True, max_length=150),
		),
		migrations.RemoveField(
			model_name="profesor",
			name="correo",
		),
	]