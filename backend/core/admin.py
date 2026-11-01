from django.contrib import admin, messages

from .models import Aula, AulaSeccion, Grupo, Horario, Materia, PeriodoAcademico, Profesor, Programa


class AulaSeccionInline(admin.TabularInline):
	model = AulaSeccion
	extra = 0


@admin.register(Aula)
class AulaAdmin(admin.ModelAdmin):
	list_display = ("nombre", "bloque", "tipo", "area_m2", "capacidad", "sillas", "mesas", "existe")
	list_filter = ("bloque", "tipo", "existe")
	search_fields = ("nombre", "observacion")
	list_editable = ("existe",)
	inlines = (AulaSeccionInline,)


@admin.register(Materia)
class MateriaAdmin(admin.ModelAdmin):
	list_display = ("codigo", "nombre")
	search_fields = ("codigo", "nombre")


@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
	list_display = ("codigo", "nombre", "materias_dictadas")
	list_filter = ("programas",)
	search_fields = ("codigo", "nombre", "materias__nombre")
	ordering = ("nombre",)
	filter_horizontal = ("programas", "materias")

	@admin.display(description="materias")
	def materias_dictadas(self, profesor):
		return ", ".join(m.nombre for m in profesor.materias.all()) or "—"


@admin.register(Programa)
class ProgramaAdmin(admin.ModelAdmin):
	list_display = ("codigo", "nombre")
	search_fields = ("codigo", "nombre")


@admin.register(PeriodoAcademico)
class PeriodoAcademicoAdmin(admin.ModelAdmin):
	list_display = ("codigo", "fecha_inicio", "fecha_fin")
	search_fields = ("codigo",)


class HorarioInline(admin.TabularInline):
	model = Horario
	extra = 0
	exclude = ("periodo", "profesor", "aula_fijada")


@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
	list_display = ("codigo", "materia", "periodo", "modalidad", "profesor", "estudiantes_matriculados")
	list_filter = ("periodo", "materia", "profesor", "modalidad")
	search_fields = ("codigo", "materia__codigo", "materia__nombre", "profesor__nombre")
	inlines = (HorarioInline,)

	def save_formset(self, request, form, formset, change):
		# un salón elegido a mano queda fijado; vaciarlo devuelve el bloque a la asignación automática
		for horario_form in formset.forms:
			if "aula" in horario_form.changed_data and horario_form.instance is not None:
				horario_form.instance.aula_fijada = horario_form.cleaned_data.get("aula") is not None
		super().save_formset(request, form, formset, change)


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
	list_display = ("grupo", "dia", "hora_inicio", "hora_fin", "aula", "aula_fijada")
	list_filter = ("dia", "grupo__periodo", "aula__bloque")
	search_fields = ("grupo__codigo", "grupo__materia__nombre", "aula__nombre")
	exclude = ("periodo", "profesor")

	def save_model(self, request, obj, form, change):
		if "aula" in form.changed_data:
			obj.aula_fijada = obj.aula_id is not None
		super().save_model(request, obj, form, change)
		if obj.aula_id and obj.aula.capacidad is None:
			self.message_user(
				request,
				f"Advertencia: {obj.aula.nombre} no tiene capacidad definida; verifica manualmente el tamaño del grupo.",
				level=messages.WARNING,
			)
