from PyQt6.QtCore import QSettings

from utils.brand import APP_ID, ORG_NAME


def get_settings() -> QSettings:
    """Get the application settings object."""
    return QSettings(ORG_NAME, APP_ID)
