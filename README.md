# Duplicate Finder GTK 0.1.1

Utilidad nativa para GNU/Linux que encuentra archivos **exactamente iguales por contenido**, aunque cambien sus nombres o extensiones. Python 3, GTK 3, PyGObject y GIO. Licencia **GPL-3.0-or-later**. Sin servicios en la nube, telemetría ni visores propios.

## Instalación en Debian 13 Trixie / XFCE

Descargue `duplicate-finder-gtk_0.1.1_all.deb`, abra una terminal en su carpeta y ejecute:

```sh
sudo apt install ./duplicate-finder-gtk_0.1.1_all.deb
```

APT resuelve las dependencias. No hace falta crear un entorno Python ni ejecutar scripts. Abra **Duplicate Finder GTK** desde el menú de utilidades o ejecute:

```sh
duplicate-finder-gtk
```

Opcionalmente puede indicar la carpeta inicial: `duplicate-finder-gtk /ruta/a/carpeta`. No inicia un análisis sin pulsar **Analizar**.

Desinstalación:

```sh
sudo apt remove duplicate-finder-gtk
```

Las preferencias personales se conservan. Para quitarlas voluntariamente, borre únicamente `~/.config/duplicate-finder-gtk/` (o su equivalente bajo `XDG_CONFIG_HOME`).

## Uso

1. Elija una carpeta. Configure subcarpetas, archivos ocultos y exclusiones (un patrón por línea, por ejemplo `*.tmp`, `cache`, `backup/*`). Los patrones coinciden con el nombre o la ruta relativa; las carpetas excluidas no se recorren.
2. Pulse **Analizar**. Puede cancelar durante el inventario, los hashes o la comparación. La interfaz permanece operativa. Un análisis cancelado descarta los resultados parciales.
3. Alterne entre **Árbol** y **Tabla**. La tabla permite ordenar las columnas. Los resultados aparecen sin marcar. Ambas vistas comparten las mismas marcas.
4. Marque manualmente o pulse **Seleccionar duplicados automáticamente**. Conserve el más antiguo, el más reciente o el más antiguo dentro de una carpeta prioritaria y sus subcarpetas. Si no hay archivos en ella, se conserva el más antiguo del grupo. Los empates se resuelven por ruta, de forma determinista.
5. Revise cantidad y espacio de la selección. La aplicación impide marcar la última copia, también manualmente.
6. Pulse **Enviar selección a la papelera…** y confirme. Se revalidan metadatos y contenido antes de actuar. Un fallo detiene ese grupo y se informa en **Ver incidencias**. Los demás grupos independientes pueden continuar. No existe borrado permanente ni sustitución de la papelera por otro método.

Doble clic para abrir con la aplicación predeterminada. El menú contextual permite abrir con otra aplicación, mostrar en la carpeta, copiar la ruta, consultar propiedades del análisis y modificar la selección.

El espacio indicado es una estimación lógica, no bloques físicos: los archivos permanecen en la papelera hasta vaciarla. Compresión, archivos dispersos, reflinks y deduplicación del sistema de archivos pueden cambiar el espacio real.

## Detección y seguridad

El motor hace inventario, agrupa por tamaño, calcula SHA-256 de tres muestras de hasta 64 KiB, calcula SHA-256 completo de los candidatos restantes y confirma las coincidencias byte a byte. Las lecturas completas utilizan bloques de 1 MiB. No se cargan archivos enteros en memoria. El inventario y los resultados mantienen metadatos en memoria en proporción al número de archivos.

Se omiten enlaces simbólicos, incluso en los componentes de la carpeta principal. Los nombres adicionales que apuntan a un mismo inodo mediante enlaces duros no cuentan como copias independientes. Un inodo con varios enlaces tiene estimación de espacio recuperable de cero. Antes de enviar a la papelera se valida dispositivo, inodo, tamaño, fechas de modificación y cambio, número de enlaces y coincidencia exacta con una copia que se conserva.

Cierre los programas que estén escribiendo en los archivos antes de operar. Las comprobaciones detectan cambios normales; GIO opera por ruta y no ofrece una transacción atómica frente a cambios simultáneos o maliciosos. Véase [Seguridad](docs/SECURITY.md).

## Preferencias

Se guardan automáticamente en `$XDG_CONFIG_HOME/duplicate-finder-gtk/preferences.json`, por defecto `~/.config/duplicate-finder-gtk/preferences.json`: última carpeta, modo de vista, geometría, maximización, anchos, conservación, carpeta prioritaria, exclusiones, ocultos y recursividad. **Aplicación → Restaurar preferencias** vuelve a los valores iniciales. La posición efectiva depende del gestor de ventanas.

## Desarrollo y reconstrucción

```sh
sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-glib-2.0 dpkg-dev make desktop-file-utils
make test check
make gui-test                     # requiere pantalla gráfica
make deb
```

Para probar sin pantalla física: instale `xvfb xauth dbus-x11` y ejecute `xvfb-run -a dbus-run-session -- make gui-test`.

El paquete aparece en `dist/duplicate-finder-gtk_0.1.1_all.deb`. No se descargan dependencias durante la construcción. `SOURCE_DATE_EPOCH` permite fijar el tiempo de los archivos; el valor predeterminado es reproducible. Más instrucciones en [Instalación y empaquetado](docs/INSTALL.md).

## Estructura

- `duplicate_finder/ui.py`: interfaz, vistas, preferencias y comunicación con un único trabajador.
- `engine.py`: inventario y etapas de búsqueda.
- `hashing.py`: aperturas sin seguir enlaces, hashes y comparación exacta.
- `model.py`: resultados, selección y cálculos de espacio.
- `operations.py`: verificación y papelera GIO.
- `config.py`: preferencias XDG validadas y escritura atómica.
- `tests/`: pruebas automatizadas del motor, selección, seguridad, preferencias y GTK/GIO.
- `tools/`: construcción y verificación aislada del DEB.
- `data/`: integración de escritorio, icono SVG propio y manual.

## Alcance y publicación

La interfaz de esta versión está en español. Su propósito es detectar igualdad exacta; no incluye similitud perceptual de fotos, videos o audio, sincronización ni indexación persistente. Debian 13 es el destino inicial; Ubuntu y otras distribuciones no se han certificado.

El proyecto está preparado para un repositorio público llamado `duplicate-finder-gtk`; la publicación requiere elegir propietario y confirmar. No incluye credenciales. El flujo de CI preparado repite pruebas y empaquetado dentro de Debian Trixie. Consulte [CHANGELOG.md](CHANGELOG.md) y el [informe de verificación](docs/VERIFICATION.md) para los resultados efectivamente obtenidos.
