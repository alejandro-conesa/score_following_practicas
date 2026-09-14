#!/usr/bin/env bash
#
# sintetizar_midis.sh
# Sintetiza archivos MIDI a WAV usando fluidsynth y uno o varios soundfonts.
#
# Busca únicamente los .mid/.midi que estén dentro de cualquier subcarpeta
# "performances/" del dataset (estructura: DATASET/Pieza/performances/variante/variante.midi)
#
# Uso:
#   ./sintetizar_midis.sh -i DIR_DATASET -o DIR_SALIDA -s "sf1.sf2 sf2.sf2" [-n N] [-j JOBS] [-r SR] [-f comandos.txt]
#
# Opciones:
#   -i DIR      Directorio raíz del dataset (contiene las carpetas de cada pieza) (obligatorio)
#   -o DIR      Directorio de salida para los .wav (obligatorio)
#   -s "SFS"    Lista de soundfonts entre comillas, separados por espacio (obligatorio)
#   -n N        Número de archivos a procesar. Si se omite o es "all", procesa todos.
#   -j JOBS     Número de procesos en paralelo (por defecto: 1)
#   -r SR       Sample rate (por defecto: 44100)
#   -f FILE     Archivo de comandos fluidsynth (select ...) opcional. Se ignora si usas -m.
#   -m MAPFILE  Archivo TSV de mapeo etiqueta->soundfont/banco/programa (ver mapa_instrumentos.tsv).
#               Si se indica, el instrumento se decide automáticamente según el nombre
#               de cada .midi, generando el "select" internamente (tiene prioridad sobre -f).
#   -h          Muestra esta ayuda
#
# Ejemplos:
#   # Probar con 10 archivos, secuencial
#   ./sintetizar_midis.sh -i ./midis -o ./wavs -s "piano.sf2 strings.sf2" -n 10
#
#   # Procesar todo el dataset con 8 procesos en paralelo (servidor potente)
#   ./sintetizar_midis.sh -i ./midis -o ./wavs -s "piano.sf2 strings.sf2" -n all -j 8
#
#   # Usando mapeo automático de instrumento por nombre de archivo
#   ./sintetizar_midis.sh -i ./dataset -o ./wavs -s "piano.sf2 strings.sf2" -m mapa_instrumentos.tsv -n all -j 8

set -euo pipefail

DIR_MIDI=""
DIR_SALIDA=""
SOUNDFONTS=""
N="all"
JOBS=1
SR=44100
CMDFILE=""
MAPFILE=""

mostrar_ayuda() {
    grep '^#' "$0" | sed -n '2,30p' | sed 's/^# \{0,1\}//'
}

while getopts "i:o:s:n:j:r:f:m:h" opt; do
    case "$opt" in
        i) DIR_MIDI="$OPTARG" ;;
        o) DIR_SALIDA="$OPTARG" ;;
        s) SOUNDFONTS="$OPTARG" ;;
        n) N="$OPTARG" ;;
        j) JOBS="$OPTARG" ;;
        r) SR="$OPTARG" ;;
        f) CMDFILE="$OPTARG" ;;
        m) MAPFILE="$OPTARG" ;;
        h) mostrar_ayuda; exit 0 ;;
        *) mostrar_ayuda; exit 1 ;;
    esac
done

# --- Validaciones ---
if [[ -z "$DIR_MIDI" || -z "$DIR_SALIDA" || -z "$SOUNDFONTS" ]]; then
    echo "Error: -i, -o y -s son obligatorios." >&2
    mostrar_ayuda
    exit 1
fi

if ! command -v fluidsynth >/dev/null 2>&1; then
    echo "Error: fluidsynth no está instalado o no está en el PATH." >&2
    exit 1
fi

if [[ ! -d "$DIR_MIDI" ]]; then
    echo "Error: el directorio del dataset '$DIR_MIDI' no existe." >&2
    exit 1
fi

for sf in $SOUNDFONTS; do
    if [[ ! -f "$sf" ]]; then
        echo "Error: no se encuentra el soundfont '$sf'." >&2
        exit 1
    fi
done

if [[ -n "$CMDFILE" && ! -f "$CMDFILE" ]]; then
    echo "Error: no se encuentra el archivo de comandos '$CMDFILE'." >&2
    exit 1
fi

if [[ -n "$MAPFILE" && ! -f "$MAPFILE" ]]; then
    echo "Error: no se encuentra el archivo de mapeo '$MAPFILE'." >&2
    exit 1
fi

mkdir -p "$DIR_SALIDA"

# --- Validar el mapa al arrancar (falla rápido si hay soundfonts mal escritos) ---
if [[ -n "$MAPFILE" ]]; then
    N_ETIQUETAS=0
    while IFS=$'\t' read -r etiqueta sf banco programa; do
        [[ -z "$etiqueta" || "$etiqueta" == \#* ]] && continue
        encontrado_sf=0
        for candidato in $SOUNDFONTS; do
            [[ "$candidato" == "$sf" ]] && { encontrado_sf=1; break; }
        done
        if [[ "$encontrado_sf" -eq 0 ]]; then
            echo "Error: en '$MAPFILE', el soundfont '$sf' (etiqueta '$etiqueta') no está en -s." >&2
            exit 1
        fi
        N_ETIQUETAS=$((N_ETIQUETAS + 1))
    done < "$MAPFILE"
    echo "Mapeo cargado: $N_ETIQUETAS etiquetas desde '$MAPFILE'"
fi

# --- Recolectar lista de archivos MIDI (solo dentro de performances/) ---
TODOS_MIDI=()
while IFS= read -r linea; do
    TODOS_MIDI+=("$linea")
done < <(find "$DIR_MIDI" -type f -path "*/performances/*" \( -iname "*.mid" -o -iname "*.midi" \) | sort)
TOTAL=${#TODOS_MIDI[@]}

if [[ "$TOTAL" -eq 0 ]]; then
    echo "No se encontraron archivos .mid/.midi dentro de subcarpetas 'performances/' en '$DIR_MIDI'." >&2
    exit 1
fi

if [[ "$N" == "all" ]]; then
    N_PROCESAR=$TOTAL
else
    if ! [[ "$N" =~ ^[0-9]+$ ]]; then
        echo "Error: -n debe ser un número entero o 'all'." >&2
        exit 1
    fi
    N_PROCESAR=$N
    if (( N_PROCESAR > TOTAL )); then
        N_PROCESAR=$TOTAL
    fi
fi

ARCHIVOS=("${TODOS_MIDI[@]:0:$N_PROCESAR}")

# --- Aviso de posibles colisiones de nombre (se usa el nombre del .midi tal cual) ---
# Compatible con bash 3.2 (macOS): sin arrays asociativos.
BASENAMES_TMP="$(mktemp "${TMPDIR:-/tmp}/sintetizar_midis_basenames.XXXXXX")"
for midi in "${ARCHIVOS[@]}"; do
    echo "$(basename "${midi%.*}")"$'\t'"$midi" >> "$BASENAMES_TMP"
done
DUPLICADOS="$(cut -f1 "$BASENAMES_TMP" | sort | uniq -d)"
if [[ -n "$DUPLICADOS" ]]; then
    while IFS= read -r dup; do
        [[ -z "$dup" ]] && continue
        echo "AVISO: nombre de salida duplicado '${dup}.wav':" >&2
        awk -F'\t' -v d="$dup" '$1==d{print "       -> " $2}' "$BASENAMES_TMP" >&2
    done <<< "$DUPLICADOS"
fi
rm -f "$BASENAMES_TMP"

echo "Encontrados: $TOTAL archivos MIDI en performances/"
echo "A procesar:  ${#ARCHIVOS[@]} archivos"
echo "Salida:      $DIR_SALIDA"
echo "Soundfonts:  $SOUNDFONTS"
echo "Sample rate: $SR"
echo "Procesos:    $JOBS"
echo "-----------------------------------------"

# --- Función que procesa un solo archivo ---
# Nota: no usa arrays asociativos del proceso padre (no se exportan a subprocesos
# en paralelo), así que si hay MAPFILE, cada llamada relee el TSV y calcula el
# índice del soundfont contando su posición en $SOUNDFONTS.
procesar_uno() {
    local midi="$1"
    local base
    base="$(basename "${midi%.*}")"
    local salida="${DIR_SALIDA}/${base}.wav"

    if [[ -f "$salida" ]]; then
        echo "[SKIP] $base (ya existe)"
        return 0
    fi

    local args=(-ni -F "$salida" -r "$SR")

    local tmpcmd=""
    if [[ -n "$MAPFILE" ]]; then
        # Buscar qué etiqueta del mapa aparece en el nombre del archivo
        local etiqueta sf banco programa sfid encontrado=0
        while IFS=$'\t' read -r etiqueta sf banco programa; do
            [[ -z "$etiqueta" || "$etiqueta" == \#* ]] && continue
            if [[ "$base" == *"$etiqueta"* ]]; then
                sfid=0
                local i=1
                for candidato in $SOUNDFONTS; do
                    if [[ "$candidato" == "$sf" ]]; then
                        sfid=$i
                        break
                    fi
                    i=$((i + 1))
                done
                if [[ "$sfid" -eq 0 ]]; then
                    echo "[FAIL] $base (soundfont '$sf' del mapa no está en -s)"
                    return 1
                fi
                tmpcmd="$(mktemp "${TMPDIR:-/tmp}/sintetizar_midis_select.XXXXXX")"
                for ch in $(seq 0 15); do
                    echo "select $ch $sfid $banco $programa" >> "$tmpcmd"
                done
                encontrado=1
                break
            fi
        done < "$MAPFILE"

        if [[ "$encontrado" -eq 0 ]]; then
            echo "[FAIL] $base (ninguna etiqueta del mapa coincide con el nombre)"
            return 1
        fi
        args+=(-f "$tmpcmd")
    elif [[ -n "$CMDFILE" ]]; then
        args+=(-f "$CMDFILE")
    fi

    # Los archivos posicionales (soundfonts + midi) van al FINAL, después de
    # todas las opciones (-ni -F -r -f). Algunos getopt (macOS/BSD) no reordenan
    # flags que aparezcan después del primer argumento posicional.
    for sf in $SOUNDFONTS; do
        args+=("$sf")
    done
    args+=("$midi")

    if fluidsynth "${args[@]}" >/dev/null 2>>"${DIR_SALIDA}/errores.log"; then
        echo "[OK]   $base"
    else
        echo "[FAIL] $base (ver errores.log)"
    fi
    [[ -n "$tmpcmd" ]] && rm -f "$tmpcmd"
}

export -f procesar_uno
export DIR_SALIDA SOUNDFONTS SR CMDFILE MAPFILE

# --- Procesamiento, secuencial o paralelo ---
if [[ "$JOBS" -le 1 ]]; then
    for midi in "${ARCHIVOS[@]}"; do
        procesar_uno "$midi"
    done
else
    if ! command -v parallel >/dev/null 2>&1; then
        echo "Aviso: 'parallel' (GNU parallel) no está instalado, usando xargs en su lugar." >&2
        printf '%s\n' "${ARCHIVOS[@]}" | xargs -P "$JOBS" -I{} bash -c 'procesar_uno "$@"' _ {}
    else
        printf '%s\n' "${ARCHIVOS[@]}" | parallel -j "$JOBS" procesar_uno {}
    fi
fi

echo "-----------------------------------------"
echo "Listo. WAVs en: $DIR_SALIDA"