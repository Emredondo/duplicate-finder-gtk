# Duplicate Finder GTK 0.1.3


Utilidad libre para GNU/Linux que encuentra archivos exactamente iguales por contenido. Utiliza Python 3, GTK 3 y GIO, sin nube ni telemetría.


## Descargar e instalar


- [Descargar el paquete DEB](https://github.com/Emredondo/duplicate-finder-gtk/releases/download/v0.1.3/duplicate-finder-gtk_0.1.3_all.deb)
- [Código fuente completo, pruebas y documentación](https://github.com/Emredondo/duplicate-finder-gtk/releases/download/v0.1.3/duplicate-finder-gtk-0.1.3-source.zip)
- [Módulos principales](https://github.com/Emredondo/duplicate-finder-gtk/tree/main/duplicate_finder)


En Debian 13, desde la carpeta de descarga:


```sh
sudo apt install ./duplicate-finder-gtk_0.1.3_all.deb
duplicate-finder-gtk
```


También puede abrir la aplicación desde el menú de utilidades. Para desinstalarla: `sudo apt remove duplicate-finder-gtk`. Sus preferencias se conservan.


## Uso y seguridad


Elija una carpeta y pulse **Analizar**. Los resultados aparecen sin marcar. Seleccione manualmente o utilice la selección automática para conservar la copia más antigua, la más reciente o la de una carpeta prioritaria. La aplicación siempre conserva al menos una copia de cada grupo.


Puede enviar la selección a la papelera o elegir **Eliminar definitivamente…**. Esta última opción pide confirmación y borra los archivos seleccionados sin enviarlos a la papelera. Cancelar es la opción predeterminada.


El contenido y los metadatos se vuelven a comprobar antes de cada operación. La aplicación compara tamaños, hashes SHA-256 y bytes; no sigue enlaces simbólicos y cuenta los enlaces duros una sola vez. Cierre los programas que escriban en esos archivos: las operaciones no son atómicas frente a cambios simultáneos.


## Código y pruebas


El ZIP contiene la estructura completa, pruebas, documentación y el constructor del DEB. La versión 0.1.3 pasó 63 pruebas automatizadas y pruebas gráficas GTK/GIO, incluidos el borrado de 1.000 duplicados temporales y la cancelación durante un borrado en curso. El paquete fue construido y validado en Debian 13; la verificación en una imagen Debian limpia sigue pendiente.


## Licencia


[GPL-3.0-or-later](LICENSE).

