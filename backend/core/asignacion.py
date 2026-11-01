"""Asignación automática de salones.

Cada bloque horario (Horario) de un grupo presencial recibe un salón. La asignación se guarda en
Horario.aula, así que las reglas del modelo y las restricciones de exclusión de PostgreSQL
(profesor y aula no se cruzan) se aplican siempre.

Reglas:
  * Solo se asignan automáticamente aulas (no laboratorios) que existan y tengan capacidad.
  * Mejor ajuste: se elige el salón más pequeño donde quepa el grupo y que esté libre en ese bloque.
  * Los grupos más grandes eligen primero.
  * Los bloques con salón fijado a mano (aula_fijada) no se mueven y reservan su franja.
  * Un grupo virtual nunca tiene salón.
"""
import threading
from bisect import bisect_left
from collections import defaultdict

from django.db import IntegrityError, connection, transaction

from .models import Aula, Grupo, Horario, PeriodoAcademico


LOCK_REASIGNACION = 7_102_026


def _se_cruzan(a_ini, a_fin, b_ini, b_fin):
	return a_ini < b_fin and b_ini < a_fin


def _aulas_automaticas():
	return [
		aula for aula in Aula.objects.filter(existe=True, tipo=Aula.Tipo.AULA)
		if aula.capacidad is not None
	]


def _ocupacion_fija(periodo_id, excluir_grupo_id=None):
	"""(aula_id, dia) -> [(inicio, fin)] reservado por bloques fijados a mano."""
	reservas = defaultdict(list)
	fijos = Horario.objects.filter(periodo_id=periodo_id, aula_fijada=True, aula__isnull=False)
	if excluir_grupo_id is not None:
		fijos = fijos.exclude(grupo_id=excluir_grupo_id)
	for horario in fijos:
		reservas[(horario.aula_id, horario.dia)].append((horario.inicio_minuto, horario.fin_minuto))
	return reservas


def _libre(reservas, aula_id, dia, inicio, fin):
	return not any(_se_cruzan(inicio, fin, i, f) for i, f in reservas.get((aula_id, dia), ()))


def limite_para_bloques(periodo_id, bloques, excluir_grupo_id=None):
	"""Máximo de estudiantes que admite un grupo con estos bloques.

	bloques: [(dia, inicio_min, fin_min, aula_fijada_o_None)].
	Para cada bloque: la capacidad del salón fijado, o la del salón más grande libre de reservas fijas.
	El límite del grupo es el menor de sus bloques; sin bloques, el aula más grande que exista.
	"""
	aulas = _aulas_automaticas()
	if not aulas:
		return None
	mayor = max(aula.capacidad for aula in aulas)
	if not bloques:
		return mayor

	reservas = _ocupacion_fija(periodo_id, excluir_grupo_id)
	limites = []
	for dia, inicio, fin, fija in bloques:
		if fija is not None:
			if fija.capacidad is not None:
				limites.append(fija.capacidad)
			continue
		libres = [a.capacidad for a in aulas if _libre(reservas, a.pk, dia, inicio, fin)]
		if libres:
			limites.append(max(libres))
	return min(limites) if limites else mayor


def reasignar(periodo_id):
	"""Recalcula el salón de todos los bloques no fijados de un período. Devuelve cuántos cambiaron."""
	with transaction.atomic():
		# serializa los cálculos: dos guardados simultáneos no deben pisarse
		with connection.cursor() as cursor:
			cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_REASIGNACION])
		aulas = sorted(_aulas_automaticas(), key=lambda aula: (aula.capacidad, aula.nombre))
		horarios = list(
			Horario.objects.filter(periodo_id=periodo_id)
			.select_related("grupo", "aula")
			.order_by("pk")
		)
		reservas = defaultdict(list)
		for horario in horarios:
			if horario.aula_fijada and horario.aula_id:
				reservas[(horario.aula_id, horario.dia)].append((horario.inicio_minuto, horario.fin_minuto))

		pendientes = [horario for horario in horarios if not horario.aula_fijada]
		presenciales = [h for h in pendientes if h.grupo.modalidad == Grupo.Modalidad.PRESENCIAL]
		presenciales.sort(key=lambda h: (-h.grupo.estudiantes_matriculados, h.grupo_id, h.inicio_minuto, h.pk))

		capacidades = [aula.capacidad for aula in aulas]
		destino = {h.pk: None for h in pendientes}
		for horario in presenciales:
			# mejor ajuste: se recorre desde el primer salón que alcanza y se corta en el primero libre;
			# a igual capacidad se prefiere el que el grupo ya tenía (menos movimientos)
			elegida, capacidad_elegida = None, None
			for aula in aulas[bisect_left(capacidades, horario.grupo.estudiantes_matriculados):]:
				if capacidad_elegida is not None and aula.capacidad > capacidad_elegida:
					break
				if _libre(reservas, aula.pk, horario.dia, horario.inicio_minuto, horario.fin_minuto):
					if elegida is None:
						elegida, capacidad_elegida = aula, aula.capacidad
					if aula.pk == horario.aula_id:
						elegida = aula
						break
			if elegida is None:
				continue
			destino[horario.pk] = elegida.pk
			reservas[(elegida.pk, horario.dia)].append((horario.inicio_minuto, horario.fin_minuto))

		cambios = [h for h in pendientes if h.aula_id != destino[h.pk]]
		# primero se liberan todos los que cambian y luego se asignan, para no chocar en el intercambio
		if cambios:
			Horario.objects.filter(pk__in=[h.pk for h in cambios]).update(aula=None)
		por_salon = defaultdict(list)
		for horario in cambios:
			if destino[horario.pk] is not None:
				por_salon[destino[horario.pk]].append(horario.pk)
		for aula_id, ids in por_salon.items():  # una sola consulta por salón
			try:
				with transaction.atomic():
					Horario.objects.filter(pk__in=ids).update(aula_id=aula_id)
			except IntegrityError:
				for pk in ids:  # si algo choca, se resuelve fila por fila y se deja sin salón lo que no entre
					try:
						with transaction.atomic():
							Horario.objects.filter(pk=pk).update(aula_id=aula_id)
					except IntegrityError:
						pass
		return len(cambios)


def reasignar_todo():
	return sum(reasignar(periodo_id) for periodo_id in PeriodoAcademico.objects.values_list("pk", flat=True))


# --- disparo automático al guardar datos -----------------------------------------------------

_estado = threading.local()


def _vaciar_pendiente():
	if not getattr(_estado, "pendiente", False):
		return
	_estado.pendiente = False
	reasignar_todo()


def programar_reasignacion(**kwargs):
	"""Se engancha a las señales; ejecuta una sola reasignación cuando termina la transacción."""
	_estado.pendiente = True
	transaction.on_commit(_vaciar_pendiente)
