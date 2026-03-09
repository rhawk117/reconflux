


from reconflux.core import ReconfluxError


class RDAPError(ReconfluxError):
    """Base exception for RDAP client failures."""

    error_code = 'rdap_error'


class RDAPAuthoritativeResolutionError(RDAPError):
    """Raised when authoritative RDAP resolution fails."""


class RDAPMalformedResponseError(RDAPError):
    """Raised when an RDAP response is invalid or cannot be normalized."""


class RDAPBootstrapError(RDAPError):
    """Raised when IANA bootstrap data cannot resolve a target."""
