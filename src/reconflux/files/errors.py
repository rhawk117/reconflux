from reconflux.core import ReconfluxError


class FileAnalysisError(ReconfluxError):
    default_message = 'Failed to analyze file.'
    error_code = 'file_analysis_error'
