import re

from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def create_initial_offerings(apps, schema_editor):
    Profesor = apps.get_model("core", "Profesor")
    Materia = apps.get_model("core", "Materia")
    PeriodoAcademico = apps.get_model("core", "PeriodoAcademico")
    Grupo = apps.get_model("core", "Grupo")
    database = schema_editor.connection.alias
    professors = Profesor.objects.using(database).exclude(materia="").order_by("pk")
    if not professors.exists():
        return

    period, _ = PeriodoAcademico.objects.using(database).get_or_create(codigo="2026-B")
    used_materia_codes = set(Materia.objects.using(database).values_list("codigo", flat=True))

    for index, professor in enumerate(professors, start=1):
        subject_name = professor.materia.strip()
        is_virtual = subject_name.upper().endswith("(AULA VIRTUAL)")
        if is_virtual:
            subject_name = re.sub(r"\s*\(AULA VIRTUAL\)\s*$", "", subject_name, flags=re.IGNORECASE).strip()

        materia = Materia.objects.using(database).filter(nombre__iexact=subject_name).first()
        if materia is None:
            base_code = slugify(subject_name).replace("-", "_").upper()[:24].strip("_") or f"MATERIA_{index:03d}"
            code = base_code
            suffix = 2
            while code in used_materia_codes:
                ending = f"_{suffix}"
                code = f"{base_code[:30 - len(ending)]}{ending}"
                suffix += 1
            materia = Materia.objects.using(database).create(codigo=code, nombre=subject_name)
            used_materia_codes.add(code)

        group_code = f"OF-{professor.codigo or f'{index:03d}'}"
        group_code = group_code[:30]
        group, created = Grupo.objects.using(database).get_or_create(
            periodo=period,
            codigo=group_code,
            defaults={
                "materia": materia,
                "profesor_id": professor.pk,
                "modalidad": "VIRTUAL" if is_virtual else "PRESENCIAL",
                "estudiantes_matriculados": 0,
            },
        )
        if not created:
            group.materia = materia
            group.profesor_id = professor.pk
            group.modalidad = "VIRTUAL" if is_virtual else "PRESENCIAL"
            group.estudiantes_matriculados = 0
            group.save(using=database)


def keep_academic_data(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_alter_grupo_estudiantes_matriculados"),
    ]

    operations = [
        migrations.AddField(
            model_name="grupo",
            name="modalidad",
            field=models.CharField(
                choices=[("PRESENCIAL", "Presencial"), ("VIRTUAL", "Virtual")],
                default="PRESENCIAL",
                max_length=12,
            ),
        ),
        migrations.RunPython(create_initial_offerings, keep_academic_data),
    ]
