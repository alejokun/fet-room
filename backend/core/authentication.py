from rest_framework.authentication import SessionAuthentication


class SessionAuthentication401(SessionAuthentication):
    """Igual que SessionAuthentication, pero una sesión ausente o vencida responde 401 (no 403).

    Así el frontend distingue "sesión expirada" de "sin permiso".
    """

    def authenticate_header(self, request):
        return "Session"
