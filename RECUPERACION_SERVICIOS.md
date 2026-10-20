# Recuperacion de EVA PDF Enterprise, HelpDesk y Falcon

## Alcance

Se reinicia **solo la aplicacion afectada**, no Windows. No se borran bases de
datos, documentos ni archivos de configuracion. No se llama a `gc.collect()` como
sustituto de la recuperacion: reiniciar el proceso libera su memoria y sus handles.
El supervisor conserva un costo pequeno: una consulta HTTP cada 15 segundos,
sin escanear documentos ni realizar pruebas de memoria sobre el servidor.

La tarea existente de cada proyecto ejecuta `servicios.py serve <Proyecto>`.
Este gestor usa `recovery_supervisor.py`. Cada aplicacion incorpora
`recovery_events.py`, con senales internas Flask y reporte explicito de errores
capturados donde corresponde. Las tareas SYSTEM y las conexiones/puertos
8080, 8090 y 8085 no se modifican. Tampoco se modifica el espejo ni se reinstalan tareas.

## Cuando actua

* Salida inesperada del proceso: programa un nuevo arranque.
* `MemoryError` del servidor: solicita recuperacion mediante archivo de senal
  local, identificado con un token distinto para cada arranque.
* Agotamiento de recursos/handles y errores reales de E/S, incluidos
  `SQLITE_IOERR`: tres eventos en 60 segundos.
* EVA PDF Enterprise: fallo de limpieza temporal (`cleanup_failed`) o imposibilidad de borrar
  un resultado entregado. El supervisor detecta la senal; se conserva el bloqueo
  de trabajos hasta reiniciar.
* Falta de respuesta o respuesta HTTP de salud incorrecta: tres comprobaciones
  consecutivas, tras 60 segundos de gracia de inicio.

Se espera 30 segundos antes de reintentar. Al tercer fallo que requiere reinicio
en una ventana de 15 minutos, el supervisor permanece vivo y deja el servicio
detenido hasta que venza la ventana. Registra el bloqueo y vuelve a
intentar despues. El historial persiste en
`_OPERACION\script\datos\recovery\<Proyecto>.restarts.json`, por lo que un
relanzamiento de la tarea no borra el limite. El reinicio manual autorizado si
restablece este presupuesto.

No provocan reinicio los PDF invalidos, errores de validacion, limites de cola
(429), cancelaciones, timeout normal de un motor aislado, archivos opcionales
inexistentes, errores de permisos, SQLite ocupado ni corrupcion de base de
datos. Estos ultimos requieren revision del administrador; no se intenta
repararlos creando bases vacias ni sobrescribiendo archivos.

Los errores de un motor PDF aislado no equivalen a un fallo de memoria del
servidor. Las comprobaciones HTTP actuales verifican disponibilidad e identidad;
la pagina inicial HelpDesk y `/health` Falcon no certifican la integridad completa
de sus bases de datos. Los errores de E/S se detectan cuando se ejecutan las
operaciones afectadas.

## Reinicio manual

Ejecutar **en el servidor principal, como administrador**, desde PowerShell:

```powershell
& 'G:\PROYECTOS IA INDEPENDIENTES\_OPERACION\script\reiniciar-folio.ps1'
& 'G:\PROYECTOS IA INDEPENDIENTES\_OPERACION\script\reiniciar-helpdesk.ps1'
& 'G:\PROYECTOS IA INDEPENDIENTES\_OPERACION\script\reiniciar-falcon.ps1'
```

Cada comando reinicia solamente su proyecto y comprueba HTTP e identidad del
listener antes de informar exito. Si el puerto pertenece a otro proceso, aborta
sin detenerlo. No hay endpoint web publico de reinicio.

**Planifique una ventana sin operaciones activas**: detener un proceso en
Windows puede interrumpir solicitudes, descargas y tareas pendientes. No existe
garantia de conservar una edicion que aun no se haya descargado. SQLite conserva
sus mecanismos de transaccion; el script no garantiza guardar escrituras en curso.
La recuperacion automatica actua sobre un servicio ya averiado y tambien puede
interrumpir otras peticiones de ese mismo proyecto.

## Logs y mantenimiento

Dentro de la raiz de **cada proyecto**, carpeta `instance\logs`:

| Archivo | Contenido | Rotacion |
|---|---|---|
| `service-events.jsonl` | Arranque, salud, parada, causa, reintento y circuito | 2 MiB + 5 copias |
| `application-events.jsonl` | Excepciones por clase, HTTP 5xx, fallos de recursos | 2 MiB + 5 copias |
| `manual-events.jsonl` | Solicitud manual, resultado y restablecimiento de presupuesto | 2 MiB + 5 copias |
| `server-output.log` | stdout/stderr existentes de la aplicacion | 10 MiB + 3 copias |

Las fechas de eventos estan en UTC. Los eventos estructurados no contienen
cuerpos HTTP, nombres de documentos, contrasenas ni mensajes de excepcion.
La salida tradicional del servidor puede contener detalles propios de la
aplicacion: restringir el acceso a administradores y SYSTEM segun las politicas
locales; no publicar esta carpeta por HTTP.

Se conserva `_OPERACION\script\datos\logs\arranque.log` del gestor.
Los anteriores `<Proyecto>.log` quedan como historico; las nuevas salidas van a
`server-output.log` con rotacion durante la ejecucion.

Si hay disco lleno, permisos incorrectos o averia persistente, el reinicio puede
no resolver la causa. Revisar los logs, espacio y almacenamiento antes de
restablecer el presupuesto. No eliminar el historial automaticamente por error.
Un estado de recuperacion ilegible impide el arranque y exige revision.

Para volver a la version anterior, detener solo la tarea del proyecto afectado,
restaurar sus fuentes desde el respaldo de despliegue y volver a arrancarla.
Para retirar el supervisor de los tres, restaurar ademas el `servicios.py`
respaldado y reiniciar sus tres tareas de forma controlada.

## Validacion

Las pruebas automatizadas usan errores sinteticos: no agotan RAM real ni
provocan averias de disco. Cubren clasificacion, errores que no deben reiniciar,
ventanas, presupuesto persistente, rotacion, senales Flask, parada de un
subproceso propio y seleccion segura del proyecto en reinicio manual.
La regresion EVA PDF Enterprise valida cola, operaciones y editor utilizando el servidor
modificado desde una copia aislada. HelpDesk y Falcon se prueban con base temporal
o gestor de datos simulado, sin ejecutar pruebas de escritura contra sus bases reales.

Los limites EVA PDF Enterprise no cambian: 1024 MiB conjuntos por envio, cinco motores como
maximo, dos pesados y doce trabajos en espera.

### Resultado de activacion

Se aprobaron 19 pruebas de recuperacion (incluido un reinicio automatico real
de un subproceso sintetico con cambio de PID) y 69 pruebas de regresion EVA PDF Enterprise.
HelpDesk y Falcon aprobaron importacion, creacion de la aplicacion, login,
salud HTTP y senal sintetica de memoria con datos aislados.

Los scripts manuales se ejecutaron contra los tres servicios, comprobando
salud e identidad del listener. Tambien se verifico la creacion real de los
registros `server_starting` y `application_hooks_ready` en cada proyecto.

Durante la activacion se detecto una instancia anterior de EVA PDF Enterprise ejecutada
desde la carpeta padre: al detener Enterprise ocupaba el mismo puerto con un
build antiguo. Se detuvo exclusivamente el proceso identificado de esa instancia;
Enterprise volvio a atender 8090. No se modificaron otros servicios por ese conflicto.

El publicador de codigo utiliza las fuentes locales de los tres proyectos y
`D:\script` para `_OPERACION\script`. Se actualizaron ambas caras de la publicacion
y se verificaron hashes: cambiar solo el servidor no era persistente porque el
espejo restauraba las fuentes anteriores. No se deshabilito el publicador.
Las configuraciones privadas y bases de datos quedaron intactas.

Respaldo previo de fuentes en el servidor:
`G:\PROYECTOS IA INDEPENDIENTES\_OPERACION\arranque-principal\recovery-backup-20261020`.
