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
poetry run pytest --ignore=tests/test_download.py -k "not test_download"
```
