from datetime import time
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from rest_framework.test import APITestCase

from .models import Aula, AulaSeccion, Grupo, Horario, Materia, PeriodoAcademico, Profesor, Programa


class ProfesorIdentityTests(TestCase):
	def test_identifier_is_optional_and_normalized(self):
		profesor = Profesor(nombre="Ana Pérez", codigo="  ab12c  ")
		profesor.save()
		Profesor.objects.create(nombre="Sin código")
		Profesor.objects.create(nombre="Tampoco tiene código")

		self.assertEqual(profesor.codigo, "AB12C")
		self.assertEqual(Profesor.objects.filter(codigo__isnull=True).count(), 2)

	def test_identifier_only_accepts_up_to_twenty_alphanumeric_characters(self):
		for value in ("ABC-123", "IDENTIFICADOR12345678"):
			with self.subTest(value=value):
				profesor = Profesor(nombre="Prueba", codigo=value)
				with self.assertRaises(ValidationError):
					profesor.full_clean()


class AulaAPITests(APITestCase):
	def test_coordinator_can_list_aulas_and_capacity_defaults_to_chairs(self):
		coordinator_group = Group.objects.get(name="Coordinador")
		coordinator = get_user_model().objects.create_user(username="coordinador")
		coordinator.groups.add(coordinator_group)
		self.client.force_authenticate(user=coordinator)

		Aula.objects.create(nombre="B1-101", sillas=28)

		response = self.client.get("/api/aulas/")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data[0]["capacidad"], 28)

	def test_area_and_capacity_are_derived_for_any_space_with_chairs(self):
		aula = Aula.objects.create(
			nombre="B1-102",
			tipo=Aula.Tipo.LABORATORIO,
			sillas=28,
		)
		AulaSeccion.objects.create(aula=aula, largo_m=Decimal("5.76"), ancho_m=Decimal("7.37"))

		self.assertEqual(aula.area_m2, Decimal("42.45"))
		self.assertEqual(aula.capacidad, 28)

	def test_area_sums_multiple_room_sections(self):
		aula = Aula.objects.create(nombre="B1-210")
		AulaSeccion.objects.create(aula=aula, numero=1, largo_m=Decimal("5.98"), ancho_m=Decimal("3.90"))
		AulaSeccion.objects.create(aula=aula, numero=2, largo_m=Decimal("4.02"), ancho_m=Decimal("2.54"))

		self.assertEqual(aula.area_m2, Decimal("33.53"))

	def test_special_room_uses_manual_capacity(self):
		laboratorio = Aula.objects.create(
			nombre="LAB-1",
			tipo=Aula.Tipo.LABORATORIO,
			capacidad_manual=35,
		)

		self.assertEqual(laboratorio.capacidad, 35)

	def test_anonymous_user_cannot_list_aulas(self):
		response = self.client.get("/api/aulas/")

		self.assertEqual(response.status_code, 401)

	def test_coordinator_cannot_create_aulas(self):
		coordinator = get_user_model().objects.create_user(username="solo_lectura")
		coordinator.groups.add(Group.objects.get(name="Coordinador"))
		self.client.force_authenticate(user=coordinator)

		response = self.client.post("/api/aulas/", {"nombre": "B1-NUEVA"}, format="json")

		self.assertEqual(response.status_code, 403)
		self.assertFalse(Aula.objects.filter(nombre="B1-NUEVA").exists())

	def test_administrator_can_create_and_update_aula_with_sections(self):
		administrator = get_user_model().objects.create_superuser(
			username="admin_crud",
			password="ClaveSegura123!",
		)
		self.client.force_authenticate(user=administrator)

		response = self.client.post("/api/aulas/", {
			"nombre": "B1-210",
			"bloque": "Bloque 1",
			"tipo": Aula.Tipo.AULA,
			"sillas": 28,
			"mesas": None,
			"mesas_aplicables": False,
			"secciones": [
				{"numero": 1, "largo_m": "5.98", "ancho_m": "3.90"},
				{"numero": 2, "largo_m": "4.02", "ancho_m": "2.54"},
			],
		}, format="json")

		self.assertEqual(response.status_code, 201, response.data)
		self.assertEqual(response.data["area_m2"], "33.53")
		self.assertEqual(len(response.data["secciones"]), 2)

		response = self.client.patch(
			f"/api/aulas/{response.data['id']}/",
			{"sillas": 30},
			format="json",
		)

		self.assertEqual(response.status_code, 200, response.data)
		self.assertEqual(response.data["capacidad"], 30)

	def test_cannot_delete_aula_assigned_to_schedule(self):
		administrator = get_user_model().objects.create_superuser(
			username="admin_aula_protegida",
			password="ClaveSegura123!",
		)
		self.client.force_authenticate(user=administrator)
		aula = Aula.objects.create(nombre="AULA-OCUPADA")
		periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		materia = Materia.objects.create(codigo="MAT-PROTEGIDA", nombre="Materia protegida")
		profesor = Profesor.objects.create(nombre="Docente protegido", codigo="PROT01")
		grupo = Grupo.objects.create(codigo="01", materia=materia, periodo=periodo, profesor=profesor)
		Horario.objects.create(
			grupo=grupo,
			aula=aula,
			dia=Horario.Dia.LUNES,
			hora_inicio=time(8, 0),
			hora_fin=time(10, 0),
		)

		response = self.client.delete(f"/api/aulas/{aula.pk}/")

		self.assertEqual(response.status_code, 400)
		self.assertTrue(Aula.objects.filter(pk=aula.pk).exists())


class ProfesorAPITests(APITestCase):
	def test_administrator_can_create_update_and_delete_profesor(self):
		administrator = get_user_model().objects.create_superuser(
			username="admin_profesores",
			password="ClaveSegura123!",
		)
		self.client.force_authenticate(user=administrator)

		response = self.client.post("/api/profesores/", {
			"codigo": "abc123",
			"nombre": "Juan Pérez",
			"programas": [],
			"materia": "Cálculo I",
		}, format="json")

		self.assertEqual(response.status_code, 201, response.data)
		self.assertEqual(response.data["codigo"], "ABC123")

		profesor_url = f"/api/profesores/{response.data['id']}/"
		response = self.client.patch(profesor_url, {"nombre": "Juanita Pérez"}, format="json")
		self.assertEqual(response.status_code, 200, response.data)
		self.assertEqual(response.data["nombre"], "Juanita Pérez")

		response = self.client.delete(profesor_url)
		self.assertEqual(response.status_code, 204)

	def test_coordinator_cannot_edit_profesor(self):
		profesor = Profesor.objects.create(nombre="Ana Docente", codigo="DOC001")
		coordinator = get_user_model().objects.create_user(username="coordinador_prof")
		coordinator.groups.add(Group.objects.get(name="Coordinador"))
		self.client.force_authenticate(user=coordinator)

		response = self.client.patch(
			f"/api/profesores/{profesor.pk}/",
			{"nombre": "Nombre alterado"},
			format="json",
		)

		self.assertEqual(response.status_code, 403)
		profesor.refresh_from_db()
		self.assertEqual(profesor.nombre, "Ana Docente")

	def test_cannot_delete_profesor_assigned_to_group(self):
		administrator = get_user_model().objects.create_superuser(
			username="admin_profesor_protegido",
			password="ClaveSegura123!",
		)
		self.client.force_authenticate(user=administrator)
		profesor = Profesor.objects.create(nombre="Profesor asignado", codigo="ASIGNADO1")
		periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		materia = Materia.objects.create(codigo="MAT-GRUPO", nombre="Materia grupo")
		Grupo.objects.create(codigo="01", materia=materia, periodo=periodo, profesor=profesor)

		response = self.client.delete(f"/api/profesores/{profesor.pk}/")

		self.assertEqual(response.status_code, 400)
		self.assertTrue(Profesor.objects.filter(pk=profesor.pk).exists())


class OfertaAcademicaAPITests(APITestCase):
	def setUp(self):
		self.administrator = get_user_model().objects.create_superuser(
			username="admin_ofertas",
			password="ClaveSegura123!",
		)
		self.client.force_authenticate(user=self.administrator)
		self.periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		self.materia = Materia.objects.create(codigo="CALC-MULTI", nombre="Cálculo Multivariado")
		self.profesor = Profesor.objects.create(
			nombre="Daniela Perez Peña",
			codigo="VPJ869",
		)

	def test_can_create_group_increment_students_and_reassign_professor(self):
		response = self.client.post("/api/grupos/", {
			"codigo": "OF-01",
			"materia": self.materia.pk,
			"periodo": self.periodo.pk,
			"modalidad": Grupo.Modalidad.PRESENCIAL,
			"profesor": self.profesor.pk,
			"estudiantes_matriculados": 0,
		}, format="json")
		self.assertEqual(response.status_code, 201, response.data)
		grupo_id = response.data["id"]

		response = self.client.patch(
			f"/api/grupos/{grupo_id}/",
			{"estudiantes_matriculados": 1},
			format="json",
		)
		self.assertEqual(response.status_code, 200, response.data)
		self.assertEqual(response.data["estudiantes_matriculados"], 1)

		nuevo_profesor = Profesor.objects.create(
			nombre="Profesor Reemplazo",
			codigo="ABC123",
		)
		response = self.client.patch(
			f"/api/grupos/{grupo_id}/",
			{"profesor": nuevo_profesor.pk},
			format="json",
		)
		self.assertEqual(response.status_code, 200, response.data)
		self.assertEqual(response.data["profesor_codigo"], "ABC123")

	def test_virtual_group_can_exist_without_room_or_schedule(self):
		response = self.client.post("/api/grupos/", {
			"codigo": "VIRTUAL-01",
			"materia": self.materia.pk,
			"periodo": self.periodo.pk,
			"modalidad": Grupo.Modalidad.VIRTUAL,
			"profesor": self.profesor.pk,
			"estudiantes_matriculados": 0,
		}, format="json")

		self.assertEqual(response.status_code, 201, response.data)
		self.assertEqual(response.data["modalidad"], Grupo.Modalidad.VIRTUAL)
		self.assertIsNone(response.data["capacidad_aula_asignada"])
		self.assertEqual(Grupo.objects.get(pk=response.data["id"]).horarios.count(), 0)

	def test_enrollment_cannot_be_negative(self):
		response = self.client.post("/api/grupos/", {
			"codigo": "NEG-01",
			"materia": self.materia.pk,
			"periodo": self.periodo.pk,
			"modalidad": Grupo.Modalidad.PRESENCIAL,
			"profesor": self.profesor.pk,
			"estudiantes_matriculados": -1,
		}, format="json")

		self.assertEqual(response.status_code, 400)


class HorarioTests(TestCase):
	def test_group_can_have_multiple_schedules_on_same_day(self):
		periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		materia = Materia.objects.create(codigo="MAT101", nombre="Matemáticas")
		profesor = Profesor.objects.create(nombre="Docente Matemáticas", codigo="MAT101")
		grupo = Grupo.objects.create(codigo="01", materia=materia, periodo=periodo, profesor=profesor)

		Horario.objects.create(
			grupo=grupo,
			dia=Horario.Dia.LUNES,
			hora_inicio=time(8, 0),
			hora_fin=time(10, 0),
		)
		Horario.objects.create(
			grupo=grupo,
			dia=Horario.Dia.LUNES,
			hora_inicio=time(14, 0),
			hora_fin=time(16, 0),
		)

		self.assertEqual(grupo.horarios.count(), 2)


class HorarioBusinessRuleTests(TestCase):
	def setUp(self):
		self.periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		self.materia = Materia.objects.create(codigo="HOR-101", nombre="Materia de horario")
		self.profesor = Profesor.objects.create(nombre="Docente de prueba", codigo="DOC101")
		self.grupo = Grupo.objects.create(
			codigo="A",
			materia=self.materia,
			periodo=self.periodo,
			profesor=self.profesor,
			estudiantes_matriculados=20,
		)
		self.aula = Aula.objects.create(nombre="AULA-REGLAS", sillas=25)

	def make_schedule(self, group, start, end, room=None, day=Horario.Dia.LUNES):
		return Horario(
			grupo=group,
			aula=room,
			dia=day,
			hora_inicio=time(*start),
			hora_fin=time(*end),
		)

	def test_overlapping_schedule_for_same_teacher_is_rejected(self):
		self.make_schedule(self.grupo, (7, 0), (9, 0), self.aula).save()
		other_group = Grupo.objects.create(
			codigo="B", materia=self.materia, periodo=self.periodo, profesor=self.profesor,
		)

		with self.assertRaises(ValidationError):
			self.make_schedule(other_group, (8, 30), (10, 0)).save()

	def test_overlapping_schedule_for_same_room_is_rejected(self):
		self.make_schedule(self.grupo, (7, 0), (9, 0), self.aula).save()
		other_professor = Profesor.objects.create(nombre="Otro docente", codigo="DOC102")
		other_group = Grupo.objects.create(
			codigo="B", materia=self.materia, periodo=self.periodo, profesor=other_professor,
		)

		with self.assertRaises(ValidationError):
			self.make_schedule(other_group, (8, 0), (9, 30), self.aula).save()

	def test_adjacent_schedule_is_allowed(self):
		self.make_schedule(self.grupo, (7, 0), (9, 0), self.aula).save()
		other_professor = Profesor.objects.create(nombre="Otro docente", codigo="DOC103")
		other_group = Grupo.objects.create(
			codigo="B", materia=self.materia, periodo=self.periodo, profesor=other_professor,
		)

		self.make_schedule(other_group, (9, 0), (11, 0), self.aula).save()
		self.assertEqual(Horario.objects.count(), 2)

	def test_insufficient_capacity_and_nonexistent_room_are_rejected(self):
		small_room = Aula.objects.create(nombre="AULA-PEQUENA", sillas=19)
		with self.assertRaises(ValidationError):
			self.make_schedule(self.grupo, (7, 0), (9, 0), small_room).save()

		nonexistent_room = Aula.objects.create(nombre="AULA-NO-EXISTE", existe=False)
		with self.assertRaises(ValidationError):
			self.make_schedule(self.grupo, (7, 0), (9, 0), nonexistent_room).save()

	def test_unknown_capacity_is_allowed(self):
		unknown_room = Aula.objects.create(nombre="AULA-SIN-CAPACIDAD")
		horario = self.make_schedule(self.grupo, (7, 0), (9, 0), unknown_room)
		horario.save()
		self.assertEqual(Horario.objects.count(), 1)

	def test_invalid_time_and_virtual_room_assignment_are_rejected(self):
		with self.assertRaises(ValidationError):
			self.make_schedule(self.grupo, (9, 0), (9, 0), self.aula).save()

		self.grupo.modalidad = Grupo.Modalidad.VIRTUAL
		self.grupo.save()
		with self.assertRaises(ValidationError):
			self.make_schedule(self.grupo, (10, 0), (11, 0), self.aula).save()


class SessionAuthTests(TestCase):
	def setUp(self):
		self.group = Group.objects.get(name="Coordinador")
		self.user = get_user_model().objects.create_user(
			username="coordinador",
			password="ClaveSegura123!",
		)
		self.user.groups.add(self.group)
		self.client = Client(enforce_csrf_checks=True)

	def test_coordinator_can_sign_in_with_csrf_and_read_rooms(self):
		self.client.get("/api/csrf/")
		csrf_token = self.client.cookies["csrftoken"].value
		response = self.client.post(
			"/api/auth/login/",
			data=json.dumps({"username": "coordinador", "password": "ClaveSegura123!"}),
			content_type="application/json",
			HTTP_X_CSRFTOKEN=csrf_token,
			HTTP_ORIGIN="http://localhost:4200",
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["groups"], ["Coordinador"])
		self.assertEqual(self.client.get("/api/aulas/").status_code, 200)

	def test_sign_in_without_csrf_token_is_rejected(self):
		response = self.client.post(
			"/api/auth/login/",
			data=json.dumps({"username": "coordinador", "password": "ClaveSegura123!"}),
			content_type="application/json",
		)

		self.assertEqual(response.status_code, 403)


class ReglasDeGruposTests(APITestCase):
	def setUp(self):
		self.client.force_authenticate(user=get_user_model().objects.create_superuser(
			username="admin_reglas", password="ClaveSegura123!",
		))
		self.periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		self.materia = Materia.objects.create(codigo="REG-1", nombre="Materia de reglas")
		self.otra = Materia.objects.create(codigo="REG-2", nombre="Otra materia")
		self.profesor = Profesor.objects.create(nombre="Profesor de reglas", codigo="REG1")

	def payload(self, codigo, horarios, **extra):
		data = {
			"codigo": codigo, "materia": self.materia.id, "periodo": self.periodo.id,
			"profesor": self.profesor.id, "modalidad": "PRESENCIAL",
			"estudiantes_matriculados": 10, "horarios": horarios,
		}
		data.update(extra)
		return data

	def bloque(self, inicio, fin, dia="LUNES"):
		return {"dia": dia, "hora_inicio": inicio, "hora_fin": fin}

	def test_group_is_created_with_its_schedules(self):
		response = self.client.post("/api/grupos/", self.payload("G1", [self.bloque("08:00", "10:00")]), format="json")
		self.assertEqual(response.status_code, 201, response.content)
		self.assertEqual(len(response.json()["horarios"]), 1)

	def test_same_teacher_cannot_teach_two_groups_at_same_time(self):
		self.client.post("/api/grupos/", self.payload("G1", [self.bloque("08:00", "10:00")]), format="json")
		response = self.client.post("/api/grupos/", self.payload("G2", [self.bloque("09:00", "11:00")], materia=self.otra.id), format="json")
		self.assertEqual(response.status_code, 400)
		self.assertFalse(Grupo.objects.filter(codigo="G2").exists())

	def test_back_to_back_classes_for_same_teacher_are_allowed(self):
		self.client.post("/api/grupos/", self.payload("G1", [self.bloque("08:00", "10:00")]), format="json")
		response = self.client.post("/api/grupos/", self.payload("G2", [self.bloque("10:00", "12:00")], materia=self.otra.id), format="json")
		self.assertEqual(response.status_code, 201, response.content)

	def test_group_cannot_overlap_itself(self):
		response = self.client.post("/api/grupos/", self.payload("G1", [self.bloque("08:00", "10:00"), self.bloque("09:00", "11:00")]), format="json")
		self.assertEqual(response.status_code, 400)

	def test_schedule_outside_institutional_hours_is_rejected(self):
		for inicio, fin in (("05:00", "07:00"), ("21:00", "23:00")):
			response = self.client.post("/api/grupos/", self.payload("G1", [self.bloque(inicio, fin)]), format="json")
			self.assertEqual(response.status_code, 400, (inicio, fin))

	def test_block_duration_limits(self):
		short = self.client.post("/api/grupos/", self.payload("G1", [self.bloque("08:00", "08:15")]), format="json")
		long = self.client.post("/api/grupos/", self.payload("G2", [self.bloque("07:00", "14:00")]), format="json")
		self.assertEqual(short.status_code, 400)
		self.assertEqual(long.status_code, 400)

	def test_failed_schedule_update_keeps_previous_schedules(self):
		created = self.client.post("/api/grupos/", self.payload("G1", [self.bloque("08:00", "10:00")]), format="json").json()
		response = self.client.patch(f"/api/grupos/{created['id']}/", {"horarios": [self.bloque("05:00", "07:00")]}, format="json")
		self.assertEqual(response.status_code, 400)
		self.assertEqual(Horario.objects.filter(grupo_id=created["id"]).count(), 1)

	def test_enrollment_has_an_upper_limit_and_cannot_exceed_assigned_room(self):
		too_many = self.client.post("/api/grupos/", self.payload("G1", [], estudiantes_matriculados=151), format="json")
		self.assertEqual(too_many.status_code, 400)
		aula = Aula.objects.create(nombre="AULA-CUPO", sillas=12)
		group = Grupo.objects.create(codigo="G3", materia=self.materia, periodo=self.periodo, profesor=self.profesor, estudiantes_matriculados=12)
		Horario.objects.create(grupo=group, aula=aula, dia="MARTES", hora_inicio=time(8, 0), hora_fin=time(10, 0))
		response = self.client.patch(f"/api/grupos/{group.id}/", {"estudiantes_matriculados": 13}, format="json")
		self.assertEqual(response.status_code, 400, response.content)
		group.refresh_from_db()
		self.assertEqual(group.estudiantes_matriculados, 12)

	def test_virtual_group_cannot_have_a_room(self):
		aula = Aula.objects.create(nombre="AULA-VIRT", sillas=30)
		response = self.client.post("/api/grupos/", self.payload("G1", [{**self.bloque("08:00", "10:00"), "aula": aula.id}], modalidad="VIRTUAL"), format="json")
		self.assertEqual(response.status_code, 400)


class RedistribucionDeEstudiantesTests(APITestCase):
	"""Aula más grande = 30 puestos; los sobrantes se pasan a otro grupo de la misma materia, solo si se confirma."""

	def setUp(self):
		self.client.force_authenticate(user=get_user_model().objects.create_superuser(
			username="admin_redis", password="ClaveSegura123!",
		))
		Aula.objects.create(nombre="AULA-30", tipo=Aula.Tipo.AULA, sillas=30)
		Aula.objects.create(nombre="AULA-20", tipo=Aula.Tipo.AULA, sillas=20)
		Aula.objects.create(nombre="LAB-50", tipo=Aula.Tipo.LABORATORIO, capacidad_manual=50)
		self.periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		self.bd = Materia.objects.create(codigo="BD", nombre="Bases de Datos")
		self.otra = Materia.objects.create(codigo="OTRA", nombre="Otra")
		self.profesor = Profesor.objects.create(nombre="Profe", codigo="P1")

	def grupo(self, codigo, n, materia=None, modalidad="PRESENCIAL"):
		return Grupo.objects.create(
			codigo=codigo, materia=materia or self.bd, periodo=self.periodo, profesor=self.profesor,
			modalidad=modalidad, estudiantes_matriculados=n,
		)

	def payload(self, codigo, n, **extra):
		data = {"codigo": codigo, "materia": self.bd.id, "periodo": self.periodo.id, "profesor": self.profesor.id,
				"modalidad": "PRESENCIAL", "estudiantes_matriculados": n}
		data.update(extra)
		return data

	def test_maximum_ignores_laboratories(self):
		self.assertEqual(Aula.capacidad_maxima_asignable(), 30)

	def test_creating_an_oversized_group_asks_before_changing_anything(self):
		otro = self.grupo("BD-2", 10)
		response = self.client.post("/api/grupos/", self.payload("BD-5", 35), format="json")
		self.assertEqual(response.status_code, 409, response.content)
		body = response.json()
		self.assertEqual((body["maximo"], body["sobrantes"]), (30, 5))
		self.assertEqual(body["destinos"][0]["id"], otro.id)
		self.assertFalse(Grupo.objects.filter(codigo="BD-5").exists())
		otro.refresh_from_db()
		self.assertEqual(otro.estudiantes_matriculados, 10)

	def test_confirmed_creation_moves_the_surplus(self):
		otro = self.grupo("BD-2", 10)
		response = self.client.post("/api/grupos/", self.payload("BD-5", 35, redistribuir=True), format="json")
		self.assertEqual(response.status_code, 201, response.content)
		self.assertEqual(Grupo.objects.get(codigo="BD-5").estudiantes_matriculados, 30)
		otro.refresh_from_db()
		self.assertEqual(otro.estudiantes_matriculados, 15)

	def test_quick_increment_beyond_limit_asks_then_moves_on_confirmation(self):
		lleno = self.grupo("BD-1", 30)
		otro = self.grupo("BD-2", 10)
		first = self.client.patch(f"/api/grupos/{lleno.id}/", {"estudiantes_matriculados": 31}, format="json")
		self.assertEqual(first.status_code, 409)
		self.assertEqual(first.json()["sobrantes"], 1)
		second = self.client.patch(f"/api/grupos/{lleno.id}/", {"estudiantes_matriculados": 31, "redistribuir": True}, format="json")
		self.assertEqual(second.status_code, 200, second.content)
		lleno.refresh_from_db(); otro.refresh_from_db()
		self.assertEqual((lleno.estudiantes_matriculados, otro.estudiantes_matriculados), (30, 11))

	def test_surplus_spreads_over_several_groups(self):
		self.grupo("BD-2", 25)
		self.grupo("BD-3", 28)
		response = self.client.post("/api/grupos/", self.payload("BD-5", 37, redistribuir=True), format="json")
		self.assertEqual(response.status_code, 201, response.content)
		totals = sorted(Grupo.objects.filter(materia=self.bd).values_list("estudiantes_matriculados", flat=True))
		self.assertEqual(sum(totals), 25 + 28 + 37)
		self.assertTrue(all(total <= 30 for total in totals))

	def test_rejects_when_no_other_group_has_room(self):
		self.grupo("BD-2", 30)
		response = self.client.post("/api/grupos/", self.payload("BD-5", 35, redistribuir=True), format="json")
		self.assertEqual(response.status_code, 400)
		self.assertFalse(Grupo.objects.filter(codigo="BD-5").exists())

	def test_other_subjects_and_virtual_groups_are_not_used_or_limited(self):
		self.grupo("OT-1", 5, materia=self.otra)
		self.grupo("BD-V", 5, modalidad="VIRTUAL")
		response = self.client.post("/api/grupos/", self.payload("BD-5", 35), format="json")
		self.assertEqual(response.status_code, 400)
		virtual = self.client.post("/api/grupos/", self.payload("BD-V2", 80, modalidad="VIRTUAL"), format="json")
		self.assertEqual(virtual.status_code, 201, virtual.content)


class AsignacionAutomaticaTests(APITestCase):
	def setUp(self):
		self.client.force_authenticate(user=get_user_model().objects.create_superuser(
			username="admin_asig", password="ClaveSegura123!",
		))
		self.periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		self.materia = Materia.objects.create(codigo="ASG", nombre="Materia")
		self.aula20 = Aula.objects.create(nombre="A-20", sillas=20)
		self.aula30 = Aula.objects.create(nombre="A-30", sillas=30)
		self.lab = Aula.objects.create(nombre="LAB-X", tipo=Aula.Tipo.LABORATORIO, capacidad_manual=25)
		self.contador = 0

	def grupo(self, n, bloques, modalidad="PRESENCIAL"):
		self.contador += 1
		profesor = Profesor.objects.create(nombre=f"Profe {self.contador}", codigo=f"AS{self.contador}")
		grupo = Grupo.objects.create(
			codigo=f"G{self.contador}", materia=self.materia, periodo=self.periodo, profesor=profesor,
			modalidad=modalidad, estudiantes_matriculados=n,
		)
		for dia, ini, fin in bloques:
			Horario(grupo=grupo, dia=dia, hora_inicio=time(ini), hora_fin=time(fin)).save()
		return grupo

	def reasignar(self):
		from .asignacion import reasignar_todo
		reasignar_todo()

	def salon(self, grupo):
		return list(grupo.horarios.values_list("aula__nombre", flat=True))

	def test_best_fit_and_biggest_group_first(self):
		chico = self.grupo(15, [("LUNES", 8, 10)])
		grande = self.grupo(25, [("LUNES", 8, 10)])
		self.reasignar()
		self.assertEqual(self.salon(grande), ["A-30"])
		self.assertEqual(self.salon(chico), ["A-20"])

	def test_laboratories_are_not_used_automatically(self):
		grupo = self.grupo(40, [("LUNES", 8, 10)])
		self.reasignar()
		self.assertEqual(self.salon(grupo), [None])

	def test_same_room_is_shared_at_different_times_but_never_overlaps(self):
		a = self.grupo(25, [("LUNES", 8, 10)])
		b = self.grupo(25, [("LUNES", 10, 12)])
		c = self.grupo(25, [("LUNES", 9, 11)])
		self.reasignar()
		self.assertEqual(self.salon(a), ["A-30"])
		self.assertEqual(self.salon(b), ["A-30"])
		self.assertEqual(self.salon(c), [None])

	def test_each_block_can_use_a_different_room(self):
		self.grupo(25, [("LUNES", 8, 10)])
		grupo = self.grupo(25, [("LUNES", 8, 10), ("MARTES", 8, 10)])
		self.reasignar()
		self.assertEqual(sorted(filter(None, self.salon(grupo))), ["A-30"])

	def test_virtual_groups_never_get_a_room(self):
		grupo = self.grupo(10, [("LUNES", 8, 10)], modalidad="VIRTUAL")
		self.reasignar()
		self.assertEqual(self.salon(grupo), [None])

	def test_growing_group_moves_to_a_better_room_without_clashes(self):
		grupo = self.grupo(18, [("LUNES", 8, 10)])
		self.reasignar()
		self.assertEqual(self.salon(grupo), ["A-20"])
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.patch(f"/api/grupos/{grupo.id}/", {"estudiantes_matriculados": 25}, format="json")
		self.assertEqual(response.status_code, 200, response.content)
		self.assertEqual(self.salon(grupo), ["A-30"])

	def test_new_group_gets_its_room_when_saved(self):
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.post("/api/grupos/", {
				"codigo": "N1", "materia": self.materia.id, "periodo": self.periodo.id,
				"profesor": Profesor.objects.create(nombre="Nuevo", codigo="NV1").id,
				"modalidad": "PRESENCIAL", "estudiantes_matriculados": 28,
				"horarios": [{"dia": "MIERCOLES", "hora_inicio": "08:00", "hora_fin": "10:00"}],
			}, format="json")
		self.assertEqual(response.status_code, 201, response.content)
		self.assertEqual(response.json()["horarios"][0]["aula_nombre"], None)  # aún no calculado al responder
		self.assertEqual(Horario.objects.get(grupo_id=response.json()["id"]).aula.nombre, "A-30")

	def test_manual_room_is_pinned_and_can_be_a_laboratory(self):
		grupo = self.grupo(20, [("LUNES", 8, 10)])
		horario = grupo.horarios.get()
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.post(f"/api/horarios/{horario.id}/asignar-aula/", {"aula": self.lab.id}, format="json")
		self.assertEqual(response.status_code, 200, response.content)
		self.reasignar()
		horario.refresh_from_db()
		self.assertEqual((horario.aula_id, horario.aula_fijada), (self.lab.id, True))

	def test_options_mark_fixed_rooms_as_unavailable_and_auto_rooms_as_relocatable(self):
		fijo = self.grupo(10, [("LUNES", 8, 10)])
		self.client.post(f"/api/horarios/{fijo.horarios.get().id}/asignar-aula/", {"aula": self.aula20.id}, format="json")
		auto = self.grupo(25, [("LUNES", 8, 10)])
		self.reasignar()
		opciones = {o["nombre"]: o for o in self.client.get(f"/api/horarios/{auto.horarios.get().id}/aulas-disponibles/").json()}
		self.assertFalse(opciones["A-20"]["disponible"])
		self.assertTrue(opciones["A-30"]["disponible"])
		self.assertTrue(opciones["LAB-X"]["disponible"])

	def test_manual_choice_relocates_the_automatic_group_that_used_the_room(self):
		auto = self.grupo(25, [("LUNES", 8, 10)])
		otro = self.grupo(15, [("LUNES", 8, 10)])
		self.reasignar()
		self.assertEqual(self.salon(auto), ["A-30"])
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.post(f"/api/horarios/{otro.horarios.get().id}/asignar-aula/", {"aula": self.aula30.id}, format="json")
		self.assertEqual(response.status_code, 200, response.content)
		self.assertEqual(self.salon(otro), ["A-30"])
		self.assertEqual(self.salon(auto), [None])  # 25 no cabe en A-20 ni en otra libre

	def test_manual_choice_rejects_small_or_reserved_rooms(self):
		grupo = self.grupo(25, [("LUNES", 8, 10)])
		horario = grupo.horarios.get()
		small = self.client.post(f"/api/horarios/{horario.id}/asignar-aula/", {"aula": self.aula20.id}, format="json")
		self.assertEqual(small.status_code, 400)
		otro = self.grupo(10, [("LUNES", 9, 11)])
		self.client.post(f"/api/horarios/{otro.horarios.get().id}/asignar-aula/", {"aula": self.aula30.id}, format="json")
		busy = self.client.post(f"/api/horarios/{horario.id}/asignar-aula/", {"aula": self.aula30.id}, format="json")
		self.assertEqual(busy.status_code, 400)

	def test_returning_to_automatic_unpins_the_block(self):
		grupo = self.grupo(20, [("LUNES", 8, 10)])
		horario = grupo.horarios.get()
		self.client.post(f"/api/horarios/{horario.id}/asignar-aula/", {"aula": self.lab.id}, format="json")
		with self.captureOnCommitCallbacks(execute=True):
			self.client.post(f"/api/horarios/{horario.id}/asignar-aula/", {"aula": None}, format="json")
		horario.refresh_from_db()
		self.assertFalse(horario.aula_fijada)
		self.assertEqual(horario.aula.nombre, "A-20")

	def test_editing_schedule_keeps_pinned_room(self):
		grupo = self.grupo(20, [("LUNES", 8, 10)])
		horario = grupo.horarios.get()
		self.client.post(f"/api/horarios/{horario.id}/asignar-aula/", {"aula": self.lab.id}, format="json")
		with self.captureOnCommitCallbacks(execute=True):
			response = self.client.patch(f"/api/grupos/{grupo.id}/", {"horarios": [
				{"dia": "LUNES", "hora_inicio": "08:00", "hora_fin": "10:00"},
				{"dia": "MARTES", "hora_inicio": "08:00", "hora_fin": "10:00"},
			]}, format="json")
		self.assertEqual(response.status_code, 200, response.content)
		pinned = grupo.horarios.get(dia="LUNES")
		self.assertEqual((pinned.aula_id, pinned.aula_fijada), (self.lab.id, True))

	def test_limit_considers_rooms_pinned_by_other_groups_in_that_slot(self):
		fijo = self.grupo(10, [("LUNES", 8, 10)])
		self.client.post(f"/api/horarios/{fijo.horarios.get().id}/asignar-aula/", {"aula": self.aula30.id}, format="json")
		grupo = self.grupo(10, [("LUNES", 8, 10)])
		self.reasignar()
		response = self.client.patch(f"/api/grupos/{grupo.id}/", {"estudiantes_matriculados": 25}, format="json")
		# solo queda A-20 libre en esa franja: no cabe, pero otro grupo de la materia tiene cupo -> pregunta
		self.assertEqual(response.status_code, 409, response.content)
		self.assertEqual(response.json()["maximo"], 20)


class IntegridadDeDatosTests(APITestCase):
	def setUp(self):
		self.client.force_authenticate(user=get_user_model().objects.create_superuser(
			username="admin_integridad", password="ClaveSegura123!",
		))
		self.periodo = PeriodoAcademico.objects.create(codigo="2026-B")
		self.profesor = Profesor.objects.create(nombre="Profe integridad", codigo="INT1")
		self.materia_a = Materia.objects.create(codigo="INT-A", nombre="Materia A")
		self.materia_b = Materia.objects.create(codigo="INT-B", nombre="Materia B")

	def test_group_code_is_unique_per_subject_not_per_period(self):
		Grupo.objects.create(codigo="01", materia=self.materia_a, periodo=self.periodo, profesor=self.profesor)
		Grupo.objects.create(codigo="01", materia=self.materia_b, periodo=self.periodo, profesor=self.profesor)
		with self.assertRaises(IntegrityError), transaction.atomic():
			Grupo.objects.create(codigo="01", materia=self.materia_a, periodo=self.periodo, profesor=self.profesor)

	def test_database_rejects_inverted_or_out_of_sync_schedule(self):
		grupo = Grupo.objects.create(codigo="01", materia=self.materia_a, periodo=self.periodo, profesor=self.profesor)
		horario = Horario(grupo=grupo, dia="LUNES", hora_inicio=time(8, 0), hora_fin=time(10, 0))
		horario.save()
		with self.assertRaises(IntegrityError), transaction.atomic():
			Horario.objects.filter(pk=horario.pk).update(hora_inicio=time(11, 0))
		with self.assertRaises(IntegrityError), transaction.atomic():
			Horario.objects.filter(pk=horario.pk).update(inicio_minuto=1)

	def test_room_chosen_through_horarios_api_is_pinned(self):
		aula = Aula.objects.create(nombre="INT-AULA", sillas=30)
		grupo = Grupo.objects.create(codigo="01", materia=self.materia_a, periodo=self.periodo, profesor=self.profesor)
		response = self.client.post("/api/horarios/", {
			"grupo": grupo.id, "aula": aula.id, "dia": "LUNES", "hora_inicio": "08:00", "hora_fin": "10:00",
		}, format="json")
		self.assertEqual(response.status_code, 201, response.content)
		self.assertTrue(Horario.objects.get(pk=response.json()["id"]).aula_fijada)
		sin_aula = self.client.post("/api/horarios/", {
			"grupo": grupo.id, "dia": "MARTES", "hora_inicio": "08:00", "hora_fin": "10:00",
		}, format="json")
		self.assertFalse(Horario.objects.get(pk=sin_aula.json()["id"]).aula_fijada)

	def test_expired_session_answers_401_and_missing_permission_403(self):
		self.client.force_authenticate(user=None)
		self.assertEqual(self.client.get("/api/grupos/").status_code, 401)
		coordinador = get_user_model().objects.create_user(username="coord_int", password="ClaveSegura123!")
		coordinador.groups.add(Group.objects.get(name="Coordinador"))
		self.client.force_authenticate(user=coordinador)
		self.assertEqual(self.client.get("/api/grupos/").status_code, 200)
		self.assertEqual(self.client.delete("/api/grupos/1/").status_code, 403)


class LimiteDeIntentosDeSesionTests(TestCase):
	def setUp(self):
		cache.clear()
		self.addCleanup(cache.clear)
		self.usuario = get_user_model().objects.create_superuser(username="limite", password="ClaveSegura123!")
		self.client = Client(enforce_csrf_checks=False)

	def intentar(self, clave):
		return self.client.post("/api/auth/login/", json.dumps({"username": "limite", "password": clave}), content_type="application/json")

	def test_blocks_after_five_failed_attempts_even_with_the_right_password(self):
		for _ in range(5):
			self.assertEqual(self.intentar("incorrecta").status_code, 401)
		self.assertEqual(self.intentar("ClaveSegura123!").status_code, 429)

	def test_successful_login_resets_the_counter(self):
		for _ in range(4):
			self.intentar("incorrecta")
		self.assertEqual(self.intentar("ClaveSegura123!").status_code, 200)
		for _ in range(4):
			self.assertEqual(self.intentar("incorrecta").status_code, 401)


class ProfesorMateriasTests(APITestCase):
	def setUp(self):
		self.client.force_authenticate(user=get_user_model().objects.create_superuser(username="admin_pm", password="ClaveSegura123!"))
		self.a = Materia.objects.create(codigo="PM-A", nombre="Álgebra")
		self.b = Materia.objects.create(codigo="PM-B", nombre="Biología")

	def test_professor_can_teach_several_subjects(self):
		response = self.client.post("/api/profesores/", {"nombre": "Profe", "codigo": "PM1", "materias": [self.a.id, self.b.id]}, format="json")
		self.assertEqual(response.status_code, 201, response.content)
		self.assertEqual(sorted(response.json()["materias_nombres"]), ["Biología", "Álgebra"])
		actualizado = self.client.patch(f"/api/profesores/{response.json()['id']}/", {"materias": [self.b.id]}, format="json")
		self.assertEqual(actualizado.json()["materias_nombres"], ["Biología"])

	def test_deleting_a_subject_only_unlinks_it_from_professors(self):
		profesor = Profesor.objects.create(nombre="Profe 2", codigo="PM2")
		profesor.materias.add(self.a)
		self.assertEqual(self.client.delete(f"/api/materias/{self.a.id}/").status_code, 204)
		self.assertEqual(profesor.materias.count(), 0)
