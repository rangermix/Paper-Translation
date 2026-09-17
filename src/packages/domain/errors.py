class DomainError(Exception):
    def __init__(self, code, message='', status=409, details=None, resource_id=None, retryable=False):
        self.code = code
        self.message = message or code.replace('_', ' ').capitalize()
        self.status = status
        self.details = details or {}
        self.resource_id = resource_id
        self.retryable = retryable
        super().__init__(self.message)


def require(condition, code, message='', status=409, **kwargs):
    if not condition:
        raise DomainError(code, message, status, **kwargs)


def match_generation(entity, value):
    require(value is not None, 'PRECONDITION_REQUIRED', status=428)
    require(value == f'"{entity.generation}"', 'PRECONDITION_FAILED', status=412)
