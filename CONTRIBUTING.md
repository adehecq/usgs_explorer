# Contribute to project

First step clone the repo or fork it to create a pull request.
Next setup the development environnement :
```bash
# install poetry if you don't have it
pip install poetry

# you need to be in the usgs_explorer repo
poetry install

# install the pre-commit hooks
poetry run pre-commit install
```

Before committing make sure to passed all tests:
```bash
poetry run pytest
```

You can also run the notebooks : [download.ipynb](./examples/download.ipynb)

## Examples of commands
```bash

usgsxplore search aerial_combin --bbox -111.87783 32.66157 -111.60280 32.89378 -i 1977-10-14 1977-10-14 -f "IMAGE_TYPE=13" -o data/1977_10_14/1977_10_14_aerial.gpkg -o data/1977_10_14/1977_10_14_aerial.html -o data/1977_10_14/1977_10_14_aerial.txt

usgsxplore search aerial_combin --bbox -111.87783 32.66157 -111.60280 32.89378 -i 1978-09-06 1978-09-06 -o data/1978_09_06/1978_09_06_aerial.gpkg -o data/1978_09_06/1978_09_06_aerial.html -o data/1978_09_06/1978_09_06_aerial.txt

usgsxplore search aerial_combin --bbox -111.87783 32.66157 -111.60280 32.89378 -i 1976-04-01 1976-04-01 -o data/1976_04_01/1976_04_01_aerial.gpkg -o data/1976_04_01/1976_04_01_aerial.html -o data/1976_04_01/1976_04_01_aerial.txt



```
