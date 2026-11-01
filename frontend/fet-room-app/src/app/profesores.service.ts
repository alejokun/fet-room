import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface Profesor {
  id: number;
  codigo: string | null;
  nombre: string;
  programas: number[];
  programas_nombres: string[];
  materias: number[];
  materias_nombres: string[];
}

export interface Programa {
  id: number;
  codigo: string;
  nombre: string;
}

export type ProfesorPayload = Omit<Profesor, 'id' | 'programas_nombres' | 'materias_nombres'>;
export type ProgramaPayload = Omit<Programa, 'id'>;

@Injectable({ providedIn: 'root' })
export class ProfesoresService {
  private readonly http = inject(HttpClient);

  listarProgramas(): Observable<Programa[]> {
    return this.http.get<Programa[]>('/api/programas/', { withCredentials: true });
  }

  crearPrograma(data: ProgramaPayload): Observable<Programa> {
    return this.http.post<Programa>('/api/programas/', data, { withCredentials: true });
  }

  actualizarPrograma(id: number, data: Partial<ProgramaPayload>): Observable<Programa> {
    return this.http.patch<Programa>(`/api/programas/${id}/`, data, { withCredentials: true });
  }

  eliminarPrograma(id: number): Observable<void> {
    return this.http.delete<void>(`/api/programas/${id}/`, { withCredentials: true });
  }

  listar(): Observable<Profesor[]> {
    return this.http.get<Profesor[]>('/api/profesores/', { withCredentials: true });
  }

  crear(data: ProfesorPayload): Observable<Profesor> {
    return this.http.post<Profesor>('/api/profesores/', data, { withCredentials: true });
  }

  actualizar(id: number, data: Partial<ProfesorPayload>): Observable<Profesor> {
    return this.http.patch<Profesor>(`/api/profesores/${id}/`, data, { withCredentials: true });
  }

  eliminar(id: number): Observable<void> {
    return this.http.delete<void>(`/api/profesores/${id}/`, { withCredentials: true });
  }
}