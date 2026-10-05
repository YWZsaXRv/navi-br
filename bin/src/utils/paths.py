import sys
from pathlib import Path


class Paths:
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)).resolve()
    RES = BASE_DIR / "res"
    DEPS = BASE_DIR / "deps"

    @classmethod
    def deps(cls, relative_path=None) -> Path:
        """Grabs from the dependencies folder by relative name.

        If no relative path is specified, it returns the /deps/ folder.
        """
        if relative_path is not None:
            return cls.DEPS / relative_path
        return cls.DEPS

    @classmethod
    def resource(cls, relative_path=None) -> Path:
        """Grabs a resource by relative name.

        If no relative path is specified, it returns the /res/ folder.
        """
        if relative_path is not None:
            return cls.RES / relative_path
        return cls.RES

    @classmethod
    def base(cls, relative_path=None) -> Path:
        """Grabs a resource from the base path.

        If no relative path is specified, it returns the base path.
        """
        if relative_path is not None:
            return cls.BASE_DIR / relative_path
        return cls.BASE_DIR

