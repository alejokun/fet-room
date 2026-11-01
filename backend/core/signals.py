from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_delete, post_migrate, post_save


def configure_role_groups(sender, **kwargs):
    if sender.label != "core":
        return

    administrator, _ = Group.objects.get_or_create(name="Administrador")
    administrator.permissions.set(Permission.objects.all())

    coordinator, _ = Group.objects.get_or_create(name="Coordinador")
    read_permissions = Permission.objects.filter(
        content_type__app_label="core",
        codename__in=(
            "view_aula",
            "view_materia",
            "view_profesor",
            "view_programa",
            "view_materia",
            "view_periodoacademico",
            "view_grupo",
            "view_horario",
            "generar_informes",
        ),
    )
    coordinator.permissions.set(read_permissions)


post_migrate.connect(
    configure_role_groups,
    dispatch_uid="core.configure_role_groups",
)

def connect_reassignment():
    from .asignacion import programar_reasignacion
    from .models import Aula, Grupo, Horario

    for model in (Grupo, Horario, Aula):
        for signal in (post_save, post_delete):
            signal.connect(
                programar_reasignacion,
                sender=model,
                dispatch_uid=f"core.reassign.{signal.__class__.__name__}.{model.__name__}",
            )


connect_reassignment()
