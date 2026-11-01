from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.functions import ExtractHour, ExtractMinute


class Aula(models.Model):
	class Tipo(models.TextChoices):
		AULA = "AULA", "Aula"
		LABORATORIO = "LABORATORIO", "Laboratorio"
		AUDITORIO = "AUDITORIO", "Auditorio"
		OTRO = "OTRO", "Otro"

	nombre = models.CharField(max_length=100, unique=True)
	bloque = models.CharField(max_length=50, blank=True)
	tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.AULA)
	espacio_por_silla = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	sillas = models.PositiveIntegerField(null=True, blank=True)
	mesas = models.PositiveIntegerField(null=True, blank=True)
	mesas_aplicables = models.BooleanField(null=True, blank=True)
	capacidad_manual = models.PositiveIntegerField(
		null=True,
		blank=True,
		verbose_name="capacidad manual",
		help_text="Para laboratorios, auditorios y espacios sin cantidad de sillas registrada.",
	)
	observacion = models.TextField(blank=True)
	existe = models.BooleanField(default=True)

	class Meta:
		ordering = ["bloque", "nombre"]
		verbose_name = "aula"
		verbose_name_plural = "aulas"

	@property
	def area_m2(self):
		areas = [seccion.area_m2 for seccion in self.secciones.all()]
		if not areas or any(area is None for area in areas):
			return None
		return sum(areas, Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

	@property
	def capacidad(self):
		if self.capacidad_manual is not None:
			return self.capacidad_manual
		if self.sillas is not None:
			return self.sillas

	@classmethod
	def capacidad_maxima_asignable(cls):
		"""Capacidad del aula (no laboratorio) más grande que existe; None si no hay datos."""
		capacidades = [
			aula.capacidad
			for aula in cls.objects.filter(existe=True, tipo=cls.Tipo.AULA)
			if aula.capacidad is not None
		]
		return max(capacidades) if capacidades else None

	def __str__(self):
		return self.nombre


class AulaSeccion(models.Model):
	aula = models.ForeignKey(Aula, on_delete=models.CASCADE, related_name="secciones")
	numero = models.PositiveSmallIntegerField(default=1)
	largo_m = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
	ancho_m = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

	class Meta:
		ordering = ["aula", "numero"]
		constraints = [
			models.UniqueConstraint(fields=["aula", "numero"], name="uniq_aula_seccion_numero"),
		]

	@property
	def area_m2(self):
		if self.largo_m is None or self.ancho_m is None:
			return None
		return (self.largo_m * self.ancho_m).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

	def __str__(self):
		return f"{self.aula.nombre} - sección {self.numero}"


class Materia(models.Model):
	codigo = models.CharField(max_length=30, unique=True)
	nombre = models.CharField(max_length=150)

	class Meta:
		ordering = ["nombre"]
		verbose_name_plural = "materias"

	def __str__(self):
		return f"{self.codigo} - {self.nombre}"


class Programa(models.Model):
	codigo = models.CharField(max_length=30, unique=True)
	nombre = models.CharField(max_length=120, unique=True)

	class Meta:
		ordering = ["nombre"]

	def __str__(self):
		return self.nombre


class Profesor(models.Model):

	codigo = models.CharField(
		max_length=20,
		unique=True,
		null=True,
		blank=True,
		validators=[RegexValidator(r"\A[A-Za-z0-9]+\Z", "Usa solo letras y números.")],
	)
	nombre = models.CharField(max_length=150)
	programas = models.ManyToManyField(Programa, related_name="profesores", blank=True)
	materias = models.ManyToManyField(Materia, related_name="profesores", blank=True)

	class Meta:
		ordering = ["nombre"]

	def save(self, *args, **kwargs):
		if self.codigo is not None:
			self.codigo = self.codigo.strip().upper() or None
		super().save(*args, **kwargs)

	def __str__(self):
		return self.nombre


class PeriodoAcademico(models.Model):
	codigo = models.CharField(max_length=20, unique=True)
	fecha_inicio = models.DateField(null=True, blank=True)
	fecha_fin = models.DateField(null=True, blank=True)

	class Meta:
		ordering = ["-codigo"]
		verbose_name = "período académico"
		verbose_name_plural = "períodos académicos"

	def __str__(self):
		return self.codigo


class Grupo(models.Model):
	class Modalidad(models.TextChoices):
		PRESENCIAL = "PRESENCIAL", "Presencial"
		VIRTUAL = "VIRTUAL", "Virtual"

	codigo = models.CharField(max_length=30)
	materia = models.ForeignKey(Materia, on_delete=models.PROTECT, related_name="grupos")
	periodo = models.ForeignKey(PeriodoAcademico, on_delete=models.PROTECT, related_name="grupos")
	modalidad = models.CharField(max_length=12, choices=Modalidad.choices, default=Modalidad.PRESENCIAL)
	profesor = models.ForeignKey(
		Profesor,
		on_delete=models.PROTECT,
		related_name="grupos",
	)
	estudiantes_matriculados = models.PositiveIntegerField(default=0)

	class Meta:
		ordering = ["periodo", "codigo"]
		constraints = [
			models.UniqueConstraint(
				fields=["periodo", "materia", "codigo"],
				name="uniq_grupo_periodo_materia_codigo",
			),
		]
		permissions = [
			("generar_informes", "Puede generar informes"),
		]

	def __str__(self):
		return f"{self.materia.codigo} - {self.codigo} ({self.periodo.codigo})"

	def limite_estudiantes(self):
		"""Máximo de estudiantes que admite este grupo presencial.

		Salones fijados a mano: su capacidad. Bloques automáticos: el salón más grande que esté
		libre de reservas fijas en esa franja. Sin horarios: el aula más grande que exista.
		"""
		if self.modalidad == self.Modalidad.VIRTUAL:
			return None
		from .asignacion import limite_para_bloques

		bloques = []
		if self.pk:
			for horario in self.horarios.select_related("aula"):
				bloques.append((
					horario.dia,
					horario._time_to_minute(horario.hora_inicio),
					horario._time_to_minute(horario.hora_fin),
					horario.aula if horario.aula_fijada and horario.aula_id else None,
				))
		return limite_para_bloques(self.periodo_id, bloques, excluir_grupo_id=self.pk)

	def save(self, *args, **kwargs):
		from django.db import transaction

		with transaction.atomic():
			super().save(*args, **kwargs)
			self._liberar_salones_automaticos()
			for horario in self.horarios.select_related("aula").all():
				horario.periodo_id = self.periodo_id
				horario.profesor_id = self.profesor_id
				horario.full_clean(exclude=["inicio_minuto", "fin_minuto"])
				horario.save()

	def _liberar_salones_automaticos(self):
		"""Quita los salones asignados automáticamente que ya no sirven; la reasignación elegirá otro."""
		virtual = self.modalidad == self.Modalidad.VIRTUAL
		for horario in self.horarios.select_related("aula").filter(aula_fijada=False, aula__isnull=False):
			capacidad = horario.aula.capacidad
			sirve = (
				not virtual
				and horario.aula.existe
				and (capacidad is None or capacidad >= self.estudiantes_matriculados)
			)
			if not sirve:
				Horario.objects.filter(pk=horario.pk).update(aula=None)


class Horario(models.Model):
	class Dia(models.TextChoices):
		LUNES = "LUNES", "Lunes"
		MARTES = "MARTES", "Martes"
		MIERCOLES = "MIERCOLES", "Miércoles"
		JUEVES = "JUEVES", "Jueves"
		VIERNES = "VIERNES", "Viernes"
		SABADO = "SABADO", "Sábado"
		DOMINGO = "DOMINGO", "Domingo"

	grupo = models.ForeignKey(Grupo, on_delete=models.CASCADE, related_name="horarios")
	periodo = models.ForeignKey(PeriodoAcademico, on_delete=models.PROTECT, related_name="horarios")
	profesor = models.ForeignKey(Profesor, on_delete=models.PROTECT, related_name="horarios")
	aula = models.ForeignKey(
		Aula,
		on_delete=models.PROTECT,
		related_name="horarios",
		null=True,
		blank=True,
	)
	dia = models.CharField(max_length=10, choices=Dia.choices)
	hora_inicio = models.TimeField()
	hora_fin = models.TimeField()
	aula_fijada = models.BooleanField(
		default=False,
		help_text="Si está activo, el salón se eligió a mano y la asignación automática no lo mueve.",
	)
	inicio_minuto = models.PositiveSmallIntegerField(editable=False)
	fin_minuto = models.PositiveSmallIntegerField(editable=False)

	class Meta:
		ordering = ["dia", "hora_inicio"]
		constraints = [
			models.UniqueConstraint(
				fields=["grupo", "dia", "hora_inicio", "hora_fin"],
				name="uniq_horario_grupo_bloque",
			),
			models.CheckConstraint(
				condition=Q(hora_inicio__lt=F("hora_fin")),
				name="chk_horario_inicio_antes_de_fin",
			),
			models.CheckConstraint(
				condition=Q(inicio_minuto=ExtractHour("hora_inicio") * 60 + ExtractMinute("hora_inicio"))
				& Q(fin_minuto=ExtractHour("hora_fin") * 60 + ExtractMinute("hora_fin")),
				name="chk_horario_minutos_coherentes",
			),
			ExclusionConstraint(
				name="excl_profesor_horario_solapado",
				expressions=[
					("periodo", RangeOperators.EQUAL),
					("dia", RangeOperators.EQUAL),
					("profesor", RangeOperators.EQUAL),
					(Func(F("inicio_minuto"), F("fin_minuto"), Value("[)"), function="int4range"), RangeOperators.OVERLAPS),
				],
			),
			ExclusionConstraint(
				name="excl_aula_horario_solapado",
				expressions=[
					("periodo", RangeOperators.EQUAL),
					("dia", RangeOperators.EQUAL),
					("aula", RangeOperators.EQUAL),
					(Func(F("inicio_minuto"), F("fin_minuto"), Value("[)"), function="int4range"), RangeOperators.OVERLAPS),
				],
				condition=Q(aula__isnull=False),
			),
		]

	HORA_MIN = 6 * 60
	HORA_MAX = 22 * 60
	DURACION_MIN = 30
	DURACION_MAX = 6 * 60

	@staticmethod
	def _time_to_minute(value):
		return value.hour * 60 + value.minute

	def clean(self):
		super().clean()
		if self.hora_inicio and self.hora_fin and self.hora_fin <= self.hora_inicio:
			raise ValidationError({"hora_fin": "La hora de fin debe ser posterior a la hora de inicio."})
		if self.hora_inicio and self.hora_fin:
			start = self._time_to_minute(self.hora_inicio)
			end = self._time_to_minute(self.hora_fin)
			if start < self.HORA_MIN or end > self.HORA_MAX:
				raise ValidationError({"hora_inicio": "Las clases solo pueden programarse entre las 06:00 y las 22:00."})
			if end - start < self.DURACION_MIN:
				raise ValidationError({"hora_fin": f"Cada bloque debe durar al menos {self.DURACION_MIN} minutos."})
			if end - start > self.DURACION_MAX:
				raise ValidationError({"hora_fin": "Un bloque no puede durar más de 6 horas."})

		if not self.grupo_id:
			return
		grupo = self.grupo
		self.periodo_id = grupo.periodo_id
		self.profesor_id = grupo.profesor_id

		if grupo.modalidad == Grupo.Modalidad.VIRTUAL and self.aula_id:
			raise ValidationError({"aula": "Una oferta virtual no puede tener un aula asignada."})
		if self.aula_id:
			if not self.aula.existe:
				raise ValidationError({"aula": "No se puede asignar un aula marcada como inexistente."})
			capacity = self.aula.capacidad
			if capacity is not None and grupo.estudiantes_matriculados > capacity:
				raise ValidationError({
					"aula": f"El aula admite {capacity} estudiantes, pero el grupo tiene {grupo.estudiantes_matriculados}."
				})

		if not self.dia or not self.hora_inicio or not self.hora_fin:
			return
		self.inicio_minuto = self._time_to_minute(self.hora_inicio)
		self.fin_minuto = self._time_to_minute(self.hora_fin)
		overlapping = Horario.objects.filter(
			periodo_id=self.periodo_id,
			dia=self.dia,
			inicio_minuto__lt=self.fin_minuto,
			fin_minuto__gt=self.inicio_minuto,
		).exclude(pk=self.pk)
		professor_conflict = overlapping.filter(profesor_id=self.profesor_id).exists()
		if professor_conflict:
			raise ValidationError({"grupo": "El profesor ya tiene otro horario que se solapa en este período y día."})
		if self.aula_id and overlapping.filter(aula_id=self.aula_id).exists():
			raise ValidationError({"aula": "El aula ya está ocupada en este período y horario."})

	def save(self, *args, **kwargs):
		if self.grupo_id:
			self.periodo_id = self.grupo.periodo_id
			self.profesor_id = self.grupo.profesor_id
			if self.dia and self.hora_inicio and self.hora_fin:
				self.inicio_minuto = self._time_to_minute(self.hora_inicio)
				self.fin_minuto = self._time_to_minute(self.hora_fin)
		self.full_clean(exclude=["inicio_minuto", "fin_minuto"])
		super().save(*args, **kwargs)

	def __str__(self):
		return f"{self.grupo} - {self.get_dia_display()} {self.hora_inicio:%H:%M}"
