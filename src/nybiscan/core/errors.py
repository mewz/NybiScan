"""Typed errors for the NybiScan core. Standalone (no intra-core imports)."""


class NybiScanError(Exception):
    """Base class for all NybiScan core errors."""


class ProjectExistsError(NybiScanError):
    """Attempted to create a project where a bundle already exists."""


class ProjectNotFoundError(NybiScanError):
    """Attempted to open a project bundle that does not exist or is malformed."""


class PassphraseRequiredError(NybiScanError):
    """The project is encrypted but no passphrase was provided."""


class WrongPassphraseError(NybiScanError):
    """The provided passphrase failed to decrypt the project database."""


class CaExistsError(NybiScanError):
    """A CA already exists at the target location and force was not set."""


class CaNotFoundError(NybiScanError):
    """No CA exists at the requested location."""
