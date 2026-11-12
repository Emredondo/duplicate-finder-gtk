# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import logging
import sys
from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Busca duplicados por contenido exacto con GTK 3")
    parser.add_argument("folder", nargs="?", help="Carpeta inicial (sin analizar automáticamente)")
    parser.add_argument("--version", action="version", version=f"Duplicate Finder GTK {__version__}")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        from .ui import Application
        return Application(args.folder).run([sys.argv[0]])
    except ImportError as error:
        print(f"No se pudo cargar GTK/PyGObject: {error}. Instale el paquete DEB mediante APT.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
