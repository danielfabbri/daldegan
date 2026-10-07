class DaldeganError(Exception):
    """Base dos erros de domínio."""


class NotFound(DaldeganError):
    pass


class IllegalTransition(DaldeganError):
    """Operação não permitida no estado atual (HTTP 409)."""


class TooEarly(IllegalTransition):
    """O período de intenção ainda não terminou (HTTP 409)."""


class Blinded(DaldeganError):
    """Dados ainda cegos (HTTP 423)."""


class SealedSessionError(DaldeganError):
    """Tentativa de escrever em arquivo selado/imutável."""


class SourceUnavailable(DaldeganError):
    """Fonte quântica não configurada ou indisponível (HTTP 503)."""
