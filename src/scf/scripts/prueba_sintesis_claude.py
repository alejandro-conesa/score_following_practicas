#!/usr/bin/env python3
"""
sintetizar_midis.py

Sintetiza a WAV los archivos MIDI de un dataset de piezas musicales, usando
fluidsynth como motor de síntesis (se invoca como subproceso).

Estructura de dataset esperada:
    DATASET/
      Pieza1/
        performances/
          variante1/variante1.midi
          variante2/variante2.midi
      Pieza2/
        performances/
          ...

Uso básico:
    python sintetizar_midis.py \
        --dataset ./dataset \
        --output ./wavs \
        --soundfonts FluidR3_GM.sf2 acoustic_grand_piano.sf2 \
        --map mapa_instrumentos.json \
        --limit 20 \
        --jobs 4

Requisitos: Python 3.8+, y el binario `fluidsynth` en el PATH.
No requiere librerías externas (usa solo la librería estándar).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------
# Configuración e instrumentos
# --------------------------------------------------------------------------

@dataclass
class Instrumento:
    etiqueta: str      # texto a buscar en el nombre del .midi (ej. "ElectricPiano")
    soundfont: str      # debe coincidir con uno de los --soundfonts pasados
    banco: int
    programa: int


def cargar_mapa_instrumentos(path: Path) -> list[Instrumento]:
    instrumentos: list[Instrumento] = []

    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data:
        instrumentos.append(Instrumento(
            etiqueta=entry["etiqueta"],
            soundfont=entry["soundfont"],
            banco=int(entry["banco"]),
            programa=int(entry["programa"]),
        ))

    return instrumentos


def resolver_instrumento(nombre_midi: str, mapa: list[Instrumento]) -> Optional[Instrumento]:
    """Devuelve el primer instrumento cuya etiqueta aparece en el nombre del archivo."""
    for inst in mapa:
        if inst.etiqueta in nombre_midi:
            return inst
    return None


# --------------------------------------------------------------------------
# Descubrimiento y selección de performances
# --------------------------------------------------------------------------

def encontrar_performances(dataset_dir: Path) -> list[Path]:
    """Encuentra todos los .mid/.midi dentro de cualquier subcarpeta performances/."""
    archivos = sorted(
        p for p in dataset_dir.rglob("*")
        if p.suffix.lower() in (".mid", ".midi") and "performances" in p.parts
    )
    return archivos


def nombre_pieza(midi_path: Path, dataset_dir: Path) -> str:
    """La 'pieza' es el primer directorio bajo dataset_dir."""
    return midi_path.relative_to(dataset_dir).parts[0]


def seleccionar_performances(
    archivos: list[Path], dataset_dir: Path, modo: str, semilla: Optional[int]
) -> list[Path]:
    if modo == "all":
        
        return archivos

    if modo == "random1":
        rng = random.Random(semilla)
        por_pieza: dict[str, list[Path]] = {}
        for midi in archivos:
            por_pieza.setdefault(nombre_pieza(midi, dataset_dir), []).append(midi)
        seleccion = [rng.choice(variantes) for variantes in por_pieza.values()]
        seleccion.sort()
        logging.info("Modo random1: %d performances elegidas (1 por obra, %d obras)",
                     len(seleccion), len(por_pieza))
        return seleccion

    raise ValueError(f"Modo de selección desconocido: {modo!r}")


# --------------------------------------------------------------------------
# Síntesis
# --------------------------------------------------------------------------

def construir_comandos_select(instrumento: Instrumento, soundfonts: list[str]) -> str:
    """Genera el contenido del archivo de comandos 'select' para fluidsynth."""
    try:
        sfid = soundfonts.index(instrumento.soundfont) + 1  # ids 1-based, orden de carga
    except ValueError:
        raise ValueError(
            f"El soundfont '{instrumento.soundfont}' del mapa no está en --soundfonts"
        )
    lineas = [f"select {canal} {sfid} {instrumento.banco} {instrumento.programa}"
              for canal in range(16)]
    return "\n".join(lineas) + "\n"


def sintetizar_uno(
    midi_path: Path,
    output_dir: Path,
    soundfonts: list[str],
    sample_rate: int,
    mapa: Optional[list[Instrumento]],
) -> tuple[Path, bool, str]:
    """Sintetiza un único MIDI. Devuelve (ruta_midi, exito, mensaje)."""
    salida = output_dir / f"{midi_path.stem}.wav"
    if salida.exists():
        return midi_path, True, "SKIP (ya existe)"

    # Todas las opciones ANTES de los archivos posicionales (soundfonts + midi):
    # algunos parsers de opciones (macOS/BSD) no reordenan flags que aparezcan
    # después del primer argumento no-opcional.
    args = ["fluidsynth", "-ni", "-F", str(salida), "-r", str(sample_rate)]

    tmp_cmd_path: Optional[Path] = None
    if mapa is not None:
        instrumento = resolver_instrumento(midi_path.name, mapa)
        if instrumento is None:
            return midi_path, False, "ninguna etiqueta del mapa coincide con el nombre"
        try:
            contenido = construir_comandos_select(instrumento, soundfonts)
        except ValueError as e:
            return midi_path, False, str(e)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="select_"
        )
        tmp.write(contenido)
        tmp.close()
        tmp_cmd_path = Path(tmp.name)
        args += ["-f", str(tmp_cmd_path)]

    args += soundfonts + [str(midi_path)]

    try:
        resultado = subprocess.run(args, capture_output=True, text=True)
        if resultado.returncode != 0:
            return midi_path, False, resultado.stderr.strip()[-500:]
        return midi_path, True, "OK"
    finally:
        if tmp_cmd_path is not None:
            tmp_cmd_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parsear_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", "-i", required=True, type=Path, help="Directorio raíz del dataset")
    p.add_argument("--output", "-o", required=True, type=Path, help="Directorio de salida para los .wav")
    p.add_argument("--soundfonts", "-s", required=True, nargs="+", help="Rutas a los .sf2, en orden de carga")
    p.add_argument("--map", "-m", type=Path, default=None, help="Archivo JSON o TSV de mapeo de instrumentos")
    p.add_argument("--pmode", "-p", choices=["all", "random1"], default="all",
                   help="Cuántas performances por obra: 'all' o 'random1'")
    p.add_argument("--seed", "-R", type=int, default=None, help="Semilla para --pmode random1")
    p.add_argument("--limit", "-n", type=int, default=None, help="Número máximo de archivos a procesar")
    p.add_argument("--jobs", "-j", type=int, default=1, help="Procesos en paralelo")
    p.add_argument("--sample-rate", "-r", type=int, default=44100)
    p.add_argument("--manifest", type=Path, default=None,
                   help="CSV donde registrar el resultado de cada render (por defecto: output/manifest.csv)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parsear_args()

    if not args.dataset.is_dir():
        logging.error("El dataset '%s' no existe", args.dataset)
        return 1
    for sf in args.soundfonts:
        if not Path(sf).is_file():
            logging.error("No se encuentra el soundfont '%s'", sf)
            return 1

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.output / "manifest.csv")

    mapa = cargar_mapa_instrumentos(args.map) if args.map else None
    if mapa is not None:
        logging.info("Mapeo cargado: %d etiquetas desde '%s'", len(mapa), args.map)

    archivos = encontrar_performances(args.dataset)
    if not archivos:
        logging.error("No se encontraron .mid/.midi dentro de 'performances/' en '%s'", args.dataset)
        return 1

    archivos = seleccionar_performances(archivos, args.dataset, args.pmode, args.seed)

    if args.limit is not None:
        archivos = archivos[: args.limit]

    logging.info("A procesar: %d archivos (salida: %s)", len(archivos), args.output)

    resultados = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor, \
         manifest_path.open("w", newline="", encoding="utf-8") as manifest_file:

        writer = csv.writer(manifest_file)
        writer.writerow(["midi", "salida", "exito", "mensaje"])

        futuros = {
            executor.submit(
                sintetizar_uno, midi, args.output, args.soundfonts, args.sample_rate, mapa
            ): midi
            for midi in archivos
        }

        for futuro in as_completed(futuros):
            midi_path, exito, mensaje = futuro.result()
            estado = "OK" if exito else "FAIL"
            logging.info("[%s] %s (%s)", estado, midi_path.stem, mensaje)
            writer.writerow([str(midi_path), f"{midi_path.stem}.wav", exito, mensaje])
            resultados.append(exito)

    ok = sum(resultados)
    logging.info("Terminado: %d/%d correctos. Manifest en %s", ok, len(resultados), manifest_path)
    return 0 if ok == len(resultados) else 2


if __name__ == "__main__":
    sys.exit(main())