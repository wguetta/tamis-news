"""Pipeline exception types."""


class PipelineError(Exception):
    """Base exception for pipeline failures."""


class S3LoadError(PipelineError):
    """Raised when loading data from S3 fails."""


class S3SaveError(PipelineError):
    """Raised when saving data to S3 fails."""


class EnrichmentError(PipelineError):
    """Raised when a pipeline stage cannot complete."""


class EmbeddingError(PipelineError):
    """Raised when OpenAI embedding generation fails."""
