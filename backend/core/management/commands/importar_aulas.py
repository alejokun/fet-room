from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from core.models import Aula, AulaSeccion


EXCLUDED_ROOM = "LABORATORIO ENSABLE Y MANTEMINIENTO"


def decimal_or_none(value):
	if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
		return None
	return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def integer_or_none(value):
	if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
		return None
	if Decimal(str(value)) % 1:
		raise CommandError(f"Se esperaba un entero y se encontró {value!r}.")
	return int(value)


def normalized_text(value):
	if value is None:
		return ""
	return str(value).strip().casefold()


def room_type(name):
	upper_name = name.upper()
	if "AUDITORIO" in upper_name:
		return Aula.Tipo.AUDITORIO
	if "LAB" in upper_name or "LABORATORIO" in upper_name:
		return Aula.Tipo.LABORATORIO
	return Aula.Tipo.AULA


class Command(BaseCommand):
	help = "Importa de forma repetible el inventario de aulas del Excel 2026-B."

	def add_arguments(self, parser):
		parser.add_argument(
			"--archivo",
			type=Path,
			default=settings.BASE_DIR.parent / "Capacidad_Instalada_Aulas_2026-B.xlsx",
		)
		parser.add_argument(
			"--dry-run",
			action="store_true",
			help="Valida y resume la importación sin escribir cambios.",
		)
		parser.add_argument(
			"--incluir-item-26",
			action="store_true",
			help="Incluye LABORATORIO ENSABLE Y MANTEMINIENTO, excluido temporalmente.",
		)

	def handle(self, *args, **options):
		path = options["archivo"]
		if not path.is_file():
			raise CommandError(f"No se encontró el archivo: {path}")

		workbook = load_workbook(path, data_only=True, read_only=True)
		if not {"Bloque 1", "Bloque 2"}.issubset(workbook.sheetnames):
			raise CommandError("El libro debe contener las hojas 'Bloque 1' y 'Bloque 2'.")

		records = []
		for sheet_name, sheet in (("Bloque 1", workbook["Bloque 1"]), ("Bloque 2", workbook["Bloque 2"])):
			for row_number in range(5, sheet.max_row + 1):
				values = [sheet.cell(row_number, column).value for column in range(1, sheet.max_column + 1)]
				item, raw_name = values[0], values[1]
				if item is None or raw_name is None:
					continue

				name = str(raw_name).strip()
				if sheet_name == "Bloque 1":
					section_pairs = ((values[2], values[3]), (values[4], values[5]))
					source_area, chair_space, chairs, tables, observation = values[6:11]
				else:
					section_pairs = ((values[2], values[3]),)
					source_area, chair_space, chairs, tables, observation = values[4:9]

				sections = []
				for length, width in section_pairs:
					length_value = decimal_or_none(length)
					width_value = decimal_or_none(width)
					if (length_value is None) != (width_value is None):
						raise CommandError(f"Dimensiones incompletas en {sheet_name}, fila {row_number}: {name}.")
					if length_value is not None:
						sections.append((length_value, width_value))

				calculated_area = sum(
					(length * width).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
					for length, width in sections
				)
				source_area_value = decimal_or_none(source_area)
				if source_area_value is not None and sections and source_area_value != calculated_area:
					raise CommandError(
						f"El área no coincide en {sheet_name}, fila {row_number}, {name}: "
						f"Excel={source_area_value}, calculada={calculated_area}."
					)

				if name.casefold() == EXCLUDED_ROOM.casefold() and not options["incluir_item_26"]:
					continue

				chairs_value = integer_or_none(chairs)
				tables_value = integer_or_none(tables)
				tables_state = normalized_text(tables)
				if tables_value is not None:
					tables_applicable = True
				elif tables_state == "no aplica":
					tables_applicable = False
				else:
					tables_applicable = None

				records.append({
					"item": item,
					"sheet": sheet_name,
					"row": row_number,
					"name": name,
					"block": sheet_name,
					"type": room_type(name),
					"exists": normalized_text(values[2]) != "no existe",
					"sections": sections,
					"chair_space": decimal_or_none(chair_space),
					"chairs": chairs_value,
					"tables": tables_value,
					"tables_applicable": tables_applicable,
					"observation": "" if normalized_text(observation) in ("sin dato", "no existe") else str(observation or "").strip(),
				})

		seen_names = set()
		for record in records:
			key = record["name"].casefold()
			if key in seen_names:
				raise CommandError(f"Nombre de espacio duplicado en el Excel: {record['name']}.")
			seen_names.add(key)

		created = 0
		updated = 0
		if options["dry_run"]:
			for record in records:
				if Aula.objects.filter(nombre__iexact=record["name"]).exists():
					updated += 1
				else:
					created += 1
		else:
			with transaction.atomic():
				for record in records:
					aulas = Aula.objects.select_for_update().filter(nombre__iexact=record["name"])
					if aulas.count() > 1:
						raise CommandError(f"Hay varios registros en la base que coinciden con {record['name']}.")
					aula = aulas.first()
					if aula is None:
						aula = Aula(nombre=record["name"])
						created += 1
					else:
						updated += 1
						aula.nombre = record["name"]

					aula.bloque = record["block"]
					aula.tipo = record["type"]
					aula.espacio_por_silla = record["chair_space"]
					aula.sillas = record["chairs"]
					aula.mesas = record["tables"]
					aula.mesas_aplicables = record["tables_applicable"]
					aula.observacion = record["observation"]
					aula.existe = record["exists"]
					aula.save()

					for section_number, (length, width) in enumerate(record["sections"], start=1):
						AulaSeccion.objects.update_or_create(
							aula=aula,
							numero=section_number,
							defaults={"largo_m": length, "ancho_m": width},
						)
					AulaSeccion.objects.filter(aula=aula, numero__gt=len(record["sections"])).delete()
					if not record["sections"]:
						AulaSeccion.objects.filter(aula=aula).delete()

		active_count = sum(record["exists"] for record in records)
		inactive_count = len(records) - active_count
		mode = "Simulación" if options["dry_run"] else "Importación"
		self.stdout.write(self.style.SUCCESS(
			f"{mode} validada: {len(records)} registros ({created} nuevos, {updated} actualizados; "
			f"{active_count} existentes, {inactive_count} marcados NO EXISTE)."
		))
		if not options["incluir_item_26"]:
			self.stdout.write(f"Ítem 26 excluido temporalmente: {EXCLUDED_ROOM}.")