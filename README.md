# Corrector KMZ de rutas escolares

Herramienta local para subir o procesar archivos KMZ/KML de rutas escolares y generar un KMZ corregido para revision en Google Earth Pro.

El programa no esta hecho para un distrito especifico. Detecta rutas, paradas y centros educativos por estructura KML y reglas generales. El archivo de San Pedro se usa solo como ejemplo de validacion.

## Instalacion

```bash
cd C:\Users\TRAE58\Desktop\KMZ-automate
python -m pip install -r requirements.txt
```

## Uso web local

```bash
python web_app.py
```

Luego abre:

```text
http://127.0.0.1:5000
```

Desde otra PC conectada a la misma red, abre la IP de esta maquina:

```text
http://10.150.1.76:5000
```

Por defecto la app escucha en `0.0.0.0` para aceptar conexiones de la red local. Puedes cambiar host o puerto con variables de entorno:

```powershell
$env:KMZ_WEB_HOST="0.0.0.0"
$env:KMZ_WEB_PORT="5000"
python web_app.py
```

Si otra PC no puede entrar, revisa que Windows Firewall permita conexiones entrantes al puerto `5000` en la red privada/local.

Sube cualquier archivo `.kmz` y descarga el ZIP generado. El ZIP incluye:

- KMZ corregido.
- `reporte_correccion_rutas.csv`.
- `recorrido_ruta.csv` con las coordenadas del flujo de cada ruta segun el `LineString` usado por el perfil de elevacion.
- `reporte_irregularidades.pdf` con capturas esquematicas de irregularidades detectadas.
- Carpeta `excel_rutas/Rutas <Distrito>/` con una plantilla Excel por ruta corregida.
- `warnings.log`.

En la pantalla puedes elegir la plantilla Excel de salida:

- `BulkCreateTrip`: formato de viajes con `Trip Name*`, `Vehicle*`, `Checkpoints*`, horarios y dias.
- `Plantilla de rutas`: formato de paradas con `ID`, `Ficha Autobus`, `Nombre Del Conductor`, `routename`, `station name`, `latitude` y `longitude`.

## Uso CLI

```bash
python -m kmz_route_corrector --input "archivo.kmz"
```

Tambien funciona:

```bash
python main.py --input "archivo.kmz" --output "archivo_corregido.kmz"
```

Parametros:

- `--input`: archivo `.kmz` de entrada.
- `--output`: archivo `.kmz` corregido. Si se omite, se agrega `_corregido` al nombre original.
- `--offset-meters`: separacion lateral desde la linea. Default `10`, minimo `10`.
- `--school-radius-meters`: radio para asignar centros educativos. Default `100`.
- `--google-places-api-key`: API key opcional de Google Places para buscar escuelas cercanas si no aparecen en el KMZ ni en OpenStreetMap. Tambien puede usarse la variable de entorno `GOOGLE_MAPS_API_KEY`.
- `--google-places-monthly-limit`: limite mensual local de requests a Google Places. Default `5000` o variable `GOOGLE_PLACES_MONTHLY_LIMIT`.
- `--drivers-csv`: CSV de choferes/autobuses. Default `db/KMZ.csv` o variable `KMZ_DRIVERS_CSV_PATH`.
- `--route-template`: plantilla Excel de rutas. Default `kmz-plantilla/BulkCreateTrip.xlsx` o variable `KMZ_ROUTE_TEMPLATE_PATH`.
- `--route-excel-template`: formato de Excel por ruta: `bulk_create_trip` o `plantillas_rutas`.
- `--bulk-trip-type`: valor de `Trip Type*`. Default `Pickup`.
- `--bulk-consider-path`: valor de `Consider Path`. Default `Yes`.
- `--bulk-valid-from`: fecha inicial `dd-MM-yyyy`. Default: fecha actual.
- `--bulk-valid-to`: fecha final `dd-MM-yyyy`. Default: `31-12` del ano actual.
- `--bulk-pickup-time`: hora de recogida `HH:mm`. Default `06:00`.
- `--bulk-drop-time`: hora de salida `HH:mm`. Default `14:00`.
- `--bulk-add-as-address`: valor de `Add As Address`. Default `No`.
- `--bulk-schedule-days`: dias activos separados por coma, por ejemplo `Mo,Tu,We,Th,Fr`. Default todos los dias.
- `--bulk-schedule-value`: texto usado en dias activos. Default `Yes`.
- `--bulk-location`: valor fijo para `Location`. Si se omite, usa el distrito de la ruta.
- `--bundle`: genera ZIP con KMZ, CSV, Excel por ruta y log.

## Plantillas por ruta

Por cada ruta corregida se genera un `.xlsx`. Por defecto usa `kmz-plantilla/BulkCreateTrip.xlsx`. Los archivos quedan agrupados por distrito, por ejemplo:

```text
excel_rutas/Rutas 09-01/001_Ruta #4.xlsx
```

La plantilla se llena con:

- `Trip Name*`: nombre de la ruta detectado en el KML, limpio y alfanumerico (`Ruta #4` sale como `Ruta4`).
- `Trip Type*`: default `Pickup`, configurable desde web o CLI.
- `Consider Path`: default `Yes`, configurable.
- `Vehicle*`: columna `FICHA` del CSV de choferes. Si no hay coincidencia, usa `NO ASIGNADO`.
- `Valid From*`: default fecha actual, configurable en formato `dd-MM-yyyy`.
- `Valid To*`: default `31-12` del ano actual, configurable en formato `dd-MM-yyyy`.
- `Checkpoints*`: todas las coordenadas corregidas de las paradas en orden, con formato `(latitud,longitud)`.
- `Add As Address`: default `No`, configurable.
- `CheckPoint Name*`: todos los nombres de paradas corregidas en el mismo orden.
- `Pickup Time*`: default `06:00`, configurable en formato `HH:mm`.
- `Drop Time*`: default `14:00`, configurable en formato `HH:mm`.
- `GR Number`: codigo generado con distrito y ruta, por ejemplo `0901R4`.
- `Mo` a `Su`: default `Yes` para dias activos y `No` para dias no activos.
- `Location`: usa el valor indicado en web/CLI o, si se deja vacio, el distrito de la ruta.

La coincidencia de ficha/vehiculo se busca por codigo de distrito y numero de ruta usando `db/KMZ.csv`. Si hay varias fichas para la misma ruta, se crea una fila por ficha dentro del mismo Excel de la ruta. La herramienta llena todos los campos de `BulkCreateTrip.xlsx`; los datos operativos que no vienen en el KMZ, como fechas, horarios, dias y tipo de viaje, salen con valores por defecto editables antes de procesar.

Si seleccionas `Plantilla de rutas`, se usa `kmz-plantilla/Plantillas de rutas.xlsx`. En ese formato se crea una fila por parada: `ID` sale como distrito+ruta+parada, por ejemplo `0901R4P1`; `routename` sale sin `#`, por ejemplo `RUTA 4`; `station name`, `latitude` y `longitude` salen del KML corregido. La ficha y el conductor se escriben una sola vez en la primera fila de la ruta; si hay varias fichas o choferes para esa ruta, se agregan juntos separados por `/`.

## Logica de correccion

`P1 / PX` significa que las paradas de ida se renombran siguiendo el flujo real del trayecto dibujado en el KMZ. Ese flujo se toma del orden del `LineString`, que es la base del perfil de elevacion de Google Earth.

Ejemplo:

```text
Entrada:  11 paradas originales de ida
Salida:   P1 -> P2 -> ... -> P11 -> P12 -> ... -> P22
```

Las paradas de ida se colocan siguiendo el flujo del LineString de la ruta, del lado derecho del sentido de circulacion. Luego se generan las paradas de regreso en orden inverso, del lado izquierdo, con numeracion normal y sin `Pf`. Por ejemplo, si la ultima parada de ida es `P11`, el regreso empieza en `P12` junto a `P11` y termina en `P22` junto a `P1`. Cada parada de regreso hereda el nombre del centro educativo de la parada de ida que tiene al lado; si esa parada de ida no lleva nombre, el regreso queda solo con su numero.

Para calcularlo, la herramienta proyecta cada parada sobre el trayecto y la coloca a 10 metros respecto a la linea del perfil de elevacion. Usa UTM con `pyproj`; en Republica Dominicana usa preferentemente EPSG:32619. Si no hay LineString util, ordena por `P#` o usa el orden KML como fallback y registra advertencia.

El archivo `recorrido_ruta.csv` exporta el flujo del `LineString` de cada ruta en el mismo orden usado por Google Earth para el Elevation Profile. Incluye distrito, ruta, indice de vertice, latitud, longitud, altitud, distancia del segmento y distancia acumulada.

Antes de renumerar, las paradas consecutivas que caen practicamente en el mismo punto o en el mismo tramo junto al mismo centro educativo se consolidan en una sola parada. Esto evita salidas como `P1` y `P2` duplicadas frente al mismo instituto.

## Reporte de irregularidades

El ZIP incluye `reporte_irregularidades.pdf`. El PDF se genera siempre; si no hay hallazgos, lo indica en una pagina de resumen.

El reporte mide:

- Paradas eliminadas/consolidadas que estaban a mas de `150 m` de la linea de ruta.
- Tramos largos de ruta sin paradas, usando un umbral de `1500 m` entre inicio/paradas/fin de ruta.

Cada hallazgo incluye una captura esquematica con la linea de ruta y el punto o tramo asociado a la irregularidad. Estas capturas no son imagenes satelitales; son diagramas generados desde la geometria del KMZ para ubicar el problema rapidamente.

## Deteccion de rutas, paradas y escuelas

Una ruta puede venir como carpeta `Ruta...`, carpeta con LineString y paradas, o Document con LineString directo y `Waypoints`.

Las paradas se detectan con esta prioridad:

1. Carpeta hija `Paradas`.
2. Puntos directos dentro de la carpeta de ruta.
3. `Waypoints` cuando la ruta esta a nivel de Document.

El orden se calcula asi:

1. Si la ruta tiene `LineString`, se ordenan por distancia sobre ese trayecto.
2. Si no hay `LineString`, se ordenan por numero `P#` cuando aplique.
3. Si no se puede, se conserva el orden KML y se registra advertencia.

Los centros educativos se detectan primero dentro del KMZ por nombre visible, carpeta o `SimpleData` usando pistas como `Escuela`, `Centro educativo`, `Centros educativos`, `Liceo`, `Liceos` o `Plantel`. Se elimina codigo inicial tipo `01391 - NOMBRE`, se convierte a mayusculas y se agrega el centro mas cercano a paradas de ida dentro de 100 metros, con formato `P4 - CENTRO EDUCATIVO X`.

Si no hay un centro educativo del KMZ dentro del radio, la herramienta consulta OpenStreetMap/Overpass como respaldo gratuito usando `amenity=school|college|university|kindergarten` y nombres como `escuela`, `liceo`, `centro educativo`, `instituto` o `colegio`. Las paradas asignadas con esa fuente quedan marcadas como `OpenStreetMap` en el CSV, en `warnings.log` y en la descripcion KML.

Si tampoco hay resultado en OpenStreetMap y existe `GOOGLE_MAPS_API_KEY`, la herramienta consulta Google Places como respaldo opcional usando tipos educativos (`school`, `primary_school`, `secondary_school`). Las paradas asignadas con esa fuente quedan marcadas como `Google Places`. Este respaldo requiere una API key valida de Google Maps Platform con Places API habilitada y billing activo.

Para usar el cupo gratis de Google Places, la herramienta mantiene un contador local mensual en `outputs/google_places_usage.json` y corta las consultas al llegar al limite configurado. Por defecto usa `5000` requests al mes:

```powershell
$env:GOOGLE_MAPS_API_KEY="TU_API_KEY"
$env:GOOGLE_PLACES_MONTHLY_LIMIT="5000"
python web_app.py
```

Puedes bajar el limite, por ejemplo a `4500`, para dejar margen de seguridad. Este contador local ayuda, pero conviene configurar tambien cuota y alertas en Google Cloud.

Si una parada de ida detecta el mismo centro educativo que otra parada anterior de ida dentro de 150 metros, conserva solo su numero (`P#`) para evitar repetir el mismo instituto demasiado cerca.

## Revision en Google Earth Pro

1. Abre Google Earth Pro.
2. Carga el KMZ corregido.
3. Revisa cada ruta.
4. Confirma que las paradas de ida estan en orden.
5. Confirma que las paradas sigan el flujo del trayecto de la ruta.
6. Confirma que las paradas cerca de escuelas tengan el nombre correcto.
7. Ajusta manualmente solo si alguna parada queda del lado incorrecto de la calle.
