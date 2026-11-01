from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F, Func, Value


PROGRAMS = {
	"ING_SOFTWARE": "Ingeniería de Software",
	"ING_AMBIENTAL": "Ingeniería Ambiental",
	"ING_ALIMENTOS": "Ingeniería de Alimentos",
	"SST": "SST",
	"ING_ELECTRICA": "Ingeniería Eléctrica",
}

def migrate_professor_programs_and_schedule_keys(apps, schema_editor):
	Profesor = apps.get_model("core", "Profesor")
	Programa = apps.get_model("core", "Programa")
	Grupo = apps.get_model("core", "Grupo")
	Horario = apps.get_model("core", "Horario")
	database = schema_editor.connection.alias

	programs_by_code = {}
	for code, name in PROGRAMS.items():
		program, _ = Programa.objects.using(database).get_or_create(
			codigo=code,
			defaults={"nombre": name},
		)
		programs_by_code[code] = program

	for professor in Profesor.objects.using(database).all().iterator():
		code = professor.programa
		program = programs_by_code.get(code)
		if program is None:
			name = code.replace("_", " ").title()
			program, _ = Programa.objects.using(database).get_or_create(
				codigo=code,
				defaults={"nombre": name},
			)
			programs_by_code[code] = program
		professor.programas.add(program)

	missing_professors = list(
		Grupo.objects.using(database).filter(profesor__isnull=True).values_list("pk", flat=True)[:20]
	)
	if missing_professors:
		raise RuntimeError(
			"No se puede hacer obligatorio el profesor: hay grupos sin docente "
			f"(IDs de ejemplo: {missing_professors}). Asigna esos docentes y reintenta."
		)

	for horario in Horario.objects.using(database).select_related("grupo").all().iterator():
		grupo = horario.grupo
		if not grupo.profesor_id:
			raise RuntimeError(f"El horario {horario.pk} pertenece a un grupo sin profesor.")
		horario.periodo_id = grupo.periodo_id
		horario.profesor_id = grupo.profesor_id
		horario.inicio_minuto = horario.hora_inicio.hour * 60 + horario.hora_inicio.minute
		horario.fin_minuto = horario.hora_fin.hour * 60 + horario.hora_fin.minute
		horario.save(using=database, update_fields=["periodo", "profesor", "inicio_minuto", "fin_minuto"])


def keep_schedule_data(apps, schema_editor):
	pass


def ensure_btree_gist(apps, schema_editor):
	if schema_editor.connection.vendor == "postgresql":
		schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def add_exclusion_constraints(apps, schema_editor):
	if schema_editor.connection.vendor != "postgresql":
		return
	Horario = apps.get_model("core", "Horario")
	minutes_range = Func(F("inicio_minuto"), F("fin_minuto"), Value("[)"), function="int4range")
	constraints = [
		ExclusionConstraint(
			name="excl_profesor_horario_solapado",
		expressions=[
				("periodo", RangeOperators.EQUAL),
				("dia", RangeOperators.EQUAL),
				("profesor", RangeOperators.EQUAL),
				(minutes_range, RangeOperators.OVERLAPS),
			],
		),
		ExclusionConstraint(
			name="excl_aula_horario_solapado",
		expressions=[
				("periodo", RangeOperators.EQUAL),
				("dia", RangeOperators.EQUAL),
				("aula", RangeOperators.EQUAL),
				(minutes_range, RangeOperators.OVERLAPS),
			],
			condition=models.Q(aula__isnull=False),
		),
	]
	for constraint in constraints:
		schema_editor.add_constraint(Horario, constraint)


def remove_exclusion_constraints(apps, schema_editor):
	if schema_editor.connection.vendor != "postgresql":
		return
	Horario = apps.get_model("core", "Horario")
	for name in ("excl_aula_horario_solapado", "excl_profesor_horario_solapado"):
		schema_editor.remove_constraint(Horario, models.CheckConstraint(condition=models.Q(pk__isnull=True), name=name))


class Migration(migrations.Migration):
	dependencies = [
		("core", "0007_seed_subject_offerings"),
	]

	operations = [
		migrations.RunPython(ensure_btree_gist, keep_schedule_data),
		migrations.CreateModel(
			name="Programa",
			fields=[
				("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
				("codigo", models.CharField(max_length=30, unique=True)),
				("nombre", models.CharField(max_length=120, unique=True)),
			],
			options={"ordering": ["nombre"]},
		),
		migrations.AddField(
			model_name="profesor",
			name="programas",
			field=models.ManyToManyField(blank=True, related_name="profesores", to="core.programa"),
		),
		migrations.AddField(
			model_name="horario",
			name="periodo",
			field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="horarios", to="core.periodoacademico"),
		),
		migrations.AddField(
			model_name="horario",
			name="profesor",
			field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="horarios", to="core.profesor"),
		),
		migrations.AddField(
			model_name="horario",
			name="inicio_minuto",
			field=models.PositiveSmallIntegerField(null=True, editable=False),
		),
		migrations.AddField(
			model_name="horario",
			name="fin_minuto",
			field=models.PositiveSmallIntegerField(null=True, editable=False),
		),
		migrations.RunPython(migrate_professor_programs_and_schedule_keys, keep_schedule_data),
		migrations.RemoveField(model_name="profesor", name="programa"),
		migrations.AlterField(
			model_name="grupo",
			name="profesor",
			field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="grupos", to="core.profesor"),
		),
		migrations.AlterField(
			model_name="horario",
			name="periodo",
			field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="horarios", to="core.periodoacademico"),
		),
		migrations.AlterField(
			model_name="horario",
			name="profesor",
			field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="horarios", to="core.profesor"),
		),
		migrations.AlterField(
			model_name="horario",
			name="inicio_minuto",
			field=models.PositiveSmallIntegerField(editable=False),
		),
		migrations.AlterField(
			model_name="horario",
			name="fin_minuto",
			field=models.PositiveSmallIntegerField(editable=False),
		),
		migrations.SeparateDatabaseAndState(
			database_operations=[
				migrations.RunPython(add_exclusion_constraints, remove_exclusion_constraints),
			],
			state_operations=[
				migrations.AddConstraint(
					model_name="horario",
					constraint=ExclusionConstraint(
						name="excl_profesor_horario_solapado",
						expressions=[
							("periodo", RangeOperators.EQUAL),
							("dia", RangeOperators.EQUAL),
							("profesor", RangeOperators.EQUAL),
							(Func(F("inicio_minuto"), F("fin_minuto"), Value("[)"), function="int4range"), RangeOperators.OVERLAPS),
						],
					),
				),
				migrations.AddConstraint(
					model_name="horario",
					constraint=ExclusionConstraint(
						name="excl_aula_horario_solapado",
						expressions=[
							("periodo", RangeOperators.EQUAL),
							("dia", RangeOperators.EQUAL),
							("aula", RangeOperators.EQUAL),
							(Func(F("inicio_minuto"), F("fin_minuto"), Value("[)"), function="int4range"), RangeOperators.OVERLAPS),
						],
						condition=models.Q(aula__isnull=False),
					),
				),
			],
		),
	]