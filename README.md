[![Tests](https://github.com/adehecq/usgs_explorer/actions/workflows/python-tests.yml/badge.svg)](https://github.com/adehecq/usgs_explorer/actions/workflows/python-tests.yml)

# Description

The **usgsxplore** Python package provides an interface to the [USGS M2M API](https://m2m.cr.usgs.gov/) to search and download data available from the [Earth Explorer](https://earthexplorer.usgs.gov/) platform.

This package is highly inspired by [landsatxplore](https://github.com/yannforget/landsatxplore) but it supports more datasets and adds new functionalities.

# Quick start

Searching for Landsat scenes over the location (5.7074, 45.1611) acquired between 2010-2020.

```bash
usgsxplore search landsat_tm_c2_l1 --location 5.7074 45.1611 --interval-date 2010-01-01 2020-01-01
```

Search for Hexagon KH-9 scenes. Save the result into a geopackage and a HTML map

```bash
usgsxplore search declassii --filter "camera=H" --output results.gpkg --output map.html
```

Downloading the 10 first images from landsat_tm_c2_l1

```bash
usgsxplore search landsat_tm_c2_l1 --limit 10 --output results.txt
usgsxplore download results.txt
```

# Installation

The package can be installed using pip.

```bash
pip install usgsxplore

# or with pipx
pipx install usgsxplore
```

# Usage

**usgsxplore** can be used both through its command-line interface and as a python module (example : [download.ipynb](./examples/download.ipynb)).

## Command-line interface

```bash
usgsxplore --help
```

```
Usage: usgsxplore [OPTIONS] COMMAND [ARGS]...

  Command line interface of the usgsxplore. Documentation :
  https://github.com/adehecq/usgs_explorer

Options:
  --help  Show this message and exit.

Commands:
  download         Download scenes with their entity ids provided in the textfile.
  download-browse  Download browse images of a vector data file localy.
  info             Display information on available datasets and filters.
  search           Search scenes in a dataset with filters.
```

### Credentials

Credentials for the Earth Explorer portal can be obtained [here](https://ers.cr.usgs.gov/register/). Note that you need to specify specifically all datasets you plan to access through the API.

`--username` and `--token` can be provided as command-line options or as environment variables:

``` shell
export USGS_USERNAME=<your_username>
export USGS_TOKEN=<your_token>
```

### Searching

```bash
usgsxplore search --help
```

```
Usage: usgsxplore search [OPTIONS] DATASET

  Search scenes in a dataset with filters.

Options:
  -u, --username TEXT          EarthExplorer username.  [required]
  -t, --token TEXT             EarthExplorer token.  [required]
  -o, --output PATH            Output file : (txt, json, html, gpkg, shp,
                               geojson)
  -vf, --vector-file PATH      Vector file that will be used for spatial
                               filter
  -l, --location FLOAT...      Point of interest (longitude, latitude).
  -b, --bbox FLOAT...          Bounding box (xmin, ymin, xmax, ymax).
  -c, --clouds INTEGER         Max. cloud cover (1-100).
  -i, --interval-date TEXT...  Date interval (start, end), (YYYY-MM-DD, YYYY-
                               MM-DD).
  -f, --filter TEXT            String representation of metadata filter
  -m, --limit INTEGER          Max. results returned. Return all by default
  --pbar                       Display a progress bar
  --help                       Show this message and exit.
```

If the `--output` is not provided, the command will print the entity ids of scenes found. Else if `--output` is provided it will save the results in the given file. Five formats are currently supported for the output:

- **text file (.txt)** : Each line is an entity id and the first line contain the dataset ex: `#dataset=landsat_tm_c2_l1`. This file can then be used to download the images.
- **json file (.json)** : json file containing the results of the search.
- **vector data (.gpkg, .shp, .geojson)** : save the results in a vector file, useful to visualise the geographic location of the results in a GIS.
- **HTML file (.html)** : save the results in a HTML file to have a quick look of scenes on a map.

The search command works with multiple scene-search so there is no limit of results, but you can fixe one with `--limit`.

If you provide a wrong dataset, a list of 50 datasets with high string similarity will be printed.

The `--filter` works like this "`field1=value1 & field2=value2 | field3=value3`". For the field you can put either the filter id, the filter label, or the sql filter. For the value you can put either value or value label. Exemples:

```bash
# select scenes from the Hexagon KH-9 satellite
# all of those 4 command will give the same results
usgsxplore search declassii --filter "camera=L"
usgsxplore search declassii --filter "Camera Type=L"
usgsxplore search declassii --filter "5e839ff8cfa94807=L"
usgsxplore search declassii --filter "camera=KH-9 Lower Resolution Mapping Camera"

# select scenes from the Hexagon KH-9 satellites if they are downloadable
usgsxplore search declassii --filter "camera=L & DOWNLOAD_AVAILABLE=Y"
```

**Note**: To know which filters are available, check the command `usgsxplore info` below.

### Downloading

```bash
usgsxplore download --help
```

```
Usage: usgsxplore download [OPTIONS] TEXTFILE

  Download scenes with their entity ids provided in the textfile. The dataset
  can also be provide in the first line of the textfile : #dataset=declassii

Options:
  -u, --username TEXT           EarthExplorer username.
  -t, --token TEXT              EarthExplorer token.  [required]
  -d, --dataset TEXT            Dataset
  -p, --product-number INTEGER  The product index you want (default: None)
  -o, --output-dir PATH         Output directory
  -m, --max-workers INTEGER     Max thread number (default: 5)
  --overwrite                   Overwrite existing files
  --hide-pbar                   Hide the progress bar
  --no-extract                  Skip the extraction of files
  --help                        Show this message and exit.
```

This command download scenes from their entity ids in the `TEXTFILE` and save the results in `--output-dir`.
It also extract file in place.

### Downloading browse

```bash
usgsxplore download-browse --help
```

```
Usage: usgsxplore download-browse [OPTIONS] VECTOR_FILE

  Download browse images of a vector data file localy.

Options:
  -o, --output-dir PATH  Output directory
  --pbar                 Display a progress bar.
  --help                 Show this message and exit.
```

### Info: datasets and filters

Information on available datasets and filters can be printed on screen with the command `usgsxplore info`

```bash
usgsxplore info --help
```

```
Usage: usgsxplore info [OPTIONS] COMMAND [ARGS]...

  Display information on available datasets and filters.

Options:
  --help  Show this message and exit.

Commands:
  dataset  Display the list of available datasets in the API.
  filters  Display a list of available filter fields for a dataset.
```

**Hints**: When using `usgsxplore search`, filters will be printed to screen when typing any (wrong) value. For example,

```bash
usgsxplore search declassii -f "whatever=?"
```

will print all metadata filters that can be used for the "declassii" dataset.

<img width="439" alt="image" src="https://github.com/user-attachments/assets/e3fc1fdc-9ee2-4ddb-a9a4-863c5884a1d3">

```bash
usgsxplore search declassii -f "camera=?"
```

will print all possible values for the filter "camera".

<img width="391" alt="image" src="https://github.com/user-attachments/assets/bcdedad7-39b0-44de-bf8c-fc7e4ca5f1ee">
