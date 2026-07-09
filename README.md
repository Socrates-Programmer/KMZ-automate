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

Sube cualquier archivo `.kmz` y descarga el ZIP generado. El ZIP incluye:

- KMZ corregido.
- `reporte_correccion_rutas.csv`.
- Carpeta `excel_rutas/<Distrito>/` con un Excel por ruta corregida.
- `warnings.log`.

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
- `--bundle`: genera ZIP con KMZ, CSV, Excel por ruta y log.

## Logica de correccion

`P1 / PX` significa que las paradas de ida se renombran siguiendo el flujo real del trayecto dibujado en el KMZ. Ese flujo se toma del orden del `LineString`, que es la base del perfil de elevacion de Google Earth.

Ejemplo:

```text
Entrada:  11 paradas originales de ida
Salida:   P1 -> P2 -> ... -> P11 -> P12 -> ... -> P22
```

Las paradas de ida se colocan siguiendo el flujo del LineString de la ruta, del lado derecho del sentido de circulacion. Luego se generan las paradas de regreso en orden inverso, del lado izquierdo, con numeracion normal y sin `Pf`. Por ejemplo, si la ultima parada de ida es `P11`, el regreso empieza en `P12` junto a `P11` y termina en `P22` junto a `P1`. Las paradas de regreso no llevan nombre de centro educativo.

Para calcularlo, la herramienta proyecta cada parada sobre el trayecto y la coloca a 10 metros respecto a la linea del perfil de elevacion. Usa UTM con `pyproj`; en Republica Dominicana usa preferentemente EPSG:32619. Si no hay LineString util, ordena por `P#` o usa el orden KML como fallback y registra advertencia.

Antes de renumerar, las paradas consecutivas que caen practicamente en el mismo punto o en el mismo tramo junto al mismo centro educativo se consolidan en una sola parada. Esto evita salidas como `P1` y `P2` duplicadas frente al mismo instituto.

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

Los centros educativos se detectan dentro del KMZ por carpeta `Escuelas` o por `SimpleData` como `Centro educativo` o `Plantel`. Se elimina codigo inicial tipo `01391 - NOMBRE`, se convierte a mayusculas y se agrega el centro mas cercano a paradas de ida dentro de 100 metros, con formato `P4 - CENTRO EDUCATIVO X`.

Si una parada de ida detecta el mismo centro educativo que otra parada anterior de ida dentro de 150 metros, conserva solo su numero (`P#`) para evitar repetir el mismo instituto demasiado cerca.

## Revision en Google Earth Pro

1. Abre Google Earth Pro.
2. Carga el KMZ corregido.
3. Revisa cada ruta.
4. Confirma que las paradas de ida estan en orden.
5. Confirma que las paradas sigan el flujo del trayecto de la ruta.
6. Confirma que las paradas cerca de escuelas tengan el nombre correcto.
7. Ajusta manualmente solo si alguna parada queda del lado incorrecto de la calle.
