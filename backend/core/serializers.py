from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import APIException

from .asignacion import limite_para_bloques
from .models import Aula, AulaSeccion, Grupo, Horario, Materia, PeriodoAcademico, Profesor, Programa


class ExcedeCapacidad(APIException):
    """409: el grupo supera el aula más grande; el cliente debe preguntar antes de redistribuir."""

    status_code = 409
    default_code = "excede_aula_maxima"

    def __init__(self, payload):
        self.detail = payload


def _flatten_errors(detail):
    if isinstance(detail, dict):
        return [message for messages in detail.values() for message in messages]
    return list(detail)


class AulaSeccionSerializer(serializers.ModelSerializer):
    area_m2 = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = AulaSeccion
        fields = ("id", "numero", "largo_m", "ancho_m", "area_m2")
        read_only_fields = ("id", "area_m2")

    def validate(self, attrs):
        length = attrs.get("largo_m", getattr(self.instance, "largo_m", None))
        width = attrs.get("ancho_m", getattr(self.instance, "ancho_m", None))
        if (length is None) != (width is None):
            raise serializers.ValidationError("Indica largo y ancho para cada sección, o deja ambos vacíos.")
        if length is not None and (length <= 0 or width <= 0):
            raise serializers.ValidationError("Las dimensiones deben ser mayores que cero.")
        return attrs


class AulaSerializer(serializers.ModelSerializer):
    area_m2 = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    capacidad = serializers.IntegerField(read_only=True, allow_null=True)
    secciones = AulaSeccionSerializer(many=True, read_only=True)

    class Meta:
        model = Aula
        fields = (
            "id",
            "nombre",
            "bloque",
            "tipo",
            "espacio_por_silla",
            "area_m2",
            "secciones",
            "sillas",
            "mesas",
            "mesas_aplicables",
            "capacidad",
            "capacidad_manual",
            "observacion",
            "existe",
        )
        read_only_fields = ("id", "area_m2", "capacidad")


class AulaWriteSerializer(AulaSerializer):
    secciones = AulaSeccionSerializer(many=True, required=False)

    @transaction.atomic
    def create(self, validated_data):
        sections_data = validated_data.pop("secciones", [])
        aula = Aula.objects.create(**validated_data)
        for section_data in sections_data:
            AulaSeccion.objects.create(aula=aula, **section_data)
        return aula

    @transaction.atomic
    def update(self, instance, validated_data):
        sections_data = validated_data.pop("secciones", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if sections_data is not None:
            section_numbers = []
            for section_data in sections_data:
                section, _ = AulaSeccion.objects.update_or_create(
                    aula=instance,
                    numero=section_data["numero"],
                    defaults={
                        "largo_m": section_data.get("largo_m"),
                        "ancho_m": section_data.get("ancho_m"),
                    },
                )
                section_numbers.append(section.numero)
            instance.secciones.exclude(numero__in=section_numbers).delete()
        return instance


class ProfesorSerializer(serializers.ModelSerializer):
    programas = serializers.PrimaryKeyRelatedField(queryset=Programa.objects.all(), many=True, required=False)
    programas_nombres = serializers.StringRelatedField(source="programas", many=True, read_only=True)
    materias = serializers.PrimaryKeyRelatedField(queryset=Materia.objects.all(), many=True, required=False)
    materias_nombres = serializers.SerializerMethodField()

    class Meta:
        model = Profesor
        fields = ("id", "nombre", "codigo", "programas", "programas_nombres", "materias", "materias_nombres")
        read_only_fields = ("id",)

    def get_materias_nombres(self, profesor):
        return [materia.nombre for materia in profesor.materias.all()]

    @transaction.atomic
    def create(self, validated_data):
        programas = validated_data.pop("programas", [])
        materias = validated_data.pop("materias", [])
        profesor = Profesor.objects.create(**validated_data)
        profesor.programas.set(programas)
        profesor.materias.set(materias)
        return profesor

    @transaction.atomic
    def update(self, instance, validated_data):
        programas = validated_data.pop("programas", None)
        materias = validated_data.pop("materias", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if programas is not None:
            instance.programas.set(programas)
        if materias is not None:
            instance.materias.set(materias)
        return instance

    def validate_codigo(self, value):
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None


class MateriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Materia
        fields = ("id", "codigo", "nombre")
        read_only_fields = ("id",)


class PeriodoAcademicoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodoAcademico
        fields = ("id", "codigo")
        read_only_fields = fields


class ProgramaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Programa
        fields = ("id", "codigo", "nombre")
        read_only_fields = ("id",)


class HorarioGrupoSerializer(serializers.ModelSerializer):
    aula_nombre = serializers.CharField(source="aula.nombre", read_only=True, default=None)
    aula = serializers.PrimaryKeyRelatedField(queryset=Aula.objects.all(), required=False, allow_null=True)
    aula_problema = serializers.SerializerMethodField()

    class Meta:
        model = Horario
        fields = ("id", "dia", "hora_inicio", "hora_fin", "aula", "aula_nombre", "aula_fijada", "aula_problema")
        read_only_fields = ("id", "aula_nombre", "aula_fijada", "aula_problema")

    def get_aula_problema(self, horario):
        if not horario.aula_id:
            return None
        if not horario.aula.existe:
            return "El aula asignada ya no existe."
        capacidad = horario.aula.capacidad
        if capacidad is not None and horario.grupo.estudiantes_matriculados > capacidad:
            return f"El aula {horario.aula.nombre} admite {capacidad} y el grupo tiene {horario.grupo.estudiantes_matriculados}."
        return None

    def validate(self, attrs):
        if attrs["hora_fin"] <= attrs["hora_inicio"]:
            raise serializers.ValidationError("La hora de fin debe ser posterior a la hora de inicio.")
        return attrs


class GrupoSerializer(serializers.ModelSerializer):
    materia_nombre = serializers.CharField(source="materia.nombre", read_only=True)
    materia_codigo = serializers.CharField(source="materia.codigo", read_only=True)
    periodo_codigo = serializers.CharField(source="periodo.codigo", read_only=True)
    profesor_nombre = serializers.CharField(source="profesor.nombre", read_only=True, allow_null=True)
    profesor_codigo = serializers.CharField(source="profesor.codigo", read_only=True, allow_null=True)
    capacidad_aula_asignada = serializers.SerializerMethodField()
    advertencias = serializers.SerializerMethodField()
    horarios = HorarioGrupoSerializer(many=True, required=False)
    redistribuir = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Grupo
        fields = (
            "id",
            "codigo",
            "materia",
            "materia_nombre",
            "materia_codigo",
            "periodo",
            "periodo_codigo",
            "modalidad",
            "profesor",
            "profesor_nombre",
            "profesor_codigo",
            "estudiantes_matriculados",
            "capacidad_aula_asignada",
            "advertencias",
            "horarios",
            "redistribuir",
        )
        read_only_fields = (
            "id",
            "materia_nombre",
            "materia_codigo",
            "periodo_codigo",
            "profesor_nombre",
            "profesor_codigo",
            "capacidad_aula_asignada",
            "advertencias",
        )

    MATRICULA_MAXIMA = 150

    def validate_estudiantes_matriculados(self, value):
        if value < 0:
            raise serializers.ValidationError("La cantidad de estudiantes no puede ser negativa.")
        if value > self.MATRICULA_MAXIMA:
            raise serializers.ValidationError(f"La matrícula no puede superar {self.MATRICULA_MAXIMA} estudiantes.")
        return value

    def validate_horarios(self, horarios):
        for index, first in enumerate(horarios):
            for second in horarios[index + 1:]:
                if first["dia"] == second["dia"] and first["hora_inicio"] < second["hora_fin"] and second["hora_inicio"] < first["hora_fin"]:
                    raise serializers.ValidationError("El grupo tiene dos horarios que se solapan el mismo día.")
        return horarios

    def validate(self, attrs):
        modalidad = attrs.get("modalidad", getattr(self.instance, "modalidad", None))
        if modalidad == Grupo.Modalidad.VIRTUAL:
            for item in attrs.get("horarios", []):
                if item.get("aula"):
                    raise serializers.ValidationError({"horarios": ["Un grupo virtual no puede tener aula asignada."]})
        self._traslados = []
        if self.instance is None or "estudiantes_matriculados" in attrs or "modalidad" in attrs:
            self._planificar_traslados(attrs, modalidad)
        return attrs

    def _planificar_traslados(self, attrs, modalidad):
        """Si la matrícula supera el aula más grande, propone pasar los sobrantes a otro grupo de la misma materia."""
        if modalidad != Grupo.Modalidad.PRESENCIAL:
            return
        total = attrs.get("estudiantes_matriculados", getattr(self.instance, "estudiantes_matriculados", 0))
        periodo_actual = attrs.get("periodo", getattr(self.instance, "periodo", None))
        if "horarios" in attrs:
            bloques = [
                (
                    item["dia"],
                    item["hora_inicio"].hour * 60 + item["hora_inicio"].minute,
                    item["hora_fin"].hour * 60 + item["hora_fin"].minute,
                    item.get("aula"),
                )
                for item in attrs["horarios"]
            ]
            limite = limite_para_bloques(
                periodo_actual.pk if periodo_actual else None, bloques,
                excluir_grupo_id=self.instance.pk if self.instance else None,
            )
        elif self.instance is not None:
            limite = self.instance.limite_estudiantes()
        else:
            limite = Aula.capacidad_maxima_asignable()
        if limite is None or total <= limite:
            return

        sobrantes = total - limite
        materia = attrs.get("materia", getattr(self.instance, "materia", None))
        periodo = attrs.get("periodo", getattr(self.instance, "periodo", None))
        candidatos = Grupo.objects.filter(
            materia=materia, periodo=periodo, modalidad=Grupo.Modalidad.PRESENCIAL,
        ).select_related("materia").order_by("estudiantes_matriculados")
        if self.instance is not None:
            candidatos = candidatos.exclude(pk=self.instance.pk)

        plan, pendientes = [], sobrantes
        for candidato in candidatos:
            tope = candidato.limite_estudiantes()
            libres = (tope if tope is not None else limite) - candidato.estudiantes_matriculados
            if libres <= 0 or pendientes <= 0:
                continue
            recibe = min(libres, pendientes)
            plan.append({"id": candidato.pk, "codigo": candidato.codigo, "materia_nombre": candidato.materia.nombre,
                         "matricula": candidato.estudiantes_matriculados, "libres": libres, "recibe": recibe})
            pendientes -= recibe

        if pendientes > 0:
            raise serializers.ValidationError({"estudiantes_matriculados": [
                f"El grupo admite como máximo {limite} estudiantes (salón más grande disponible en su horario) y sobran {sobrantes}. "
                "No hay otro grupo de esta materia con cupo suficiente: crea otro grupo, reduce la matrícula "
                "o, si el salón fue fijado a mano, cámbialo desde Asignación auto."
            ]})
        if not attrs.get("redistribuir"):
            raise ExcedeCapacidad({
                "codigo": "excede_aula_maxima", "maximo": limite, "sobrantes": sobrantes, "destinos": plan,
                "detail": f"El grupo supera el aula más grande asignable ({limite} puestos): sobran {sobrantes} estudiantes.",
            })
        attrs["estudiantes_matriculados"] = limite
        self._traslados = [(item["id"], item["recibe"]) for item in plan]

    def _aplicar_traslados(self):
        for pk, cantidad in self._traslados:
            destino = Grupo.objects.select_for_update().get(pk=pk)
            destino.estudiantes_matriculados += cantidad
            destino.save()

    def _replace_horarios(self, grupo, horarios, anteriores=None):
        anteriores = anteriores or {}
        try:
            for item in horarios:
                item = dict(item)
                if item.get("aula") is not None:
                    item["aula_fijada"] = True
                else:
                    previo = anteriores.get((item["dia"], item["hora_inicio"], item["hora_fin"]))
                    if previo is not None and previo["aula_fijada"]:
                        item["aula"], item["aula_fijada"] = previo["aula"], True
                Horario(grupo=grupo, **item).save()
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise serializers.ValidationError({"horarios": _flatten_errors(detail)}) from error
        except IntegrityError as error:
            raise serializers.ValidationError({"horarios": ["El horario se cruza con otro del mismo profesor o aula."]}) from error

    @transaction.atomic
    def create(self, validated_data):
        horarios = validated_data.pop("horarios", [])
        validated_data.pop("redistribuir", None)
        grupo = Grupo.objects.create(**validated_data)
        self._replace_horarios(grupo, horarios)
        self._aplicar_traslados()
        return grupo

    @transaction.atomic
    def update(self, instance, validated_data):
        horarios = validated_data.pop("horarios", None)
        validated_data.pop("redistribuir", None)
        anteriores = {}
        if horarios is not None:
            anteriores = {
                (h.dia, h.hora_inicio, h.hora_fin): {"aula": h.aula, "aula_fijada": h.aula_fijada}
                for h in instance.horarios.select_related("aula")
            }
            instance.horarios.all().delete()
        for field, value in validated_data.items():
            setattr(instance, field, value)
        try:
            instance.save()
        except DjangoValidationError as error:
            detail = error.message_dict if hasattr(error, "message_dict") else error.messages
            raise serializers.ValidationError(detail) from error
        if horarios is not None:
            self._replace_horarios(instance, horarios, anteriores)
        self._aplicar_traslados()
        return instance

    def get_capacidad_aula_asignada(self, grupo):
        capacities = [
            horario.aula.capacidad
            for horario in grupo.horarios.all()
            if horario.aula_id and horario.aula.capacidad is not None
        ]
        return min(capacities) if capacities else None

    def get_advertencias(self, grupo):
        warnings = []
        for horario in grupo.horarios.all():
            if horario.aula_id and horario.aula.capacidad is None:
                warnings.append(f"{horario.aula.nombre}: capacidad no definida; verificar manualmente.")
        return warnings


class HorarioSerializer(serializers.ModelSerializer):
    profesor_nombre = serializers.CharField(source="grupo.profesor.nombre", read_only=True)
    materia_nombre = serializers.CharField(source="grupo.materia.nombre", read_only=True)
    advertencias = serializers.SerializerMethodField()

    class Meta:
        model = Horario
        fields = (
            "id",
            "grupo",
            "aula",
            "dia",
            "hora_inicio",
            "hora_fin",
            "profesor_nombre",
            "materia_nombre",
            "advertencias",
        )
        read_only_fields = ("id", "profesor_nombre", "materia_nombre", "advertencias")

    def validate(self, attrs):
        group = attrs.get("grupo", getattr(self.instance, "grupo", None))
        room = attrs.get("aula", getattr(self.instance, "aula", None))
        day = attrs.get("dia", getattr(self.instance, "dia", None))
        start = attrs.get("hora_inicio", getattr(self.instance, "hora_inicio", None))
        end = attrs.get("hora_fin", getattr(self.instance, "hora_fin", None))

        if start is None or end is None or day is None or group is None:
            return attrs
        if end <= start:
            raise serializers.ValidationError({"hora_fin": "La hora de fin debe ser posterior a la hora de inicio."})
        if group.modalidad == Grupo.Modalidad.VIRTUAL and room is not None:
            raise serializers.ValidationError({"aula": "Una oferta virtual no puede tener un aula asignada."})
        if room is not None:
            if not room.existe:
                raise serializers.ValidationError({"aula": "No se puede asignar un aula marcada como inexistente."})
            if room.capacidad is not None and group.estudiantes_matriculados > room.capacidad:
                raise serializers.ValidationError({
                    "aula": f"Capacidad insuficiente: el aula admite {room.capacidad} y el grupo tiene {group.estudiantes_matriculados}."
                })

        candidate = Horario(
            pk=self.instance.pk if self.instance else None,
            grupo=group,
            periodo=group.periodo,
            profesor=group.profesor,
            aula=room,
            dia=day,
            hora_inicio=start,
            hora_fin=end,
        )
        try:
            candidate.full_clean(exclude=["inicio_minuto", "fin_minuto"])
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data["aula_fijada"] = validated_data.get("aula") is not None
        grupo = validated_data["grupo"]
        validated_data["periodo"], validated_data["profesor"] = grupo.periodo, grupo.profesor
        try:
            horario = Horario(**validated_data)
            horario.full_clean(exclude=["inicio_minuto", "fin_minuto"])
            horario.save()
            return horario
        except IntegrityError as error:
            raise serializers.ValidationError({"non_field_errors": ["El horario se cruza con otro horario del mismo profesor o aula."]}) from error

    @transaction.atomic
    def update(self, instance, validated_data):
        if "aula" in validated_data:
            validated_data["aula_fijada"] = validated_data["aula"] is not None
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.periodo, instance.profesor = instance.grupo.periodo, instance.grupo.profesor
        try:
            instance.full_clean(exclude=["inicio_minuto", "fin_minuto"])
            instance.save()
            return instance
        except IntegrityError as error:
            raise serializers.ValidationError({"non_field_errors": ["El horario se cruza con otro horario del mismo profesor o aula."]}) from error

    def get_advertencias(self, horario):
        if horario.aula_id and horario.aula.capacidad is None:
            return [f"{horario.aula.nombre}: capacidad no definida; verificar manualmente."]
        return []