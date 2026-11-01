import json

from django.core.cache import cache

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework.exceptions import ValidationError
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import DjangoModelPermissions

from .asignacion import programar_reasignacion
from .models import Aula, Grupo, Horario, Materia, PeriodoAcademico, Profesor, Programa
from .serializers import (
	AulaSerializer,
	AulaWriteSerializer,
	GrupoSerializer,
	MateriaSerializer,
	HorarioSerializer,
	PeriodoAcademicoSerializer,
	ProfesorSerializer,
	ProgramaSerializer,
)


class AulaViewSet(ModelViewSet):
	queryset = Aula.objects.prefetch_related("secciones").all()
	permission_classes = (DjangoModelPermissions,)

	def get_serializer_class(self):
		if self.action in ("create", "update", "partial_update"):
			return AulaWriteSerializer
		return AulaSerializer

	def perform_destroy(self, instance):
		try:
			instance.delete()
		except ProtectedError as error:
			raise ValidationError({"detail": "No se puede eliminar el aula porque está asignada a uno o más horarios."}) from error


class ProfesorViewSet(ModelViewSet):
	queryset = Profesor.objects.prefetch_related("programas", "materias").all()
	serializer_class = ProfesorSerializer
	permission_classes = (DjangoModelPermissions,)

	def perform_destroy(self, instance):
		try:
			instance.delete()
		except ProtectedError as error:
			raise ValidationError({"detail": "No se puede eliminar el profesor porque está asignado a uno o más grupos."}) from error


class MateriaViewSet(ModelViewSet):
	queryset = Materia.objects.all()
	serializer_class = MateriaSerializer
	permission_classes = (DjangoModelPermissions,)

	def perform_destroy(self, instance):
		try:
			instance.delete()
		except ProtectedError as error:
			raise ValidationError({"detail": "No se puede eliminar la materia porque tiene grupos asociados."}) from error


class GrupoViewSet(ModelViewSet):
	queryset = Grupo.objects.select_related("materia", "periodo", "profesor").prefetch_related(
		"horarios__aula",
	).all()
	serializer_class = GrupoSerializer
	permission_classes = (DjangoModelPermissions,)


class HorarioViewSet(ModelViewSet):
	queryset = Horario.objects.select_related(
		"grupo__materia", "grupo__periodo", "grupo__profesor", "aula",
	).all()
	serializer_class = HorarioSerializer
	permission_classes = (DjangoModelPermissions,)

	def _conflictos(self, horario, aula):
		return Horario.objects.filter(
			periodo_id=horario.periodo_id,
			dia=horario.dia,
			aula=aula,
			inicio_minuto__lt=horario.fin_minuto,
			fin_minuto__gt=horario.inicio_minuto,
		).exclude(pk=horario.pk).select_related("grupo__materia")

	@action(detail=True, methods=["get"], url_path="aulas-disponibles")
	def aulas_disponibles(self, request, pk=None):
		"""Todos los salones existentes, indicando cuáles se pueden usar en este bloque."""
		horario = self.get_object()
		personas = horario.grupo.estudiantes_matriculados
		opciones = []
		for aula in Aula.objects.filter(existe=True).order_by("bloque", "nombre"):
			disponible, motivo, aviso = True, "", ""
			capacidad = aula.capacidad
			choques = list(self._conflictos(horario, aula))
			fijos = [c for c in choques if c.aula_fijada]
			if capacidad is not None and capacidad < personas:
				disponible, motivo = False, f"Capacidad insuficiente ({capacidad} para {personas})"
			elif fijos:
				c = fijos[0]
				disponible, motivo = False, f"Ocupada: {c.grupo.materia.nombre} · grupo {c.grupo.codigo}"
			elif choques:
				c = choques[0]
				aviso = f"La usa {c.grupo.materia.nombre} · grupo {c.grupo.codigo}; ese grupo se reubicará"
			elif capacidad is None:
				aviso = "Sin capacidad registrada; verifica manualmente"
			opciones.append({
				"id": aula.pk, "nombre": aula.nombre, "bloque": aula.bloque, "tipo": aula.tipo,
				"capacidad": capacidad, "disponible": disponible, "motivo": motivo, "aviso": aviso,
				"actual": horario.aula_id == aula.pk,
			})
		return Response(opciones)

	@action(detail=True, methods=["post"], url_path="asignar-aula")
	def asignar_aula(self, request, pk=None):
		"""Fija un salón a mano (aula=id) o devuelve el bloque a la asignación automática (aula=null)."""
		horario = self.get_object()
		if "aula" not in request.data:
			raise ValidationError({"aula": "Indica el aula o null para volver a automático."})
		aula_id = request.data["aula"]
		try:
			with transaction.atomic():
				if aula_id is None:
					Horario.objects.filter(pk=horario.pk).update(aula=None, aula_fijada=False)
					programar_reasignacion()
				else:
					aula = Aula.objects.filter(pk=aula_id, existe=True).first()
					if aula is None:
						raise ValidationError({"aula": "El aula no existe."})
					choques = list(self._conflictos(horario, aula))
					if any(c.aula_fijada for c in choques):
						raise ValidationError({"aula": "El aula ya está reservada a mano en ese horario."})
					# los bloques automáticos que la usaban se reubican después
					Horario.objects.filter(pk__in=[c.pk for c in choques]).update(aula=None)
					horario.aula = aula
					horario.aula_fijada = True
					horario.save()
		except DjangoValidationError as error:
			detalle = error.message_dict if hasattr(error, "message_dict") else error.messages
			raise ValidationError({"aula": detalle}) from error
		except IntegrityError as error:
			raise ValidationError({"aula": "El aula se cruza con otro horario."}) from error
		horario.refresh_from_db()
		return Response({"id": horario.pk, "aula": horario.aula_id, "aula_fijada": horario.aula_fijada})


class ProgramaViewSet(ModelViewSet):
	queryset = Programa.objects.all()
	serializer_class = ProgramaSerializer
	permission_classes = (DjangoModelPermissions,)

	def perform_destroy(self, instance):
		if instance.profesores.exists():
			raise ValidationError({"detail": "No se puede eliminar un programa asignado a profesores."})
		instance.delete()


class PeriodoAcademicoViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = PeriodoAcademico.objects.all()
	serializer_class = PeriodoAcademicoSerializer
	permission_classes = (DjangoModelPermissions,)


MAX_INTENTOS_LOGIN = 5
VENTANA_LOGIN_SEGUNDOS = 5 * 60


def _user_payload(user):
	return {
		"username": user.get_username(),
		"groups": list(user.groups.values_list("name", flat=True)),
		"can_manage": user.is_superuser or user.has_perm("core.change_aula"),
	}


@ensure_csrf_cookie
@require_GET
def csrf_token(request):
	return JsonResponse({"detail": "CSRF cookie establecida."})


@csrf_protect
@require_POST
def session_login(request):
	try:
		credentials = json.loads(request.body)
	except (json.JSONDecodeError, UnicodeDecodeError):
		return JsonResponse({"detail": "Solicitud inválida."}, status=400)

	username = str(credentials.get("username", ""))
	intentos_key = f"login-fallidos:{request.META.get('REMOTE_ADDR', '')}:{username.strip().lower()}"
	if cache.get(intentos_key, 0) >= MAX_INTENTOS_LOGIN:
		return JsonResponse(
			{"detail": "Demasiados intentos fallidos. Espera unos minutos antes de volver a intentarlo."},
			status=429,
		)

	user = authenticate(
		request,
		username=username,
		password=credentials.get("password", ""),
	)
	if user is None or not user.groups.filter(name__in=("Administrador", "Coordinador")).exists() and not user.is_superuser:
		cache.set(intentos_key, cache.get(intentos_key, 0) + 1, VENTANA_LOGIN_SEGUNDOS)
		return JsonResponse({"detail": "Credenciales inválidas o usuario sin rol asignado."}, status=401)

	cache.delete(intentos_key)
	login(request, user)
	return JsonResponse(_user_payload(user))


@require_GET
def session_status(request):
	if not request.user.is_authenticated:
		return JsonResponse({"detail": "No hay una sesión activa."}, status=401)
	return JsonResponse(_user_payload(request.user))


@csrf_protect
@require_POST
def session_logout(request):
	if not request.user.is_authenticated:
		return JsonResponse({"detail": "No hay una sesión activa."}, status=401)
	logout(request)
	return JsonResponse({"detail": "Sesión cerrada."})
