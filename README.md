# Duplicate Finder GTK 0.1.1

Utilidad libre para GNU/Linux que encuentra archivos **exactamente iguales por contenido**, aunque tengan nombres o extensiones diferentes. Utiliza Python 3, GTK 3, PyGObject y GIO. No utiliza servicios en la nube ni telemetría.

## Descargar e instalar

- [Descargar el paquete DEB para Debian 13](https://github.com/Emredondo/duplicate-finder-gtk/raw/refs/heads/main/duplicate-finder-gtk_0.1.1_all.deb)
- [Descargar el código fuente completo, las pruebas y la documentación](https://github.com/Emredondo/duplicate-finder-gtk/raw/refs/heads/main/duplicate-finder-gtk-0.1.1-source.zip)
- [Ver los módulos principales del programa](duplicate_finder/)

Una vez descargado el paquete, abra una terminal en su carpeta y ejecute:

```sh
sudo apt install ./duplicate-finder-gtk_0.1.1_all.deb
duplicate-finder-gtk
```

También puede iniciar la aplicación desde el menú de utilidades. Para desinstalarla, conservando sus preferencias:

```sh
sudo apt remove duplicate-finder-gtk
```

## Uso y seguridad

Elija una carpeta, configure las opciones de búsqueda y pulse **Analizar**. Los resultados se muestran sin marcar en árbol o tabla. Puede elegir manualmente las copias o seleccionarlas automáticamente conservando la más antigua, la más reciente o una copia de la carpeta prioritaria. Siempre debe conservarse al menos una copia por grupo.

La aplicación compara tamaños, hashes SHA-256 parciales y completos, y finalmente los bytes. No sigue enlaces simbólicos y cuenta los enlaces duros al mismo archivo una sola vez. Antes de enviar archivos a la papelera vuelve a comprobar su identidad y contenido. **No realiza borrado permanente**.

Cierre los programas que estén escribiendo en los archivos antes de operar: GIO mueve los archivos por ruta y las comprobaciones no constituyen una operación atómica frente a cambios simultáneos. El espacio indicado es una estimación y no se libera hasta vaciar la papelera.

## Código fuente y pruebas

El archivo ZIP de código fuente contiene el proyecto completo con su estructura, las pruebas, la documentación, el informe de verificación y las instrucciones para reconstruir el DEB. Descomprímalo antes de ejecutar `make test`, `make check` o `make deb`.

La versión 0.1.1 pasó 57 pruebas automatizadas y pruebas gráficas GTK/GIO. La instalación y actualización se verificaron en Debian 13 aislado; queda pendiente verificarlas en una imagen Debian limpia y una sesión XFCE completa.

## Licencia

[GPL-3.0-or-later](LICENSE).
