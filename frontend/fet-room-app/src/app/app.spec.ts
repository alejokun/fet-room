import { TestBed } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { of } from 'rxjs';

import { Aula, AulasService } from './aulas.service';
import { App } from './app';
import { AuthService, AuthSession } from './auth.service';
import { OfertasService } from './ofertas.service';
import { ProfesoresService } from './profesores.service';

describe('App', () => {
  const rooms: Aula[] = [
    {
      id: 1,
      nombre: 'B1-101',
      bloque: 'Bloque 1',
      tipo: 'AULA',
      espacio_por_silla: 1.5,
      area_m2: 42.45,
      secciones: [],
      sillas: 28,
      mesas: 14,
      mesas_aplicables: true,
      capacidad: 28,
      capacidad_manual: null,
      observacion: 'MESAS BLANCAS',
      existe: true,
    },
    {
      id: 2,
      nombre: 'B1-102',
      bloque: 'Bloque 1',
      tipo: 'AULA',
      espacio_por_silla: 1.5,
      area_m2: null,
      secciones: [],
      sillas: null,
      mesas: null,
      mesas_aplicables: null,
      capacidad: null,
      capacidad_manual: null,
      observacion: '',
      existe: false,
    },
    {
      id: 3,
      nombre: 'B2-201',
      bloque: 'Bloque 2',
      tipo: 'AULA',
      espacio_por_silla: 1.5,
      area_m2: 36.25,
      secciones: [],
      sillas: 24,
      mesas: null,
      mesas_aplicables: false,
      capacidad: 24,
      capacidad_manual: null,
      observacion: 'PUPITRES MADERA',
      existe: true,
    },
  ];

  let fixture: ReturnType<typeof TestBed.createComponent<App>>;
  let sessionSignal: WritableSignal<AuthSession | null>;
  let restoringSignal: WritableSignal<boolean>;

  beforeEach(async () => {
    history.replaceState(null, '', window.location.pathname); // la vista activa vive en el #hash
    const session: AuthSession = { username: 'coordinador', groups: ['Coordinador'], can_manage: false };
    sessionSignal = signal<AuthSession | null>(session);
    restoringSignal = signal(false);
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        { provide: AulasService, useValue: { listar: () => of(rooms) } },
        { provide: ProfesoresService, useValue: { listar: () => of([]), listarProgramas: () => of([]) } },
        {
          provide: OfertasService,
          useValue: {
            listarMaterias: () => of([]),
            listarGrupos: () => of([]),
            listarPeriodos: () => of([]),
          },
        },
        {
          provide: AuthService,
          useValue: {
            session: sessionSignal,
            restoring: restoringSignal,
            expired: signal(false),
            restoreSession: () => undefined,
            logout: () => of({ detail: 'Sesión cerrada.' }),
            login: () => of(session),
          },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('keeps the Aulas navigation in the current page', () => {
    const navButton = fixture.nativeElement.querySelector('button.nav-item') as HTMLButtonElement;

    expect(navButton.textContent).toContain('Aulas');
    expect(navButton.closest('a')).toBeNull();
  });

  it('opens the professor directory without granting coordinator edit controls', () => {
    const professorNav = [...fixture.nativeElement.querySelectorAll('button.nav-item')]
      .find((button) => button.textContent.includes('Profesores')) as HTMLButtonElement;
    professorNav.click();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('#profesores-title')?.textContent).toContain('Directorio de profesores');
    expect(fixture.nativeElement.querySelector('button.create-button')).toBeNull();
  });

  it('opens the subjects and groups section without exposing coordinator write controls', () => {
    const offersNav = [...fixture.nativeElement.querySelectorAll('button.nav-item')]
      .find((button) => button.textContent.includes('Materias y grupos')) as HTMLButtonElement;
    offersNav.click();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('#groups-title')?.textContent).toContain('Ofertas por período');
    expect(fixture.nativeElement.querySelector('button.create-button')).toBeNull();
    expect(fixture.nativeElement.querySelector('.enrollment-control')).toBeNull();
  });

  it('does not show login before the saved session has been checked', () => {
    sessionSignal.set(null);
    restoringSignal.set(true);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.session-check')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.login-form')).toBeNull();

    restoringSignal.set(false);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.session-check')).toBeNull();
    expect(fixture.nativeElement.querySelector('.login-form')).not.toBeNull();
  });

  it('filters rooms by block and combines the block filter with status', () => {
    const blockFilter = fixture.nativeElement.querySelector(
      'select[aria-label="Filtrar por bloque"]',
    ) as HTMLSelectElement;
    blockFilter.value = 'Bloque 1';
    blockFilter.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    let rows = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('B1-101');
    expect(rows[1].textContent).toContain('B1-102');

    const statusFilter = fixture.nativeElement.querySelector(
      'select[aria-label="Filtrar por existencia"]',
    ) as HTMLSelectElement;
    statusFilter.value = 'existentes';
    statusFilter.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    rows = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain('B1-101');
  });

  it('keeps the current view after a page reload', () => {
    history.replaceState(null, '', `${window.location.pathname}#profesores`);
    const reloaded = TestBed.createComponent(App);
    reloaded.detectChanges();
    expect(reloaded.nativeElement.querySelector('h1')?.textContent).toContain('Profesores');
    expect(reloaded.nativeElement.querySelector('.nav-item.active')?.textContent).toContain('Profesores');
  });

  it('writes the selected view to the URL and ignores unknown values', () => {
    const asignacion = Array.from(fixture.nativeElement.querySelectorAll('.nav-item') as NodeListOf<HTMLButtonElement>)
      .find((button) => button.textContent?.includes('Asignación'));
    asignacion?.click();
    expect(window.location.hash).toBe('#asignacion');

    history.replaceState(null, '', `${window.location.pathname}#no-existe`);
    const reloaded = TestBed.createComponent(App);
    reloaded.detectChanges();
    expect(reloaded.nativeElement.querySelector('.nav-item.active')?.textContent).toContain('Aulas');
  });
});
