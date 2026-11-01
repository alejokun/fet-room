import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface Materia {
  id: number;
  codigo: string;
  nombre: string;
}

export interface PeriodoAcademico {
  id: number;
  codigo: string;
}

export interface HorarioGrupo {
  id?: number;
  dia: string;
  hora_inicio: string;
  hora_fin: string;
  aula?: number | null;
  aula_nombre?: string | null;
  aula_fijada?: boolean;
  aula_problema?: string | null;
}

export interface AulaOpcion {
  id: number;
  nombre: string;
  bloque: string;
  tipo: string;
  capacidad: number | null;
  disponible: boolean;
  motivo: string;
  aviso: string;
  actual: boolean;
}

export interface GrupoOferta {
  id: number;
  codigo: string;
  materia: number;
  materia_nombre: string;
  materia_codigo: string;
  periodo: number;
  periodo_codigo: string;
  modalidad: 'PRESENCIAL' | 'VIRTUAL';
  profesor: number | null;
  profesor_nombre: string | null;
  profesor_codigo: string | null;
  estudiantes_matriculados: number;
  capacidad_aula_asignada: number | null;
  horarios: HorarioGrupo[];
}

export interface MateriaPayload {
  codigo: string;
  nombre: string;
}

export interface GrupoPayload {
  codigo: string;
  materia: number;
  periodo: number;
  modalidad: 'PRESENCIAL' | 'VIRTUAL';
  profesor: number;
  estudiantes_matriculados: number;
  horarios: HorarioGrupo[];
  redistribuir?: boolean;
}

export interface ExcedeCapacidad {
  codigo: 'excede_aula_maxima';
  maximo: number;
  sobrantes: number;
  detail: string;
  destinos: Array<{ id: number; codigo: string; materia_nombre: string; matricula: number; libres: number; recibe: number }>;
}

@Injectable({ providedIn: 'root' })
export class OfertasService {
  private readonly http = inject(HttpClient);

  listarMaterias(): Observable<Materia[]> {
    return this.http.get<Materia[]>('/api/materias/', { withCredentials: true });
  }

  crearMateria(payload: MateriaPayload): Observable<Materia> {
    return this.http.post<Materia>('/api/materias/', payload, { withCredentials: true });
  }

  actualizarMateria(id: number, payload: Partial<MateriaPayload>): Observable<Materia> {
    return this.http.patch<Materia>(`/api/materias/${id}/`, payload, { withCredentials: true });
  }

  eliminarMateria(id: number): Observable<void> {
    return this.http.delete<void>(`/api/materias/${id}/`, { withCredentials: true });
  }

  listarGrupos(): Observable<GrupoOferta[]> {
    return this.http.get<GrupoOferta[]>('/api/grupos/', { withCredentials: true });
  }

  crearGrupo(payload: GrupoPayload): Observable<GrupoOferta> {
    return this.http.post<GrupoOferta>('/api/grupos/', payload, { withCredentials: true });
  }

  actualizarGrupo(id: number, payload: Partial<GrupoPayload>): Observable<GrupoOferta> {
    return this.http.patch<GrupoOferta>(`/api/grupos/${id}/`, payload, { withCredentials: true });
  }

  eliminarGrupo(id: number): Observable<void> {
    return this.http.delete<void>(`/api/grupos/${id}/`, { withCredentials: true });
  }

  aulasDisponibles(horarioId: number): Observable<AulaOpcion[]> {
    return this.http.get<AulaOpcion[]>(`/api/horarios/${horarioId}/aulas-disponibles/`, { withCredentials: true });
  }

  asignarAula(horarioId: number, aula: number | null): Observable<{ id: number; aula: number | null; aula_fijada: boolean }> {
    return this.http.post<{ id: number; aula: number | null; aula_fijada: boolean }>(
      `/api/horarios/${horarioId}/asignar-aula/`, { aula }, { withCredentials: true },
    );
  }

  listarPeriodos(): Observable<PeriodoAcademico[]> {
    return this.http.get<PeriodoAcademico[]>('/api/periodos/', { withCredentials: true });
  }
}
