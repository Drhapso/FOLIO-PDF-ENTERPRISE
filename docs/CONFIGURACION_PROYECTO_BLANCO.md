# Configuracion y operacion LAN

## Independencia

Folio toma como referencia el despliegue Flask/Waitress y SQLite central de
FALCON y Help Desk, no sus datos ni credenciales. Las tres aplicaciones tienen
entornos, puertos, bases y directorios separados. No mover bases operativas
a esta carpeta ni publicar contenido de otros proyectos.

La copia publicable excluye `.venv`, `instance`, `runtime`, modelos descargados,
logs y `config\site_config.json`. Revisar el TXT de referencia antes de publicarlo.
No se ha publicado ni creado un repositorio remoto automaticamente.

## Preparar

Para distribuir sin Python en el destino, consultar
[DISTRIBUCION_OFFLINE](DISTRIBUCION_OFFLINE.md). Los comandos siguientes
corresponden al arranque desde codigo fuente. La proxima receta de instalador
esta preparada pero no se ha construido ni certificado.

El directorio actual del proyecto es `D:\EDITOR Y COMPRESOR PDF\FOLIO PDF`.
Ejecutar los comandos desde esa carpeta. Los lanzadores calculan la raiz desde
su ubicacion; no necesitan conservar la ruta anterior.

1. Crear el entorno e instalar `requirements.txt` siguiendo el README.
2. Instalar LibreOffice local para conversion Office. No requiere Microsoft Office.
3. Ejecutar `deploy\install-ocr.ps1` una vez para descargar modelos locales;
   revisar sus hashes. La operacion diaria puede ser sin Internet.
4. Copiar el ejemplo JSON a `config\site_config.json` si se desea cambiar limites.
   Claves de capacidad por sesion de procesamiento: `max_files` (5),
   `max_upload_mb` (1024, peso conjunto) y `max_file_mb` (1024, no puede superar
   `max_upload_mb`). Herramientas masivas (unir, dividir, comprimir, conversiones
   desde PDF): `max_batch_files` (200, tope tecnico dentro de la misma cuota de
   1 GB), incluido Armar expediente. `max_pages` y `max_batch_pages` valen 0:
   sin tope fijo de paginas; valores positivos permiten un tope administrativo.
   Servidor: `max_output_mb` (2048), `max_parallel_jobs` (techo 5),
   `max_job_memory_mb` (techo 4096) y `timeout_seconds` (120, nunca mas de
   120 efectivos). CPU, RAM disponible y perfil medido reducen los techos al
   iniciar. El tiempo cubre el motor completo, no la transferencia.
5. Arrancar primero en loopback y verificar `http://127.0.0.1:8090/health`.
6. Usar `deploy\run-lan.ps1` para escuchar en todas las interfaces IPv4.
   No se configura firewall ni red de forma implicita.

## Medicion local de capacidad

Con el servidor detenido, ejecutar:

```powershell
.\.venv\Scripts\python.exe .\server.py --calibrate
```

Prueba sintetica aislada con combinacion, render y OCR si hay modelos locales,
tres muestras por motor; timeout y memoria acotados. Se usa el bloqueo exclusivo
para no competir con trabajos de usuarios. Se eliminan los documentos de prueba;
solo `instance\performance.json` conserva tiempos y especificaciones tecnicas.
Reiniciar normalmente para aplicar el perfil. Sin perfil, solo se dimensiona por
hardware y `/api/capabilities` indica `performance.calibrated: false`.
No hay cola: los motores ocupados responden 429. Los trabajos que exceden
120 s se cancelan y limpian, sin PDF parcial. No se garantiza procesar cualquier
cantidad de paginas en dos minutos. Las estimaciones no son limites obligatorios
y no representan Office, firmas ni documentos arbitrarios. Recalibrar al cambiar
de equipo, motores o carga habitual; revisar disco libre y RAM antes de servir.

## Firewall

Desde PowerShell elevado, indicar la subred autorizada real. El ejemplo
usa un marcador y no es un comando listo para ejecutar sin sustituirlo.

```powershell
.\deploy\configure-firewall.ps1 -AuthorizedSubnet '<SUBRED_AUTORIZADA/CIDR>' -Port 8090
.\deploy\configure-firewall.ps1 -AuthorizedSubnet '<SUBRED_AUTORIZADA/CIDR>' -Port 8090 -Apply
```

Sin `-Apply` solo consulta. Con `-Apply` crea una regla TCP entrante exclusiva,
limitada a esa subred y perfiles Domain/Private. Rechaza sobrescribir una regla
existente. No abre UDP, puertos SQLite, NAT o puertos de otras aplicaciones.
No cambia IP, DNS ni proxy. Si cambia el puerto, revisar la regla antigua.

Desde un cliente abrir `http://<SERVIDOR_LAN>:8090`, nunca el HTML como archivo.
Comprobar desde **otro equipo fisico**; una respuesta local no prueba el firewall.
No exponer a Internet.

## HTTPS y arranque persistente

HTTP no cifra documentos ni claves, incluso en LAN. Para documentos sensibles
usar HTTPS con certificado confiable y un proxy inverso administrado por TI.
No se instala un proxy ni se reutiliza la configuracion de otros proyectos.
El backend no acepta CORS ni procesa solicitudes POST de origen externo.

Si hay terminacion TLS, el proxy debe reescribir Origin y Host de forma
coherente hacia el backend o integrar una politica explicita de origen
antes del despliegue. No habilitar confianza indiscriminada en X-Forwarded-*.
Probar carga, descarga y tamanos maximos tambien en el proxy; desactivar
cache y almacenamiento temporal de cuerpos de solicitudes/respuestas en el proxy.
La politica de eliminacion solo cubre Folio, no un proxy configurado por terceros.

Para inicio con Windows, TI puede registrar `deploy\run-lan.ps1` como tarea
bajo una cuenta dedicada de privilegios minimos, con acceso solo a este proyecto,
arranque del equipo y reinicio en fallo. No se crea automaticamente una tarea
como SYSTEM ni se almacenan credenciales en scripts. El servidor debe permanecer
encendido y sin suspension. La persistencia del proceso requiere esa instalacion.

## Recuperacion y verificacion

- `/health`: identificador `pdf-lan`, estado y build.
- `/api/capabilities`: disponibilidad de OCR/Office y limites, sin documentos.
- Solicitudes y resultados usan `Cache-Control: no-store`.
- Solo un servidor puede usar el mismo directorio `runtime`.
- Si falla la limpieza, corregir permisos/antivirus/espacio y reiniciar.
  El arranque elimina `runtime\job-*` antes de servir y falla si no puede.
- No limpiar manualmente temporales con trabajos activos.
- No realizar respaldos de `runtime`, perfiles Office o modelos transitorios.
  La configuracion tecnica si puede respaldarse sin documentos.
- Revisar nombres, fechas, cifras y aspecto de conversiones/OCR.
- La redaccion elimina la zona indicada, no busca automaticamente todos los
  datos sensibles ni garantiza saneado forense de cualquier PDF complejo.

Las pruebas incluyen documentos generados, errores, claves, limites, cierre de
procesos y ausencia de temporales. La prueba de reinicio de Windows, carga
sostenida y conectividad desde otro equipo deben realizarse en el entorno final.

## Ampliacion Toolbox y clientes Windows

Actualizar dependencias con el entorno exclusivo:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

pikepdf incorpora qpdf para reparar y linealizar sin ejecutables de red.
No se modifica el esquema SQLite: sigue guardando solo configuracion tecnica.
No se agregan puertos, cuentas, historiales, servicios de cliente ni credenciales.
Las herramientas nuevas usan el mismo subproceso, Job Object, timeout,
limites y directorio temporal por trabajo. No requieren nuevos valores JSON.
Recargar la pagina tras reiniciar para enviar el nuevo build.

El complemento se descarga de `/desktop/download`. El operador lo ejecuta
manualmente en cada cliente Windows con `-STA`, sin permisos administrativos
ni instalaciones automaticas. El escaneo requiere WIA; la impresion depende
de una aplicacion PDF con verbo Print registrado y confirmacion explicita.
Diagnostico: `powershell -NoProfile -STA -File .\Folio-Desktop.ps1 -Action Diagnose`.
No interpretar una solicitud al spooler como confirmacion de impresion.

La cabecera Permissions-Policy permite camara y captura solo al propio origen,
sin microfono ni geolocalizacion. Se mantienen CSP, no-store y origen estricto.
El acceso HTTP LAN sigue sin habilitar APIs que exigen contexto seguro;
configurar HTTPS conforme a la seccion anterior antes de usarlas.

PDF/A, creacion de firmas certificadas, verificacion de confianza/revocacion
y fax siguen fuera de las capacidades operativas. Cualquier futura integracion
necesita aprobacion de sus motores, certificados, acceso de red y politica de retencion. El escaneo guardado por
el cliente y los datos del spooler no estan bajo la eliminacion del servidor.

## OCR avanzado, HEIC, EPUB y firmas offline

Instalar las dependencias actualizadas de `requirements.txt` en el entorno
propio: OpenCV headless/NumPy, pillow-heif y pyHanko. No se agregan claves JSON,
puertos ni servicios de cliente. El preprocesamiento OCR es opcional y viene
desactivado para preservar el comportamiento anterior: enderezado hasta 5 grados
o enderezado con limpieza binaria. No sustituye la revision visual.

HEIC/HEIF admite un fotograma y el mismo limite de pixeles que las otras
imagenes. EPUB a PDF admite libros sin DRM, sujeto a `max_pages` si es positivo tras
reflujo A4 y `max_upload_mb` MB descomprimidos, con hasta 10000 entradas.
PDF a EPUB exporta texto por pagina y conserva la cuota masiva de 1 GB.

La comprobacion de firmas utiliza contextos pyHanko con descarga deshabilitada
y sin raices de confianza. El JSON distingue bytes firmados, firma criptografica,
cobertura y modificaciones; no certifica identidad, revocacion ni validez legal.
Una firma puede seguir correcta sobre una revision anterior aunque el documento
actual tenga cambios. No se solicitan ni reciben claves privadas o certificados
PKCS#12. PDF/A requiere instalar un conversor y un validador como veraPDF;
HTTPS requiere certificado confiable y despliegue aprobado por TI.
