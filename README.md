# GULLØYE – norsk gullsatellitt

Spionsatellitt-visning (CesiumJS) av **modellert potensial for vaskegull** langs norske elver, for hobbyvaskere.
Alt er regnet fra åpne data: NGU, Kartverket, OpenStreetMap, Copernicus Sentinel-2 og Copernicus DEM.

- **Nettside:** https://snkpipefish.github.io/gulloye/
- **Metode og formler:** `web/metode.html` (Manning, Shields, strømeffekt, hydraulisk ekvivalens, weights of evidence, Sentinel-2 båndratioer)

## Struktur

```
pipeline/   Python: henter data, regner modellen, skriver web/public/data/
web/        Vite + CesiumJS: statisk side (GitHub Pages)
```

## Kjøre pipelinen

```bash
python3 -m venv .venv && .venv/bin/pip install -r pipeline/requirements.txt
cd pipeline
../.venv/bin/python -m goldpipe run --area rollag      # ett dypdykk
../.venv/bin/python -m goldpipe national               # nasjonalt 1 km-kart
../.venv/bin/python -m goldpipe regression --area rollag
../.venv/bin/python -m goldpipe auto --n 12 --run       # velg og kjør nye områder fra det nasjonale kartet
../.venv/bin/python -m goldpipe images                  # regenerer bilder uten å kjøre modellen
```

Valgfritt: `export NVE_HYDAPI_KEY=...` (gratis nøkkel fra https://hydapi.nve.no) gir målt vannføring per område.

Områder konfigureres i `pipeline/config/areas.yaml` (bbox, elver, middelflom, dammer). Rå nedlastinger caches i `pipeline/cache/` (ikke i git).

## Kjøre nettsiden

```bash
cd web && npm install && npm run dev
```

Taster: `1–9` område, `0` Norge, `M` kartstabel, `F1–F4` sensor (CRT/NVG/FLIR/NOIR), `A/B/C` beste punkt, `H` hjelp.
Knapper: «Min posisjon» (GPS med avstand/retning til nærmeste punkter), «2D». Lag: eiendomsgrenser, verneområder, lodegull, Sentinel-2.

## Lov og skikk

Alluvialt gull tilhører grunneier. Varsle grunneier og bruker før leting (mineralloven § 10), bruk bare håndredskap,
og meld uttak over 500 m³ eller bruk av maskiner til Direktoratet for mineralforvaltning. Modellen er en beregning, ikke et funn.

## Lisens

MIT. Visuelt konsept inspirert av [gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view) (MIT).
