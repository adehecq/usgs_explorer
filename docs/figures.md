# Figures

Examples of the `usgsxplore viz` outputs, made from Hexagon KH-9 Mapping Camera scenes over Arizona.

The footprint example uses the KH-9 MC scenes acquired in 1974 over a small area near Phoenix:

```bash
usgsxplore search declassii --bbox -111.87783 32.66157 -111.60280 32.89378 -i 1974-01-01 1974-12-31 \
    -f "camera=L" -o kh9_mc_1974.gpkg
```

The strip example uses the single strip acquired on 1976-08-28 over the same area:

```bash
usgsxplore search declassii --bbox -111.87783 32.66157 -111.60280 32.89378 -i 1976-08-28 1976-08-28 \
    -f "camera=L" -o kh9_mc_strip.gpkg
```

The density example uses every KH-9 MC scene over a wider area:

```bash
usgsxplore search declassii --bbox -112.5 32 -111 33.5 -f "camera=L" -o kh9_mc_all.gpkg
```

## `footprint`

```bash
usgsxplore viz footprint kh9_mc_1974.gpkg -o footprint.jpg --roi-bbox -111.87783 32.66157 -111.60280 32.89378
```

![Scene footprints](images/footprint.jpg)

## `density`

```bash
usgsxplore viz density kh9_mc_all.gpkg -o density.jpg --roi-bbox -112.5 32 -111 33.5
```

![Scene overlap density](images/density.jpg)

## `strip`

```bash
usgsxplore viz strip kh9_mc_strip.gpkg -o ./strips --roi-bbox -111.87783 32.66157 -111.60280 32.89378
```

![Strip figure](images/strip.jpg)
