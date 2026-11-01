"""Pruebas de carga de la asignación automática.

No forman parte de la suite normal (el nombre no empieza por "test"). Se ejecutan a propósito:

    venv/bin/python manage.py test core.pruebas_carga -v 2

Django crea una base de datos TEMPORAL (test_<nombre>), genera los datos sintéticos allí y la borra al
terminar: la base real nunca se toca. Escalas configurables:

    CARGA_ESCALAS=100,400,1500 venv/bin/python manage.py test core.pruebas_carga
"""
import os
import random
import statistics
import time as reloj
from collections import defaultdict
from datetime import time

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from .asignacion import reasignar_todo
from .models import Aula, Grupo, Horario, Materia, PeriodoAcademico, Profesor

DIAS = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]
INICIOS = [6, 8, 10, 12, 14, 16, 18, 20]  # bloques de 2 h dentro de 06:00–22:00
CAPACIDADES = [16, 20, 24, 26, 28, 30, 32, 34]
ESCALAS = [int(valor) for valor in os.environ.get("CARGA_ESCALAS", "100,400,1200").split(",")]


def construir_datos(n_grupos, semilla=42):
	"""Crea aulas, profesores, materias, grupos y horarios sin cruces de profesor (restricción de la BD)."""
	azar = random.Random(semilla)
	periodo = PeriodoAcademico.objects.create(codigo="CARGA")

	n_aulas = max(20, n_grupos // 6)
	aulas = [
		Aula(nombre=f"AULA-{i:04d}", bloque=f"Bloque {1 + i % 2}", sillas=azar.choice(CAPACIDADES), existe=(i % 25 != 0))
		for i in range(n_aulas)
	]
	aulas += [Aula(nombre=f"LAB-{i:03d}", tipo=Aula.Tipo.LABORATORIO, capacidad_manual=40) for i in range(5)]
	Aula.objects.bulk_create(aulas)

	materias = Materia.objects.bulk_create([Materia(codigo=f"M{i:04d}", nombre=f"Materia {i}") for i in range(max(10, n_grupos // 4))])
	profesores = Profesor.objects.bulk_create([Profesor(codigo=f"P{i:05d}", nombre=f"Profesor {i}") for i in range(max(10, n_grupos // 2))])

	ocupado = defaultdict(set)  # (profesor_id, dia, inicio) -> ya tiene clase
	grupos, plan = [], []
	for i in range(n_grupos):
		virtual = azar.random() < 0.08
		matricula = azar.randint(35, 45) if azar.random() < 0.05 else azar.randint(8, 34)
		dias = azar.sample(DIAS, 2)
		inicio = azar.choice(INICIOS)
		elegido = None
		for _ in range(30):
			candidato = azar.choice(profesores)
			if all((candidato.pk, dia, inicio) not in ocupado for dia in dias):
				elegido = candidato
				break
		if elegido is None:
			elegido = Profesor.objects.create(codigo=f"X{i:05d}", nombre=f"Profesor extra {i}")
		for dia in dias:
			ocupado[(elegido.pk, dia, inicio)] = True
		grupos.append(Grupo(
			codigo=f"G{i:05d}", materia=azar.choice(materias), periodo=periodo, profesor=elegido,
			modalidad=Grupo.Modalidad.VIRTUAL if virtual else Grupo.Modalidad.PRESENCIAL,
			estudiantes_matriculados=matricula,
		))
		plan.append((dias, inicio))

	Grupo.objects.bulk_create(grupos)
	horarios = []
	for grupo, (dias, inicio) in zip(grupos, plan):
		for dia in dias:
			horarios.append(Horario(
				grupo=grupo, periodo=periodo, profesor=grupo.profesor, dia=dia,
				hora_inicio=time(inicio), hora_fin=time(inicio + 2),
				inicio_minuto=inicio * 60, fin_minuto=(inicio + 2) * 60,
			))
	Horario.objects.bulk_create(horarios)
	return periodo


def verificar_invariantes(caso):
	"""Comprobación independiente del servicio: devuelve (asignados, sin_salon)."""
	horarios = list(Horario.objects.select_related("aula", "grupo").all())
	por_salon = defaultdict(list)
	asignados = sin_salon = 0
	for h in horarios:
		if h.grupo.modalidad == Grupo.Modalidad.VIRTUAL:
			caso.assertIsNone(h.aula_id, "un grupo virtual no puede tener salón")
			continue
		if h.aula_id is None:
			sin_salon += 1
			continue
		asignados += 1
		caso.assertTrue(h.aula.existe, f"{h.aula.nombre} no existe")
		caso.assertEqual(h.aula.tipo, Aula.Tipo.AULA, "la asignación automática solo usa aulas")
		caso.assertGreaterEqual(h.aula.capacidad, h.grupo.estudiantes_matriculados, f"{h.aula.nombre} es pequeña para {h.grupo.codigo}")
		por_salon[(h.aula_id, h.dia)].append((h.inicio_minuto, h.fin_minuto))
	for (aula_id, dia), franjas in por_salon.items():
		franjas.sort()
		for (_, fin), (inicio_siguiente, _) in zip(franjas, franjas[1:]):
			caso.assertLessEqual(fin, inicio_siguiente, f"cruce en el salón {aula_id} el {dia}")
	return asignados, sin_salon


class CargaAsignacionTests(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.resultados = []

	@classmethod
	def tearDownClass(cls):
		print("\n\n=========== RESUMEN DE CARGA ===========")
		print(f"{'grupos':>7} {'bloques':>8} {'salones':>8} | {'1ª asig.':>9} {'2ª (estable)':>12} {'cambio mat. p50/p95/max':>26} | {'consultas listado':>17} {'listado':>8}")
		for fila in cls.resultados:
			print(fila)
		print("=" * 40)
		super().tearDownClass()

	def _probar(self, n_grupos):
		construir_datos(n_grupos)
		n_bloques = Horario.objects.count()
		n_salones = Aula.objects.filter(existe=True, tipo=Aula.Tipo.AULA).count()

		# 1) asignación completa desde cero
		inicio = reloj.perf_counter()
		reasignar_todo()
		primera = reloj.perf_counter() - inicio
		asignados, sin_salon = verificar_invariantes(self)

		# 2) estabilidad: recalcular sin cambios no debe mover nada
		antes = dict(Horario.objects.values_list("pk", "aula_id"))
		inicio = reloj.perf_counter()
		reasignar_todo()
		segunda = reloj.perf_counter() - inicio
		self.assertEqual(antes, dict(Horario.objects.values_list("pk", "aula_id")), "recalcular sin cambios movió salones")

		# 3) salones fijados a mano: se respetan aunque cambie todo lo demás
		asignados_ids = [pk for pk, aula in antes.items() if aula is not None]
		azar = random.Random(7)
		fijados = azar.sample(asignados_ids, max(1, len(asignados_ids) // 20))
		Horario.objects.filter(pk__in=fijados).update(aula_fijada=True)
		fijos_antes = dict(Horario.objects.filter(pk__in=fijados).values_list("pk", "aula_id"))

		# 4) cambios reales por la API: cada uno dispara la reasignación completa
		cliente = APIClient()
		cliente.force_authenticate(user=get_user_model().objects.create_superuser(username=f"carga{n_grupos}", password="x" * 12))
		presenciales = list(Grupo.objects.filter(modalidad=Grupo.Modalidad.PRESENCIAL, estudiantes_matriculados__lt=30, estudiantes_matriculados__gt=10).values_list("pk", "estudiantes_matriculados")[:40])
		tiempos, rechazados = [], 0
		for pk, n in presenciales:
			inicio = reloj.perf_counter()
			with self.captureOnCommitCallbacks(execute=True):
				respuesta = cliente.patch(f"/api/grupos/{pk}/", {"estudiantes_matriculados": n + 3}, format="json")
			tiempos.append(reloj.perf_counter() - inicio)
			if respuesta.status_code not in (200, 409, 400):
				self.fail(f"respuesta inesperada {respuesta.status_code}: {respuesta.content[:200]}")
			rechazados += respuesta.status_code != 200
		asignados_final, sin_salon_final = verificar_invariantes(self)
		self.assertEqual(fijos_antes, dict(Horario.objects.filter(pk__in=fijados).values_list("pk", "aula_id")), "se movió un salón fijado a mano")

		# 5) listado: tiempo y número de consultas (no debe crecer con la cantidad de grupos)
		with CaptureQueriesContext(connection) as consultas:
			inicio = reloj.perf_counter()
			respuesta = cliente.get("/api/grupos/")
			listado = reloj.perf_counter() - inicio
		self.assertEqual(respuesta.status_code, 200)
		self.assertEqual(len(respuesta.json()), n_grupos)
		self.assertLessEqual(len(consultas), 12, "el listado hace consultas de más (N+1)")

		tiempos.sort()
		p50 = statistics.median(tiempos)
		p95 = tiempos[int(len(tiempos) * 0.95) - 1]
		self.__class__.resultados.append(
			f"{n_grupos:>7} {n_bloques:>8} {n_salones:>8} | {primera:>8.2f}s {segunda:>11.2f}s "
			f"{p50 * 1000:>8.0f}/{p95 * 1000:.0f}/{max(tiempos) * 1000:.0f} ms{'':>4} | {len(consultas):>17} {listado:>7.2f}s"
			f"   (asignados {asignados}->{asignados_final}, sin salón {sin_salon}->{sin_salon_final}, "
			f"fijados {len(fijados)}, avisos de capacidad {rechazados}/{len(presenciales)})"
		)

	def test_escalas(self):
		for n in ESCALAS:
			with self.subTest(grupos=n):
				# cada escala parte de una base vacía
				Horario.objects.all().delete()
				Grupo.objects.all().delete()
				Profesor.objects.all().delete()
				Materia.objects.all().delete()
				Aula.objects.all().delete()
				PeriodoAcademico.objects.all().delete()
				self._probar(n)
