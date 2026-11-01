import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, switchMap } from 'rxjs';

export interface AuthSession {
  username: string;
  groups: string[];
  can_manage?: boolean;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  readonly session = signal<AuthSession | null>(null);
  readonly restoring = signal(true);
  /** true cuando el servidor cerró la sesión por inactividad mientras se usaba la app. */
  readonly expired = signal(false);

  restoreSession(): void {
    this.restoring.set(true);
    this.http.get<AuthSession>('/api/auth/session/', { withCredentials: true }).subscribe({
      next: (session) => {
        this.session.set(session);
        this.restoring.set(false);
      },
      error: () => {
        this.session.set(null);
        this.restoring.set(false);
      },
    });
  }

  login(username: string, password: string): Observable<AuthSession> {
    this.expired.set(false);
    return this.http.get('/api/csrf/', { withCredentials: true }).pipe(
      switchMap(() => this.http.post<AuthSession>(
        '/api/auth/login/',
        { username, password },
        { withCredentials: true },
      )),
    );
  }

  logout(): Observable<{ detail: string }> {
    return this.http.post<{ detail: string }>(
      '/api/auth/logout/',
      {},
      { withCredentials: true },
    );
  }
}