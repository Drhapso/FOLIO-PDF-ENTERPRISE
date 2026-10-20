# Proceso de implementacion de Folio

Este documento resume el trabajo del proyecto para revision y publicacion.
El detalle por build esta en [CHANGELOG](../CHANGELOG.md); la operacion LAN
en [CONFIGURACION_PROYECTO_BLANCO](CONFIGURACION_PROYECTO_BLANCO.md).
No incorpora documentos de usuarios, datos institucionales ni credenciales.

## 1. Base y privacidad

Plataforma propia Flask/Waitress con SQLite solo para configuracion tecnica.
El despliegue LAN toma como referencia otros proyectos, sin conectar sus bases
ni copiar sus configuraciones. Los archivos se procesan en workers aislados
con Job Objects de Windows. Hay bloqueo de instancia, spool temporal, limpieza
antes de responder y entrega transitoria de resultados grandes. Un fallo de
limpieza bloquea nuevos trabajos. El borrado es logico, no forense.

Los originales y resultados que el usuario descarga quedan en su equipo.
HTTP no protege el trafico LAN: HTTPS y permisos de red requieren gestion de TI.

## 2. Ampliacion de herramientas

Se evaluaron herramientas de PDF24 y se implementaron capacidades compatibles
con procesamiento local: organizacion, conversion, compresion, OCR, formularios,
proteccion, comparacion, HEIC, EPUB e informe criptografico de firmas, hasta
46 accesos. OCR admite enderezado hasta 5 grados y limpieza opcional.
Office requiere LibreOffice. PDF/A validado, firma con custodia de claves,
fax y captura arbitraria de URL no se anuncian como resueltos.

La seccion de escritorio/camara/impresion esta cerrada en la interfaz con
"Funcion en Construccion". El endpoint del complemento historico se conserva;
el aviso no constituye una restriccion de autorizacion de ese endpoint.

## 3. Evolucion de cuotas y expedientes

Se paso del limite inicial de 5 archivos al procesamiento masivo por cuota:
1 GB conjunto por envio, hasta 200 archivos en herramientas masivas, incluidas
unir, convertir por lote y armar expediente. Las demas conservan sus cantidades
propias (uno o dos, segun herramienta). Un archivo de 1 GB consume la cuota.
Navegador y servidor validan peso y cantidad.

Armar expediente conserva el orden elegido. La casilla "Incluir pagina inicial
(portada)" esta marcada por defecto; desmarcarla deshabilita el titulo y omite
esa pagina. La API recibe `include_cover` booleano y mantiene la portada si
se omite la opcion, para compatibilidad.

Los antiguos topes de 200/5000 paginas se sustituyeron por 0 (sin tope fijo),
con un maximo de 120 s de motor/lote, memoria acotada y salida de hasta 2 GB.
Se pueden configurar topes administrativos positivos. No se promete procesar
cualquier documento en dos minutos; una tarea costosa puede ser rechazada.

## 4. Capacidad real del equipo

`server.py --calibrate` usa PDFs sinteticos, tres ensayos de combinacion,
render y OCR cuando hay modelos. Se ejecuta con la instancia detenida,
aislamiento de memoria, tiempo limitado y borrado de documentos de prueba.
Solo persiste `instance/performance.json`, excluido de Git y del instalador.

CPU/RAM disponible y latencia de render ajustan concurrencia al arrancar.
5 trabajos y 4 GB por trabajo son techos, no reservas garantizadas.
No hay cola de procesamiento: sin motor libre se responde 429.
Las estimaciones no son limites nuevos de paginas ni un benchmark exhaustivo:
Office, firmas, imagenes complejas y carga simultanea requieren pruebas propias.

## 5. Edicion de texto PDF

Se eliminaron fondos blancos de seleccion y reemplazo. El motor identifica
texto horizontal por linea/estilo, preserva fondos, imagenes y trazos vectoriales
y usa una vista sin texto para previsualizar modificaciones.
No se amplia silenciosamente la caja: el texto que no cabe produce un error.
Se corrigieron flags de negrita/cursiva e identificadores de eliminacion.

No es un clon ni equivalente completo de Acrobat: utiliza fuentes compatibles
Helvetica/Times/Courier, no reconstruye parrafos complejos ni edita texto
incrustado en imagenes. Revisar siempre el PDF guardado.

## 6. Paleta y avisos

Antes de aplicar la paleta se hicieron combinaciones en un HTML independiente.
La paleta negro/violeta/purpura/lima/amarillo se centralizo en `static/palette.css`
para temas claro y oscuro, manteniendo el papel y colores de contenido PDF.
Se verificaron contrastes, foco y vistas moviles. Avisos industriales originales,
esquinas y luces sutiles indican construccion sin usar logotipos de terceros.

## 7. Evolucion de la apertura

1. Logo Folio con arco luminoso; al principio solo primera visita por navegador.
2. A peticion del usuario paso a reproducirse en cada entrada/recarga.
3. Emergente con relieve de papel, bruma, particulas y profundidad.
4. Estado actual: pantalla completa sin recuadro ni boton de omitir, fondo real
   desenfocado, haces y estelas originales, cierre automatico a 4.5 s, Escape
   y omision con `prefers-reduced-motion`. Sin sonido ni contenido remoto.

Las referencias cinematograficas se usaron solo como orientacion general de
movimiento/luz: no se incorporaron GIFs, montanas, coronas de estrellas,
tipografias distintivas ni musica de estudios.
Se guardo un checkpoint ZIP externo con la apertura de arco anterior
(`opening.css`, `opening.js`, fragmento original contenido en `index.html`).
No forma parte del repositorio ni del instalador. Para restaurar, recuperar
CSS/JS y **solo el dialogo de apertura** de esa plantilla; no sobreescribir
la pagina completa si hay cambios posteriores. Subir build, documentar y validar.

## 8. Evidencia y limites de validacion

- Primera ampliacion: 67 pruebas.
- Correccion del editor: 74 pruebas y regresiones de fondos/imagenes/lineas.
- Capacidad adaptativa: 80 pruebas aprobadas, expediente de 5227 paginas,
  union de 5226 y division de 201 paginas.
- Portada opcional: cuatro pruebas de expediente, API booleana, orden, cuotas
  y limite administrativo. Las pruebas posteriores se acumulan en `tests`.
- Interfaz: temas claro/oscuro, escritorio/movil/horizontal, reduccion de
  movimiento, cierre y repeticion de apertura; sin errores JS en esas pruebas.

Estos conteos describen ejecuciones historicas, no una certificacion automatica
de cada commit. Repetir las pruebas para la release.
La conectividad desde otro equipo fisico, antivirus, instalacion limpia,
licencias y ejecutable congelado quedan sujetos a aceptacion especifica.

## 9. Proxima distribucion

Se prepararon parametros `3.1.0` para Folio.exe onedir y Setup.exe offline,
sin construirlos. Se adapto el despacho de workers en modo congelado para que
no intenten ejecutar un script `.py` usando Folio.exe como si fuera Python.
Se ejecutaron 86 pruebas de fuente con resultado correcto. Se valido la sintaxis
de los scripts, pero la politica de PowerShell bloqueo la prevalidacion real;
no se altero esa politica ni se instalaron herramientas de empaquetado.
El detalle y checklist estan en [DISTRIBUCION_OFFLINE](DISTRIBUCION_OFFLINE.md).
No se hizo commit, push ni publicacion automatica.
