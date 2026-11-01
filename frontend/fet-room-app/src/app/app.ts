import { HttpErrorResponse } from '@angular/common/http';
import { TitleCasePipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Aula, AulaPayload, AulasService } from './aulas.service';
import { AuthService } from './auth.service';
import { AulaOpcion, ExcedeCapacidad, GrupoOferta, GrupoPayload, HorarioGrupo, Materia, MateriaPayload, OfertasService, PeriodoAcademico } from './ofertas.service';
import { Profesor, ProfesorPayload, ProfesoresService, Programa } from './profesores.service';

interface AulaSectionDraft {
  largo_m: number | null;
  ancho_m: number | null;
}

interface AulaDraft {
  nombre: string;
  bloque: string;
  tipo: string;
  espacio_por_silla: number | null;
  sillas: number | null;
  mesas: number | null;
  mesas_aplicables: boolean | null;
  capacidad_manual: number | null;
  observacion: string;
  existe: boolean;
  secciones: AulaSectionDraft[];
}

interface ProfesorDraft {
  codigo: string;
  nombre: string;
  programas: number[];
  materias: number[];
}

interface GrupoDraft {
  codigo: string;
  materia: number | null;
  periodo: number | null;
  modalidad: 'PRESENCIAL' | 'VIRTUAL';
  profesor: number | null;
  estudiantes_matriculados: number;
  horarios: HorarioGrupo[];
}

interface MateriaDraft {
  codigo: string;
  nombre: string;
}

/** Medidas (px) del espacio de trabajo de la asignación. */
const GROUP_W = 300;
const GROUP_H = 76;
const ROOM_W = 250;
const ROOM_H = 76;
const ROW_GAP = 104;
const GROUP_X = 60;
const ROOM_X = 560;
const TOP = 96;
const PROGRAM_COLORS = ['#2f8f6b', '#3b82c4', '#d98a1f', '#8a5bd1', '#d4574a', '#1f9aa8'];

interface BloqueGrupo { key: string; grupo: GrupoOferta; horario: HorarioGrupo | null; x: number; y: number; color: string; programas: string }
interface BloqueSalon { key: string; grupo: GrupoOferta; horario: HorarioGrupo; aula: Aula | null; nombre: string | null; x: number; y: number }
interface Cable { key: string; d: string; color: string }

type Vista = 'aulas' | 'profesores' | 'ofertas' | 'asignacion';
const VISTAS: readonly Vista[] = ['aulas', 'profesores', 'ofertas', 'asignacion'];

/** La vista activa vive en la URL (#profesores, #asignacion…) para sobrevivir a una recarga. */
const vistaInicial = (): Vista => {
  const guardada = window.location.hash.replace('#', '') as Vista;
  return VISTAS.includes(guardada) ? guardada : 'aulas';
};

const emptyAulaDraft = (): AulaDraft => ({
  nombre: '',
  bloque: 'Bloque 1',
  tipo: 'AULA',
  espacio_por_silla: 1.5,
  sillas: null,
  mesas: null,
  mesas_aplicables: null,
  capacidad_manual: null,
  observacion: '',
  existe: true,
  secciones: [{ largo_m: null, ancho_m: null }],
});

const emptyProfesorDraft = (): ProfesorDraft => ({
  codigo: '',
  nombre: '',
  programas: [],
  materias: [],
});

const emptyGrupoDraft = (): GrupoDraft => ({
  codigo: '',
  materia: null,
  periodo: null,
  modalidad: 'PRESENCIAL',
  profesor: null,
  estudiantes_matriculados: 0,
  horarios: [],
});

const emptyMateriaDraft = (): MateriaDraft => ({ codigo: '', nombre: '' });

@Component({
  selector: 'app-root',
  imports: [FormsModule, TitleCasePipe],
  templateUrl: './app.html',
  host: {
    '(document:keydown.escape)': 'closeDialogs()',
    '(document:pointermove)': 'onPointerMove($event)',
    '(document:pointerup)': 'onPointerUp()',
    '(document:pointercancel)': 'onPointerUp()',
  },
})
export class App {
  private readonly aulasService = inject(AulasService);
  private readonly profesoresService = inject(ProfesoresService);
  private readonly ofertasService = inject(OfertasService);
  protected readonly auth = inject(AuthService);
  protected readonly aulas = signal<Aula[]>([]);
  protected readonly profesores = signal<Profesor[]>([]);
  protected readonly programas = signal<Programa[]>([]);
  protected readonly materias = signal<Materia[]>([]);
  protected readonly grupos = signal<GrupoOferta[]>([]);
  protected readonly periodos = signal<PeriodoAcademico[]>([]);
  protected readonly activeView = signal<Vista>(vistaInicial());
  protected readonly programaFiltro = signal<number | null>(null);
  protected readonly blockPos = signal<Record<string, { x: number; y: number }>>({});
  protected readonly pan = signal({ x: 0, y: 0 });
  protected readonly dragging = signal(false);
  private drag: { kind: 'pan' | 'block'; key: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null = null;
  protected readonly loading = signal(false);
  protected readonly apiConnected = signal(false);
  protected readonly submitting = signal(false);
  protected readonly error = signal('');
  protected readonly search = signal('');
  protected readonly statusFilter = signal('todas');
  protected readonly blockFilter = signal('todos');
  protected readonly peopleSearch = signal('');
  protected readonly aulaEditorOpen = signal(false);
  protected readonly profesorEditorOpen = signal(false);
  protected readonly grupoEditorOpen = signal(false);
  protected readonly materiaEditorOpen = signal(false);
  protected readonly saving = signal(false);
  protected readonly dialogError = signal('');
  protected readonly ajustando = signal<ReadonlySet<number>>(new Set());
  protected readonly toasts = signal<Array<{ id: number; message: string; kind: 'error' | 'success' }>>([]);
  protected readonly confirmState = signal<{ title: string; message: string; action: () => void; label: string; danger: boolean } | null>(null);
  protected readonly aulaSort = signal<{ key: string; dir: 1 | -1 }>({ key: 'nombre', dir: 1 });
  protected readonly profesorSort = signal<{ key: string; dir: 1 | -1 }>({ key: 'nombre', dir: 1 });
  private toastSeq = 0;
  protected editingAulaId: number | null = null;
  protected editingProfesorId: number | null = null;
  protected aulaDraft = emptyAulaDraft();
  protected profesorDraft = emptyProfesorDraft();
  protected grupoDraft = emptyGrupoDraft();
  protected materiaDraft = emptyMateriaDraft();
  protected username = '';
  protected password = '';
  protected editingGrupoId: number | null = null;
  protected editingMateriaId: number | null = null;

  protected readonly aulasVisibles = computed(() => {
    const query = this.search().trim().toLocaleLowerCase();
    const { key, dir } = this.aulaSort();
    return this.aulas().filter((aula) => {
      const matchesQuery = !query || [aula.nombre, aula.bloque, aula.tipo]
        .some((value) => value.toLocaleLowerCase().includes(query));
      const matchesStatus = this.statusFilter() === 'todas'
        || (this.statusFilter() === 'existentes' && aula.existe)
        || (this.statusFilter() === 'inexistentes' && !aula.existe);
      const matchesBlock = this.blockFilter() === 'todos' || aula.bloque === this.blockFilter();
      return matchesQuery && matchesStatus && matchesBlock;
    }).sort((first, second) => this.compareValues(this.aulaSortValue(first, key), this.aulaSortValue(second, key)) * dir);
  });

  protected readonly hasAulaFilters = computed(() =>
    Boolean(this.search().trim()) || this.statusFilter() !== 'todas' || this.blockFilter() !== 'todos');

  protected readonly aulasActivas = computed(() => this.aulas().filter((aula) => aula.existe).length);
  protected readonly sillasDisponibles = computed(() => this.aulas()
    .filter((aula) => aula.existe)
    .reduce((total, aula) => total + (aula.capacidad ?? 0), 0));
  protected readonly espaciosEspeciales = computed(() => this.aulas()
    .filter((aula) => aula.tipo !== 'AULA').length);
  protected readonly aulasInexistentes = computed(() => this.aulas().filter((aula) => !aula.existe).length);
  protected readonly canManage = computed(() => Boolean(
    this.auth.session()?.can_manage || this.auth.session()?.groups.includes('Administrador'),
  ));
  protected readonly profesoresVisibles = computed(() => {
    const query = this.peopleSearch().trim().toLocaleLowerCase();
    const { key, dir } = this.profesorSort();
    return this.profesores().filter((profesor) =>
      !query || [profesor.codigo ?? '', profesor.nombre, profesor.programas_nombres.join(' '), profesor.materias_nombres.join(' ')]
        .some((value) => value.toLocaleLowerCase().includes(query)),
    ).sort((first, second) => this.compareValues(this.profesorSortValue(first, key), this.profesorSortValue(second, key)) * dir);
  });
  protected readonly gruposOrdenados = computed(() => [...this.grupos()].sort((first, second) =>
    first.materia_nombre.localeCompare(second.materia_nombre, 'es')
      || first.periodo_codigo.localeCompare(second.periodo_codigo)
      || first.codigo.localeCompare(second.codigo),
  ));

  /** Programas de cada grupo, según los programas de su profesor. */
  private readonly programasPorGrupo = computed(() => {
    const profesores = new Map(this.profesores().map((profesor) => [profesor.id, profesor]));
    const programas = new Map(this.programas().map((programa) => [programa.id, programa]));
    const result = new Map<number, Programa[]>();
    for (const grupo of this.grupos()) {
      const profesor = grupo.profesor !== null ? profesores.get(grupo.profesor) : undefined;
      result.set(grupo.id, (profesor?.programas ?? [])
        .map((id) => programas.get(id))
        .filter((programa): programa is Programa => programa !== undefined));
    }
    return result;
  });

  protected readonly gruposVisibles = computed(() => {
    const filtro = this.programaFiltro();
    const programas = this.programasPorGrupo();
    return [...this.grupos()]
      .filter((grupo) => filtro === null || (programas.get(grupo.id) ?? []).some((programa) => programa.id === filtro))
      .sort((first, second) =>
        Number(first.modalidad === 'VIRTUAL') - Number(second.modalidad === 'VIRTUAL')
          || first.materia_nombre.localeCompare(second.materia_nombre, 'es')
          || first.codigo.localeCompare(second.codigo));
  });

  /** Resumen de salones de un grupo según los horarios guardados en el servidor. */
  protected resumenSalones(grupo: GrupoOferta): { nombres: string[]; sinSalon: number; total: number } {
    const nombres = [...new Set(grupo.horarios.map((h) => h.aula_nombre).filter((n): n is string => Boolean(n)))];
    return { nombres, sinSalon: grupo.horarios.filter((h) => !h.aula).length, total: grupo.horarios.length };
  }

  /** Panel fijo: grupos por programa; con filtro solo se ve ese programa. */
  protected readonly gruposPorPrograma = computed(() => {
    const filtro = this.programaFiltro();
    const programas = this.programasPorGrupo();
    const mapa = new Map<string, { programa: string; color: string; grupos: GrupoOferta[] }>();
    for (const grupo of this.gruposVisibles()) {
      const delGrupo = programas.get(grupo.id) ?? [];
      const entradas = delGrupo.length ? delGrupo : [null];
      for (const programa of entradas) {
        if (filtro !== null && programa?.id !== filtro) continue;
        const nombre = programa?.nombre ?? 'Sin programa';
        if (!mapa.has(nombre)) mapa.set(nombre, { programa: nombre, color: this.colorDePrograma(programa?.id ?? null), grupos: [] });
        mapa.get(nombre)!.grupos.push(grupo);
      }
    }
    return [...mapa.values()].sort((first, second) => first.programa.localeCompare(second.programa, 'es'));
  });

  /** Bloques y cables del espacio de trabajo (estilo Scratch): una fila por bloque horario. */
  protected readonly espacio = computed(() => {
    const posiciones = this.blockPos();
    const programas = this.programasPorGrupo();
    const aulasPorId = new Map(this.aulas().map((aula) => [aula.id, aula]));
    const grupos: BloqueGrupo[] = [];
    const salones: BloqueSalon[] = [];
    const cables: Cable[] = [];
    let fila = 0;
    for (const grupo of this.gruposVisibles()) {
      const delGrupo = programas.get(grupo.id) ?? [];
      const color = this.colorDePrograma(delGrupo[0]?.id ?? null);
      const etiquetaProgramas = delGrupo.map((programa) => programa.codigo).join(' · ');
      const presencial = grupo.modalidad === 'PRESENCIAL';
      const bloques: Array<HorarioGrupo | null> = presencial && grupo.horarios.length ? grupo.horarios : [null];
      for (const horario of bloques) {
        const base = { x: GROUP_X, y: TOP + fila * ROW_GAP };
        fila++;
        const key = horario ? `h${horario.id}` : `g${grupo.id}`;
        const pos = posiciones[key] ?? base;
        grupos.push({ key, grupo, horario, x: pos.x, y: pos.y, color, programas: etiquetaProgramas });
        if (!horario || !presencial) continue;
        const roomKey = `r${horario.id}`;
        const roomPos = posiciones[roomKey] ?? { x: ROOM_X, y: base.y };
        const aula = horario.aula ? aulasPorId.get(horario.aula) ?? null : null;
        salones.push({ key: roomKey, grupo, horario, aula, nombre: horario.aula_nombre ?? null, x: roomPos.x, y: roomPos.y });
        if (horario.aula) {
          const x1 = pos.x + GROUP_W;
          const y1 = pos.y + GROUP_H / 2;
          const x2 = roomPos.x;
          const y2 = roomPos.y + ROOM_H / 2;
          const dx = Math.max(70, Math.abs(x2 - x1) / 2);
          cables.push({ key: roomKey, color, d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}` });
        }
      }
    }
    return { grupos, salones, cables };
  });

  protected readonly resumenAsignacion = computed(() => {
    const visibles = this.gruposVisibles();
    const presenciales = visibles.filter((grupo) => grupo.modalidad === 'PRESENCIAL');
    const horarios = presenciales.flatMap((grupo) => grupo.horarios);
    return {
      asignados: horarios.filter((h) => h.aula).length,
      sinSalon: horarios.filter((h) => !h.aula).length + presenciales.filter((grupo) => grupo.horarios.length === 0).length,
      virtuales: visibles.length - presenciales.length,
    };
  });

  constructor() {
    effect(() => {
      if (this.auth.session()) {
        this.loadAulas();
        this.loadProfesores();
        this.loadOfertas();
      }
    });
    this.auth.restoreSession();
  }

  protected signIn(): void {
    if (!this.username.trim() || !this.password) {
      this.error.set('Escribe tu usuario y contraseña.');
      return;
    }
    this.submitting.set(true);
    this.error.set('');
    this.auth.login(this.username.trim(), this.password).subscribe({
      next: (session) => {
        this.auth.session.set(session);
        this.password = '';
        this.submitting.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.error.set(this.errorMessage(error, 'No se pudo iniciar sesión.'));
        this.submitting.set(false);
      },
    });
  }

  protected signOut(): void {
    this.auth.logout().subscribe({
      next: () => {
        this.auth.session.set(null);
        this.aulas.set([]);
        this.profesores.set([]);
        this.programas.set([]);
        this.materias.set([]);
        this.grupos.set([]);
        this.periodos.set([]);
        this.programaFiltro.set(null);
        this.resetLayout();
        this.apiConnected.set(false);
        this.error.set('');
      },
      error: () => this.notify('No se pudo cerrar la sesión. Actualiza e inténtalo de nuevo.'),
    });
  }

  protected refresh(): void {
    this.loadAulas();
    this.loadProfesores();
    this.loadOfertas();
  }

  protected setView(view: Vista): void {
    this.activeView.set(view);
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}#${view}`);
    this.error.set('');
  }

  protected openNewAula(): void {
    this.editingAulaId = null;
    this.aulaDraft = emptyAulaDraft();
    this.dialogError.set('');
    this.aulaEditorOpen.set(true);
  }

  protected editAula(aula: Aula): void {
    this.editingAulaId = aula.id;
    this.aulaDraft = {
      nombre: aula.nombre,
      bloque: aula.bloque,
      tipo: aula.tipo,
      espacio_por_silla: this.numberOrNull(aula.espacio_por_silla),
      sillas: aula.sillas,
      mesas: aula.mesas,
      mesas_aplicables: aula.mesas_aplicables,
      capacidad_manual: aula.capacidad_manual,
      observacion: aula.observacion,
      existe: aula.existe,
      secciones: aula.secciones.length
        ? aula.secciones.map((section) => ({
          largo_m: this.numberOrNull(section.largo_m),
          ancho_m: this.numberOrNull(section.ancho_m),
        }))
        : [{ largo_m: null, ancho_m: null }],
    };
    this.dialogError.set('');
    this.aulaEditorOpen.set(true);
  }

  protected addAulaSection(): void {
    this.aulaDraft.secciones.push({ largo_m: null, ancho_m: null });
    this.aulaDraft = { ...this.aulaDraft, secciones: [...this.aulaDraft.secciones] };
  }

  protected removeAulaSection(index: number): void {
    if (this.aulaDraft.secciones.length <= 1) return;
    this.aulaDraft.secciones.splice(index, 1);
    this.aulaDraft = { ...this.aulaDraft, secciones: [...this.aulaDraft.secciones] };
  }

  protected saveAula(): void {
    const hasIncompleteSection = this.aulaDraft.secciones.some(
      (section) => (section.largo_m === null) !== (section.ancho_m === null),
    );
    if (hasIncompleteSection) {
      this.dialogError.set('Completa largo y ancho de cada sección, o deja ambos campos vacíos.');
      return;
    }
    const sections = this.aulaDraft.secciones
      .filter((section) => section.largo_m !== null && section.ancho_m !== null)
      .map((section, index) => ({ numero: index + 1, ...section }));
    const payload: AulaPayload = {
      ...this.aulaDraft,
      nombre: this.aulaDraft.nombre.trim(),
      secciones: sections,
    };
    if (!payload.nombre) {
      this.dialogError.set('El nombre del espacio es obligatorio.');
      return;
    }

    this.saving.set(true);
    this.dialogError.set('');
    const request = this.editingAulaId === null
      ? this.aulasService.crear(payload)
      : this.aulasService.actualizar(this.editingAulaId, payload);
    request.subscribe({
      next: () => {
        this.saving.set(false);
        this.aulaEditorOpen.set(false);
        this.notify('Aula guardada.', 'success');
        this.loadAulas();
        this.loadOfertas();
      },
      error: (error: HttpErrorResponse) => {
        this.saving.set(false);
        this.dialogError.set(this.errorMessage(error, 'No se pudo guardar el aula.'));
      },
    });
  }

  protected deleteAula(aula: Aula): void {
    this.ask('Eliminar espacio', `¿Eliminar ${aula.nombre}? Esta acción no se puede deshacer.`, () =>
      this.aulasService.eliminar(aula.id).subscribe({
        next: () => { this.notify('Espacio eliminado.', 'success'); this.loadAulas(); this.loadOfertas(); },
        error: (error: HttpErrorResponse) => this.fail(error, 'No se pudo eliminar el aula.'),
      }));
  }

  protected openNewProfesor(): void {
    this.editingProfesorId = null;
    this.profesorDraft = emptyProfesorDraft();
    this.dialogError.set('');
    this.profesorEditorOpen.set(true);
  }

  protected editProfesor(profesor: Profesor): void {
    this.editingProfesorId = profesor.id;
    this.profesorDraft = {
      codigo: profesor.codigo ?? '',
      nombre: profesor.nombre,
      programas: [...profesor.programas],
      materias: [...profesor.materias],
    };
    this.dialogError.set('');
    this.profesorEditorOpen.set(true);
  }

  protected saveProfesor(): void {
    const payload: ProfesorPayload = {
      ...this.profesorDraft,
      codigo: this.profesorDraft.codigo.trim().toUpperCase() || null,
      nombre: this.profesorDraft.nombre.trim(),
      programas: [...this.profesorDraft.programas],
      materias: [...this.profesorDraft.materias],
    };
    if (!payload.nombre) {
      this.dialogError.set('El nombre del profesor es obligatorio.');
      return;
    }

    this.saving.set(true);
    this.dialogError.set('');
    const request = this.editingProfesorId === null
      ? this.profesoresService.crear(payload)
      : this.profesoresService.actualizar(this.editingProfesorId, payload);
    request.subscribe({
      next: () => {
        this.saving.set(false);
        this.profesorEditorOpen.set(false);
        this.notify('Profesor guardado.', 'success');
        this.loadProfesores();
        this.loadOfertas();
      },
      error: (error: HttpErrorResponse) => {
        this.saving.set(false);
        this.dialogError.set(this.errorMessage(error, 'No se pudo guardar el profesor.'));
      },
    });
  }

  protected deleteProfesor(profesor: Profesor): void {
    this.ask('Eliminar profesor', `¿Eliminar al profesor ${profesor.nombre}?`, () =>
      this.profesoresService.eliminar(profesor.id).subscribe({
        next: () => { this.notify('Profesor eliminado.', 'success'); this.loadProfesores(); this.loadOfertas(); },
        error: (error: HttpErrorResponse) => this.fail(error, 'No se pudo eliminar el profesor.'),
      }));
  }

  protected onPeopleSearch(event: Event): void {
    this.peopleSearch.set((event.target as HTMLInputElement).value);
  }

  protected toggleProfesorPrograma(programaId: number, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const selected = new Set(this.profesorDraft.programas);
    if (checked) selected.add(programaId);
    else selected.delete(programaId);
    this.profesorDraft = { ...this.profesorDraft, programas: [...selected] };
  }

  protected toggleProfesorMateria(materiaId: number, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const selected = new Set(this.profesorDraft.materias);
    if (checked) selected.add(materiaId);
    else selected.delete(materiaId);
    this.profesorDraft = { ...this.profesorDraft, materias: [...selected] };
  }

  /** Para el formulario de grupo: primero los profesores que dictan la materia elegida. */
  protected profesoresParaMateria(materiaId: number | null): { preferidos: Profesor[]; otros: Profesor[] } {
    const todos = this.profesores();
    if (materiaId === null) return { preferidos: [], otros: todos };
    return {
      preferidos: todos.filter((profesor) => profesor.materias.includes(materiaId)),
      otros: todos.filter((profesor) => !profesor.materias.includes(materiaId)),
    };
  }

  protected onTablesApplicability(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.aulaDraft.mesas_aplicables = value === '' ? null : value === 'si';
  }

  protected trackProfesor(_index: number, profesor: Profesor): number {
    return profesor.id;
  }

  protected openNewGrupo(): void {
    this.editingGrupoId = null;
    this.grupoDraft = {
      ...emptyGrupoDraft(),
      materia: this.materias()[0]?.id ?? null,
      periodo: this.periodos()[0]?.id ?? null,
    };
    this.dialogError.set('');
    this.grupoEditorOpen.set(true);
  }

  protected editGrupo(grupo: GrupoOferta): void {
    this.editingGrupoId = grupo.id;
    this.grupoDraft = {
      codigo: grupo.codigo,
      materia: grupo.materia,
      periodo: grupo.periodo,
      modalidad: grupo.modalidad,
      profesor: grupo.profesor,
      estudiantes_matriculados: grupo.estudiantes_matriculados,
      horarios: grupo.horarios.map((h) => ({
        id: h.id, dia: h.dia, hora_inicio: h.hora_inicio.slice(0, 5), hora_fin: h.hora_fin.slice(0, 5), aula: h.aula ?? null,
      })),
    };
    this.dialogError.set('');
    this.grupoEditorOpen.set(true);
  }

  protected saveGrupo(): void {
    if (!this.grupoDraft.codigo.trim() || this.grupoDraft.materia === null || this.grupoDraft.periodo === null || this.grupoDraft.profesor === null) {
      this.dialogError.set('Completa el código, la materia, el período y el profesor del grupo.');
      return;
    }
    const problem = this.horarioProblem();
    if (problem) {
      this.dialogError.set(problem);
      return;
    }
    const materiaId = this.grupoDraft.materia;
    const periodoId = this.grupoDraft.periodo;
    const profesorId = this.grupoDraft.profesor;
    if (materiaId === null || periodoId === null || profesorId === null) return;
    const payload: GrupoPayload = {
      ...this.grupoDraft,
      codigo: this.grupoDraft.codigo.trim(),
      materia: materiaId,
      periodo: periodoId,
      profesor: profesorId,
      estudiantes_matriculados: Math.max(0, Math.floor(this.grupoDraft.estudiantes_matriculados || 0)),
      horarios: this.grupoDraft.horarios.map((h) => ({ dia: h.dia, hora_inicio: h.hora_inicio, hora_fin: h.hora_fin })),
    };
    this.submitGrupo(payload);
  }

  private submitGrupo(payload: GrupoPayload): void {
    this.saving.set(true);
    this.dialogError.set('');
    const request = this.editingGrupoId === null
      ? this.ofertasService.crearGrupo(payload)
      : this.ofertasService.actualizarGrupo(this.editingGrupoId, payload);
    request.subscribe({
      next: () => {
        this.saving.set(false);
        this.grupoEditorOpen.set(false);
        this.notify(payload.redistribuir ? 'Grupo guardado y estudiantes sobrantes trasladados.' : 'Grupo guardado.', 'success');
        this.loadOfertas();
      },
      error: (error: HttpErrorResponse) => {
        this.saving.set(false);
        if (this.askRedistribute(error, () => this.submitGrupo({ ...payload, redistribuir: true }))) return;
        this.dialogError.set(this.errorMessage(error, 'No se pudo guardar el grupo.'));
      },
    });
  }

  protected readonly dias = [
    { value: 'LUNES', label: 'Lunes' }, { value: 'MARTES', label: 'Martes' }, { value: 'MIERCOLES', label: 'Miércoles' },
    { value: 'JUEVES', label: 'Jueves' }, { value: 'VIERNES', label: 'Viernes' }, { value: 'SABADO', label: 'Sábado' },
    { value: 'DOMINGO', label: 'Domingo' },
  ];

  /** Reglas obvias de un grupo; el servidor las vuelve a validar. */
  private horarioProblem(): string | null {
    const draft = this.grupoDraft;
    const toMin = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5));
    const label = (dia: string) => this.dias.find((d) => d.value === dia)?.label ?? dia;
    for (const h of draft.horarios) {
      if (!h.hora_inicio || !h.hora_fin) return 'Cada horario necesita hora de inicio y de fin.';
      const start = toMin(h.hora_inicio);
      const end = toMin(h.hora_fin);
      if (end <= start) return `${label(h.dia)}: la hora de fin debe ser posterior a la de inicio.`;
      if (start < 6 * 60 || end > 22 * 60) return `${label(h.dia)}: las clases solo pueden programarse entre las 06:00 y las 22:00.`;
      if (end - start < 30) return `${label(h.dia)}: cada bloque debe durar al menos 30 minutos.`;
      if (end - start > 360) return `${label(h.dia)}: un bloque no puede durar más de 6 horas.`;
    }
    const overlaps = (a: HorarioGrupo, b: HorarioGrupo) =>
      a.dia === b.dia && toMin(a.hora_inicio) < toMin(b.hora_fin) && toMin(b.hora_inicio) < toMin(a.hora_fin);
    for (let i = 0; i < draft.horarios.length; i++) {
      for (let j = i + 1; j < draft.horarios.length; j++) {
        if (overlaps(draft.horarios[i], draft.horarios[j])) return `El grupo tiene dos horarios que se solapan el ${label(draft.horarios[i].dia).toLowerCase()}.`;
      }
    }
    if (draft.profesor !== null && draft.periodo !== null) {
      for (const other of this.grupos()) {
        if (other.id === this.editingGrupoId || other.profesor !== draft.profesor || other.periodo !== draft.periodo) continue;
        for (const h of draft.horarios) {
          const clash = other.horarios.find((o) => overlaps(h, o));
          if (clash) {
            return `El profesor ya dicta ${other.materia_nombre} (grupo ${other.codigo}) el ${label(h.dia).toLowerCase()} de ${this.hora(clash.hora_inicio)} a ${this.hora(clash.hora_fin)}.`;
          }
        }
      }
    }
    return null;
  }

  protected addHorario(): void {
    this.grupoDraft = { ...this.grupoDraft, horarios: [...this.grupoDraft.horarios, { dia: 'LUNES', hora_inicio: '08:00', hora_fin: '10:00', aula: null }] };
  }

  protected removeHorario(index: number): void {
    this.grupoDraft = { ...this.grupoDraft, horarios: this.grupoDraft.horarios.filter((_, i) => i !== index) };
  }

  protected diaCorto(dia: string): string {
    return this.dias.find((d) => d.value === dia)?.label.slice(0, 3) ?? dia;
  }

  protected hora(value: string): string {
    return value.slice(0, 5);
  }

  protected adjustEnrollment(grupo: GrupoOferta, delta: number, redistribuir = false): void {
    const nextCount = grupo.estudiantes_matriculados + delta;
    if (nextCount < 0 || this.ajustando().has(grupo.id)) return;
    this.marcarAjuste(grupo.id, true);
    this.ofertasService.actualizarGrupo(grupo.id, { estudiantes_matriculados: nextCount, ...(redistribuir ? { redistribuir: true } : {}) }).subscribe({
      next: () => {
        this.marcarAjuste(grupo.id, false);
        if (redistribuir) this.notify('Estudiantes sobrantes trasladados al otro grupo.', 'success');
        this.loadOfertas();
      },
      error: (error: HttpErrorResponse) => {
        this.marcarAjuste(grupo.id, false);
        if (this.askRedistribute(error, () => this.adjustEnrollment(grupo, delta, true))) return;
        this.fail(error, 'No se pudo cambiar la matrícula.');
      },
    });
  }

  private marcarAjuste(id: number, activo: boolean): void {
    this.ajustando.update((actual) => {
      const siguiente = new Set(actual);
      if (activo) siguiente.add(id); else siguiente.delete(id);
      return siguiente;
    });
  }

  protected deleteGrupo(grupo: GrupoOferta): void {
    this.ask('Eliminar grupo', `¿Eliminar la oferta ${grupo.materia_nombre} · ${grupo.codigo}?`, () =>
      this.ofertasService.eliminarGrupo(grupo.id).subscribe({
        next: () => { this.notify('Grupo eliminado.', 'success'); this.loadOfertas(); },
        error: (error: HttpErrorResponse) => this.fail(error, 'No se pudo eliminar el grupo.'),
      }));
  }

  protected grupoCapacityStatus(grupo: GrupoOferta): string {
    if (grupo.modalidad === 'VIRTUAL') return 'Virtual · sin salón';
    if (grupo.capacidad_aula_asignada === null) return 'Aún sin salón';
    return grupo.estudiantes_matriculados > grupo.capacidad_aula_asignada
      ? 'Supera capacidad'
      : 'Capacidad suficiente';
  }

  protected openNewMateria(): void {
    this.editingMateriaId = null;
    this.materiaDraft = emptyMateriaDraft();
    this.dialogError.set('');
    this.materiaEditorOpen.set(true);
  }

  protected editMateria(materia: Materia): void {
    this.editingMateriaId = materia.id;
    this.materiaDraft = { codigo: materia.codigo, nombre: materia.nombre };
    this.dialogError.set('');
    this.materiaEditorOpen.set(true);
  }

  protected saveMateria(): void {
    const payload: MateriaPayload = {
      codigo: this.materiaDraft.codigo.trim().toUpperCase(),
      nombre: this.materiaDraft.nombre.trim(),
    };
    if (!payload.codigo || !payload.nombre) {
      this.dialogError.set('El código y el nombre de la materia son obligatorios.');
      return;
    }
    this.saving.set(true);
    this.dialogError.set('');
    const request = this.editingMateriaId === null
      ? this.ofertasService.crearMateria(payload)
      : this.ofertasService.actualizarMateria(this.editingMateriaId, payload);
    request.subscribe({
      next: () => {
        this.saving.set(false);
        this.materiaEditorOpen.set(false);
        this.notify('Materia guardada.', 'success');
        this.loadOfertas();
      },
      error: (error: HttpErrorResponse) => {
        this.saving.set(false);
        this.dialogError.set(this.errorMessage(error, 'No se pudo guardar la materia.'));
      },
    });
  }

  protected deleteMateria(materia: Materia): void {
    this.ask('Eliminar materia', `¿Eliminar la materia ${materia.nombre}? Solo es posible si no tiene grupos.`, () =>
      this.ofertasService.eliminarMateria(materia.id).subscribe({
        next: () => { this.notify('Materia eliminada.', 'success'); this.loadOfertas(); },
        error: (error: HttpErrorResponse) => this.fail(error, 'No se pudo eliminar la materia.'),
      }));
  }

  protected trackGrupo(_index: number, grupo: GrupoOferta): number {
    return grupo.id;
  }

  protected trackMateria(_index: number, materia: Materia): number {
    return materia.id;
  }

  protected clearAulaFilters(): void {
    this.search.set('');
    this.statusFilter.set('todas');
    this.blockFilter.set('todos');
  }

  protected sortAulas(key: string): void {
    const current = this.aulaSort();
    this.aulaSort.set({ key, dir: current.key === key && current.dir === 1 ? -1 : 1 });
  }

  protected sortProfesores(key: string): void {
    const current = this.profesorSort();
    this.profesorSort.set({ key, dir: current.key === key && current.dir === 1 ? -1 : 1 });
  }

  protected sortMark(sort: { key: string; dir: 1 | -1 }, key: string): string {
    return sort.key === key ? (sort.dir === 1 ? '▲' : '▼') : '';
  }

  protected sortAria(sort: { key: string; dir: 1 | -1 }, key: string): 'ascending' | 'descending' | 'none' {
    return sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none';
  }

  protected notify(message: string, kind: 'error' | 'success' = 'error'): void {
    const id = ++this.toastSeq;
    this.toasts.update((list) => [...list, { id, message, kind }]);
    setTimeout(() => this.dismissToast(id), kind === 'error' ? 7000 : 3500);
  }

  protected dismissToast(id: number): void {
    this.toasts.update((list) => list.filter((toast) => toast.id !== id));
  }

  protected ask(title: string, message: string, action: () => void, label = 'Eliminar', danger = true): void {
    this.confirmState.set({ title, message, action, label, danger });
  }

  /** Si el servidor avisa que el grupo supera el aula más grande, pregunta y reintenta con redistribuir=true. */
  private askRedistribute(error: HttpErrorResponse, retry: () => void, onDecline?: () => void): boolean {
    const body = error.error as ExcedeCapacidad | undefined;
    if (error.status !== 409 || body?.codigo !== 'excede_aula_maxima') return false;
    const destinos = body.destinos
      .map((d) => `• ${d.materia_nombre}, grupo ${d.codigo}: tiene ${d.matricula}, recibiría ${d.recibe}`)
      .join('\n');
    const plural = body.sobrantes === 1 ? 'estudiante sobrante' : 'estudiantes sobrantes';
    this.confirmState.set({
      title: 'El grupo supera el aula más grande',
      message: `El salón más grande disponible admite ${body.maximo} estudiantes y sobran ${body.sobrantes}. `
        + `¿Quieres pasar ${body.sobrantes} ${plural} a otro grupo de la misma materia?\n\n${destinos}`,
      action: retry,
      label: 'Sí, pasarlos',
      danger: false,
    });
    this.declineAction = onDecline ?? null;
    return true;
  }

  private declineAction: (() => void) | null = null;

  protected confirmAccept(): void {
    const state = this.confirmState();
    this.confirmState.set(null);
    this.declineAction = null;
    state?.action();
  }

  protected confirmCancel(): void {
    this.confirmState.set(null);
    this.declineAction?.();
    this.declineAction = null;
  }

  protected closeDialogs(): void {
    if (this.confirmState()) { this.confirmCancel(); return; }
    this.selector.set(null);
    this.aulaEditorOpen.set(false);
    this.profesorEditorOpen.set(false);
    this.grupoEditorOpen.set(false);
    this.materiaEditorOpen.set(false);
  }

  protected onSearch(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }

  protected onStatusChange(event: Event): void {
    this.statusFilter.set((event.target as HTMLSelectElement).value);
  }

  protected onBlockChange(event: Event): void {
    this.blockFilter.set((event.target as HTMLSelectElement).value);
  }

  protected trackAula(_index: number, aula: Aula): number {
    return aula.id;
  }

  protected colorDePrograma(programaId: number | null): string {
    if (programaId === null) return '#6b7a74';
    const index = this.programas().findIndex((programa) => programa.id === programaId);
    return PROGRAM_COLORS[(index < 0 ? 0 : index) % PROGRAM_COLORS.length];
  }

  protected onProgramaFiltro(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.programaFiltro.set(value === '' ? null : Number(value));
  }

  protected resetLayout(): void {
    this.blockPos.set({});
    this.pan.set({ x: 0, y: 0 });
  }

  protected startDrag(event: PointerEvent, key?: string): void {
    if (event.button !== 0) return;
    event.stopPropagation();
    if (key === undefined) {
      this.drag = { kind: 'pan', key: '', sx: event.clientX, sy: event.clientY, ox: this.pan().x, oy: this.pan().y, moved: false };
    } else {
      const { grupos, salones } = this.espacio();
      const bloque = grupos.find((item) => item.key === key) ?? salones.find((item) => item.key === key);
      if (!bloque) return;
      this.drag = { kind: 'block', key, sx: event.clientX, sy: event.clientY, ox: bloque.x, oy: bloque.y, moved: false };
    }
    this.dragging.set(true);
    event.preventDefault();
  }

  protected onPointerMove(event: PointerEvent): void {
    const drag = this.drag;
    if (!drag) return;
    const x = drag.ox + event.clientX - drag.sx;
    const y = drag.oy + event.clientY - drag.sy;
    if (Math.abs(event.clientX - drag.sx) + Math.abs(event.clientY - drag.sy) > 4) drag.moved = true;
    if (drag.kind === 'pan') this.pan.set({ x, y });
    else this.blockPos.update((posiciones) => ({ ...posiciones, [drag.key]: { x, y } }));
  }

  protected onPointerUp(): void {
    const drag = this.drag;
    this.drag = null;
    this.dragging.set(false);
    // un clic (sin arrastrar) sobre un bloque de salón abre el selector
    if (drag?.kind === 'block' && !drag.moved && drag.key.startsWith('r') && this.canManage()) {
      const salon = this.espacio().salones.find((item) => item.key === drag.key);
      if (salon) this.openSelector(salon.grupo, salon.horario);
    }
  }

  protected readonly selector = signal<{ grupo: GrupoOferta; horario: HorarioGrupo; opciones: AulaOpcion[] | null } | null>(null);

  protected openSelector(grupo: GrupoOferta, horario: HorarioGrupo): void {
    if (horario.id === undefined) return;
    this.selector.set({ grupo, horario, opciones: null });
    this.ofertasService.aulasDisponibles(horario.id).subscribe({
      next: (opciones) => this.selector.update((actual) => actual && { ...actual, opciones }),
      error: (error: HttpErrorResponse) => {
        this.selector.set(null);
        this.fail(error, 'No se pudieron consultar los salones disponibles.');
      },
    });
  }

  protected chooseAula(opcion: AulaOpcion | null): void {
    const actual = this.selector();
    if (!actual || actual.horario.id === undefined || (opcion && !opcion.disponible)) return;
    this.ofertasService.asignarAula(actual.horario.id, opcion?.id ?? null).subscribe({
      next: () => {
        this.selector.set(null);
        this.notify(opcion ? `Salón ${opcion.nombre} fijado.` : 'El bloque volvió a la asignación automática.', 'success');
        this.loadOfertas();
      },
      error: (error: HttpErrorResponse) => this.fail(error, 'No se pudo cambiar el salón.'),
    });
  }

  private loadAulas(): void {
    this.loading.set(true);
    this.error.set('');
    this.aulasService.listar().subscribe({
      next: (aulas) => {
        this.aulas.set(aulas);
        this.apiConnected.set(true);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.apiConnected.set(false);
        this.fail(error, 'No se pudieron cargar las aulas.');
        this.loading.set(false);
      },
    });
  }

  private loadProfesores(): void {
    this.profesoresService.listar().subscribe({
      next: (profesores) => this.profesores.set(profesores),
      error: (error: HttpErrorResponse) => this.fail(error, 'No se pudieron cargar los profesores.'),
    });
    this.profesoresService.listarProgramas().subscribe({
      next: (programas) => this.programas.set(programas),
      error: (error: HttpErrorResponse) => this.fail(error, 'No se pudieron cargar los programas.'),
    });
  }

  private loadOfertas(): void {
    this.ofertasService.listarMaterias().subscribe({
      next: (materias) => this.materias.set(materias),
      error: (error: HttpErrorResponse) => this.fail(error, 'No se pudieron cargar las materias.'),
    });
    this.ofertasService.listarGrupos().subscribe({
      next: (grupos) => this.grupos.set(grupos),
      error: (error: HttpErrorResponse) => this.fail(error, 'No se pudieron cargar las ofertas.'),
    });
    this.ofertasService.listarPeriodos().subscribe({
      next: (periodos) => this.periodos.set(periodos),
      error: (error: HttpErrorResponse) => this.fail(error, 'No se pudieron cargar los períodos.'),
    });
  }

  private numberOrNull(value: number | string | null): number | null {
    if (value === null || value === '') return null;
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }

  private fail(error: HttpErrorResponse, fallback: string): void {
    this.notify(this.errorMessage(error, fallback));
  }

  private compareValues(first: string | number, second: string | number): number {
    if (typeof first === 'number' && typeof second === 'number') return first - second;
    return String(first).localeCompare(String(second), 'es', { numeric: true });
  }

  private aulaSortValue(aula: Aula, key: string): string | number {
    switch (key) {
      case 'tipo': return aula.tipo;
      case 'bloque': return aula.bloque;
      case 'sillas': return aula.sillas ?? -1;
      case 'mesas': return aula.mesas ?? -1;
      case 'capacidad': return aula.capacidad ?? -1;
      case 'area': return this.numberOrNull(aula.area_m2) ?? -1;
      case 'existe': return aula.existe ? 1 : 0;
      default: return aula.nombre;
    }
  }

  private profesorSortValue(profesor: Profesor, key: string): string {
    switch (key) {
      case 'codigo': return profesor.codigo ?? '';
      case 'programas': return profesor.programas_nombres.join(' ');
      case 'materia': return profesor.materias_nombres.join(' ');
      default: return profesor.nombre;
    }
  }

  private errorMessage(error: HttpErrorResponse, fallback: string): string {
    if (error.status === 0) return 'No hay conexión con el servidor. Revisa que el backend esté en marcha.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    const body = error.error;
    if (typeof body?.detail === 'string') return body.detail;
    if (body && typeof body === 'object') {
      const labels: Record<string, string> = {
        nombre: 'Nombre', codigo: 'Código', materia: 'Materia', periodo: 'Período', profesor: 'Profesor',
        estudiantes_matriculados: 'Estudiantes', secciones: 'Secciones', capacidad_manual: 'Capacidad manual',
      };
      const parts: string[] = [];
      for (const [field, value] of Object.entries(body)) {
        const messages = Array.isArray(value) ? value.filter((item) => typeof item === 'string') : typeof value === 'string' ? [value] : [];
        if (!messages.length) continue;
        parts.push(field === 'non_field_errors' ? messages.join(' ') : `${labels[field] ?? field}: ${messages.join(' ')}`);
      }
      if (parts.length) return parts.join('\n');
    }
    return fallback;
  }
}
