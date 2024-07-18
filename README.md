# Description

The **usgsxplore** Python package provides an interface to the [M2M API](https://m2m.cr.usgs.gov/) to search and donwloads scenes.

This package is highly inspired of [landsatxplore](https://github.com/yannforget/landsatxplore) but it support more dataset and add functionalities.

# Quick start

Searching for Landsat scenes that contains the location (5.7074, 45.1611) acquired between 2010-2020.

```
usgsxplore search landsat_tm_c2_l1 --location 5.7074 45.1611 --interval-date 2010-01-01 2020-01-01
```

Search for Hexagon KH-9 scenes. Save the result into a geopackage

```
usgsxplore search declassii --filter "camera=H" --output results.gpkg
```

Downloading ids.txt --dataset landsat_tm_c2_l1
