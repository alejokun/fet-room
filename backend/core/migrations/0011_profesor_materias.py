import re

from django.db import migrations, models
from django.utils.text import slugify


def texto_a_materias(apps, schema_editor):
    """Convierte Profesor.materia (texto libre) en vínculos reales con la tabla Materia."""
    Profesor = apps.get_model("core", "Profesor")
    Materia = apps.get_model("core", "Materia")
    db = schema_editor.connection.alias
    codigos = set(Materia.objects.using(db).values_list("codigo", flat=True))

    for profesor in Profesor.objects.using(db).exclude(materia=""):
        nombre = re.sub(r"\s*\(AULA VIRTUAL\)\s*$", "", profesor.materia, flags=re.IGNORECASE).strip()
        if not nombre:
            continue
        materia = Materia.objects.using(db).filter(nombre__iexact=nombre).first()
        if materia is None:
            base = slugify(nombre).replace("-", "_").upper()[:24].strip("_") or f"MATERIA_{profesor.pk}"
            codigo, sufijo = base, 2
            while codigo in codigos:
                fin = f"_{sufijo}"
                codigo, sufijo = f"{base[:30 - len(fin)]}{fin}", sufijo + 1
            materia = Materia.objects.using(db).create(codigo=codigo, nombre=nombre)
            codigos.add(codigo)
        profesor.materias.add(materia)


def materias_a_texto(apps, schema_editor):
    Profesor = apps.get_model("core", "Profesor")
    db = schema_editor.connection.alias
    for profesor in Profesor.objects.using(db).all():
        primera = profesor.materias.order_by("nombre").first()
        profesor.materia = primera.nombre if primera else ""
        profesor.save(using=db, update_fields=["materia"])


class Migration(migrations.Migration):
    dependencies = [("core", "0010_integridad_grupos_y_horarios")]

    operations = [
        migrations.AddField(
            model_name="profesor",
            name="materias",
            field=models.ManyToManyField(blank=True, related_name="profesores", to="core.materia"),
        ),
        migrations.RunPython(texto_a_materias, materias_a_texto),
        migrations.RemoveField(model_name="profesor", name="materia"),
    ]
