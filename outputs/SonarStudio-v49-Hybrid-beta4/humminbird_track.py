# SPDX-License-Identifier: MIT
"""Export position changes from known Humminbird SON layouts."""

import argparse
import csv
from math import atan, degrees, exp, pi, tan
import os
from pathlib import Path
import struct
from tempfile import NamedTemporaryFile


_MAGIC = bytes.fromhex("c0 de ab 21")
_RECORD_TAGS = bytes(range(0x80, 0x85))
_LAYOUTS = ((67, 34), (72, 39), (152, 39))
_GPS_RADIUS = 6_378_388
_LATITUDE_CORRECTION = 1.0067642927


def _iter_records(son, cancelled):
    with son.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        offset = 0
        while offset < size:
            if cancelled():
                raise InterruptedError("Exportação cancelada.")
            stream.seek(offset)
            header = stream.read(152)
            if header[:4] != _MAGIC or header[4:25:5] != _RECORD_TAGS:
                raise ValueError(f"{son.name}: início de ping inválido no byte {offset}.")
            candidates = []
            for length, depth_tag in _LAYOUTS:
                if (len(header) < length or header[length - 6] != 0xA0
                        or header[length - 1] != 0x21 or header[depth_tag] != 0x87):
                    continue
                count = struct.unpack_from(">I", header, length - 5)[0]
                next_offset = offset + length + count
                if next_offset > size:
                    continue
                if next_offset != size:
                    stream.seek(next_offset)
                    if stream.read(4) != _MAGIC:
                        continue
                candidates.append((depth_tag, next_offset))
            if len(candidates) != 1:
                raise ValueError(f"{son.name}: formato de ping inválido ou ambíguo no byte {offset}.")
            depth_tag, offset = candidates[0]
            east = struct.unpack_from(">i", header, 15)[0]
            north = struct.unpack_from(">i", header, 20)[0]
            depth_dm = struct.unpack_from(">i", header, depth_tag + 1)[0]
            yield east, north, depth_dm


def export_track(son, target, *, cancelled=lambda: False):
    """Save the first ping at each consecutive GPS position, including zero depth."""
    son, target = Path(son), Path(target)
    if target.resolve() == son.resolve() or target.exists() and target.samefile(son):
        raise ValueError("O CSV não pode substituir o arquivo SON.")
    if target.suffix.casefold() != ".csv":
        raise ValueError("Use a extensão .csv para exportar a trilha.")
    previous = None
    rows = 0
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False,
            dir=target.parent, prefix=".sonarstudio-", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("Latitude", "Longitude", "Depth(m)"))
            for east, north, depth_dm in _iter_records(son, cancelled):
                position = (east, north)
                if position == previous:
                    continue
                previous = position
                if position == (0, 0) or max(abs(east), abs(north)) > pi * _GPS_RADIUS:
                    continue
                if depth_dm < 0:
                    continue
                mercator_lat = 2 * atan(exp(north / _GPS_RADIUS)) - pi / 2
                lat = degrees(atan(tan(mercator_lat) * _LATITUDE_CORRECTION))
                lon = degrees(east / _GPS_RADIUS)
                writer.writerow((lat, lon, f"{depth_dm / 10:.2f}"))
                rows += 1
            if not rows:
                raise ValueError(f"{son.name}: nenhum ponto utilizável para exportação.")
        if cancelled():
            raise InterruptedError("Exportação cancelada.")
        os.replace(temporary, target)
        return rows
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("son", type=Path, help="Canal SON primário da gravação, como R00050/B001.SON")
    parser.add_argument("output", type=Path, help="CSV de saída")
    args = parser.parse_args()
    try:
        rows = export_track(args.son, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Falha na exportação: {error}\n")
    print(f"{rows:,} pontos exportados para {args.output}")


if __name__ == "__main__":
    main()
