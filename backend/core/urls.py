from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AulaViewSet,
    GrupoViewSet,
    HorarioViewSet,
    MateriaViewSet,
    PeriodoAcademicoViewSet,
    ProgramaViewSet,
    ProfesorViewSet,
    csrf_token,
    session_login,
    session_logout,
    session_status,
)

router = DefaultRouter()
router.register("aulas", AulaViewSet, basename="aula")
router.register("profesores", ProfesorViewSet, basename="profesor")
router.register("materias", MateriaViewSet, basename="materia")
router.register("grupos", GrupoViewSet, basename="grupo")
router.register("periodos", PeriodoAcademicoViewSet, basename="periodo")
router.register("horarios", HorarioViewSet, basename="horario")
router.register("programas", ProgramaViewSet, basename="programa")

urlpatterns = [
    path("csrf/", csrf_token, name="csrf-token"),
    path("auth/login/", session_login, name="session-login"),
    path("auth/session/", session_status, name="session-status"),
    path("auth/logout/", session_logout, name="session-logout"),
    path("", include(router.urls)),
]