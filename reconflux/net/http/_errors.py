from reconflux.core import ReconfluxError


class HTTPError(ReconfluxError):
    error_code = 'http_error'
    default_message = 'An HTTP operation failed.'
