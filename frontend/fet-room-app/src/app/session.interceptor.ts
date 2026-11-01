import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { AuthService } from './auth.service';

/** Si el servidor responde 401 a una llamada de datos, la sesión venció: vuelve al inicio de sesión. */
export const sessionInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  return next(request).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401 && !request.url.includes('/api/auth/') && auth.session()) {
        auth.expired.set(true);
        auth.session.set(null);
      }
      return throwError(() => error);
    }),
  );
};
