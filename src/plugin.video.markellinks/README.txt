plugin.video.markellinks 1.3.1
================================

Addon para Kodi 21.3 que recopila los enlaces AceStream de markellinks.app
y los reproduce mediante el addon Horus (script.module.horus).

INSTALACION
-----------
1. Usa el ZIP generado por el script.
2. Ajustes > Sistema > Complementos > activa Origenes desconocidos.
3. Complementos > icono de caja > Instalar desde archivo ZIP.
4. Instala antes Horus, arranca el motor AceStream y desactiva en Horus
   "Detener AceStream al salir".

USO
---
- Raiz: cabecera con canales/enlaces/fuente, Buscar, Rescanear y categorias.
- Rescanear fuerza una descarga nueva.
- La cabecera abre un diagnostico con trazas HTTP.

AJUSTES
-------
- Reproduccion directa: activada. Si la reproduccion se corta, desactivala
  para volver al metodo con setResolvedUrl.
- Cache de 10 minutos configurable.
- Se recomienda VPN: LaLiga y las operadoras bloquean AceStream.
- 1.2.1: corregido el bucle al abrir Horus. Nuevo metodo por defecto "Directo a Horus".
- 1.2.2: el modo directo ya no marca el item como reproducible (Horus no resuelve el handle). Metadatos con InfoTagVideo (Kodi 21).
- 1.3.0: Horus se abre igual que en plugin.video.nolokodi (setResolvedUrl(False) + PlayMedia plugin://script.module.horus?action=play&id=HASH). Ajustes en formato Kodi 21.
- 1.3.1: las opciones son elementos-accion (sin resolucion de Kodi, evita reintentos en bucle) + seguro anti-reentrada + trazas en kodi.log. Ajuste "Modo nolokodi" para el metodo anterior.
