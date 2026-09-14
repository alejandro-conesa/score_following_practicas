"""
construir_alineacion.py

Construye la tabla de correspondencia tiempo <-> posición en píxel para score
following, parseando directamente los archivos mung/XX.xml.

Cada CropObject con la clave "midi_pitch_code" es una nota. Cada nota trae,
para CADA performance (tempo/instrumento) generada de esa pieza, sus propias
claves:
    {nombre_performance}_onset_seconds
    {nombre_performance}_duration_seconds
    {nombre_performance}_onset_frame
    {nombre_performance}_duration_frame
    {nombre_performance}_note_event_idx

Esto significa que NO hace falta cruzar con el .midi ni preocuparse por notas
sin anotar: el propio dataset ya da el tiempo exacto para la performance que
elijas, directamente en el XML.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def listar_performances_disponibles(xml_path: Path) -> set[str]:
    """
    Inspecciona un mung/XX.xml y devuelve los nombres de performance disponibles
    (útil para copiar el nombre exacto antes de llamar a construir_tabla_alineacion).
    """
    tree = ET.parse(xml_path)
    nombres = set()
    for data_item in tree.iter("DataItem"):
        key = data_item.get("key", "")
        m = re.match(r"(.+)_onset_seconds$", key)
        if m:
            nombres.add(m.group(1))
    return nombres


def _centro_bbox(crop_object: ET.Element) -> tuple[float, float]:
    """Centro (y, x) del bounding box de un CropObject."""
    top = float(crop_object.find("Top").text)
    left = float(crop_object.find("Left").text)
    height = float(crop_object.find("Height").text)
    width = float(crop_object.find("Width").text)
    y = top + height / 2
    x = left + width / 2
    return y, x


def construir_tabla_alineacion(pieza_dir: Path, nombre_performance: str) -> np.ndarray:
    """
    Devuelve un array estructurado con columnas:
        tiempo (f8), duracion (f8), pagina (i4), y (f8), x (f8), pitch (i4)
    ordenado por tiempo, para la performance dada.
    """
    scores_subdirs = list((pieza_dir / "scores").glob("*_ly"))
    if len(scores_subdirs) != 1:
        raise ValueError(f"Se esperaba 1 carpeta *_ly en scores/, encontradas: {len(scores_subdirs)}")
    mung_dir = scores_subdirs[0] / "mung"

    clave_onset = f"{nombre_performance}_onset_seconds"
    clave_duracion = f"{nombre_performance}_duration_seconds"

    filas = []
    for xml_path in sorted(mung_dir.glob("*.xml")):
        num_pagina = int(re.search(r"(\d+)\.xml$", xml_path.name).group(1))
        tree = ET.parse(xml_path)

        for crop_object in tree.iter("CropObject"):
            data_node = crop_object.find("Data")
            data_items = {
                di.get("key"): di.text
                for di in data_node.findall("DataItem")
            } if data_node is not None else {}

            if "midi_pitch_code" not in data_items:
                continue  # no es una nota (es una ligadura, clave, compás, etc.)

            if clave_onset not in data_items:
                # Esta nota no tiene datos para la performance pedida; puede pasar
                # si el nombre no coincide exactamente. Mejor avisar explícitamente.
                continue

            y, x = _centro_bbox(crop_object)
            filas.append((
                float(data_items[clave_onset]),
                float(data_items.get(clave_duracion, 0.0)),
                num_pagina,
                y,
                x,
                int(data_items["midi_pitch_code"]),
            ))

    if not filas:
        disponibles = listar_performances_disponibles(sorted(mung_dir.glob("*.xml"))[0])
        raise ValueError(
            f"Ninguna nota tiene datos para la performance '{nombre_performance}'.\n"
            f"Nombres disponibles en este XML: {sorted(disponibles)}"
        )

    tabla = np.array(
        filas,
        dtype=[("tiempo", "f8"), ("duracion", "f8"), ("pagina", "i4"),
               ("y", "f8"), ("x", "f8"), ("pitch", "i4")],
    )
    tabla.sort(order="tiempo")
    return tabla


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Uso: python construir_alineacion.py <ruta_pieza> <nombre_performance> [carpeta_salida]")
        print("Ejemplo: python construir_alineacion.py ./AdamA__giselle__giselle "
              "AdamA__giselle__giselle_tempo-1000_ElectricPiano ./alineaciones")
        sys.exit(1)

    pieza_dir = Path(sys.argv[1])
    # Tolerante: si por error se pasa la ruta completa a la carpeta de la
    # performance en vez de solo su nombre, nos quedamos con el último componente.
    nombre_performance = Path(sys.argv[2]).name
    carpeta_salida = Path(sys.argv[3]) if len(sys.argv) > 3 else pieza_dir
    carpeta_salida.mkdir(parents=True, exist_ok=True)

    tabla = construir_tabla_alineacion(pieza_dir, nombre_performance)
    print(f"{len(tabla)} notas alineadas para '{nombre_performance}'")
    print(tabla[:5])

    salida = carpeta_salida / f"alineacion_{nombre_performance}.npy"
    np.save(salida, tabla)
    print(f"Guardado en {salida}")