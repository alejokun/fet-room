import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface Aula {
  id: number;
  nombre: string;
  bloque: string;
  tipo: string;
  espacio_por_silla: number | string | null;
  area_m2: number | string | null;
  secciones: Array<{
    numero: number;
    largo_m: number | string | null;
    ancho_m: number | string | null;
    area_m2: number | string | null;
  }>;
  sillas: number | null;
  mesas: number | null;
  mesas_aplicables: boolean | null;
  capacidad: number | null;
  capacidad_manual: number | null;
  observacion: string;
  existe: boolean;
}

@Injectable({ providedIn: 'root' })
export class AulasService {
  private readonly http = inject(HttpClient);

  listar(): Observable<Aula[]> {
    return this.http.get<Aula[]>('/api/aulas/', { withCredentials: true });
  }

  crear(data: AulaPayload): Observable<Aula> {
    return this.http.post<Aula>('/api/aulas/', data, { withCredentials: true });
  }

  actualizar(id: number, data: Partial<AulaPayload>): Observable<Aula> {
    return this.http.patch<Aula>(`/api/aulas/${id}/`, data, { withCredentials: true });
  }

  eliminar(id: number): Observable<void> {
    return this.http.delete<void>(`/api/aulas/${id}/`, { withCredentials: true });
  }
}

export interface AulaPayload {
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
  secciones: Array<{
    numero: number;
    largo_m: number | null;
    ancho_m: number | null;
  }>;
}