# mwsgi

![Python 3](https://img.shields.io/badge/python-3-blue.svg)

This is a very simple, single-file WSGI server module.


## Installation

```sh
python -m pip install "mwsgi @ git+https://github.com/oshinko/mwsgi.git"
```


## Usage

Edit `mywsgi.py`.

```python
import mwsgi

app = mwsgi.App()


@app.handler
def handle(req, res):
    app.logger.info(f'req.headers: {req.headers}')
    app.logger.info(f'req.query: {req.query}')
    app.logger.info(f'req.form: {req.form}')
    app.logger.info(f'req.json: {req.json}')
    return dict(greet='Hello!')
```

Run.

```sh
python -m mwsgi mywsgi
```

or

```sh
python -m mwsgi mywsgi:app
```

To change the port number.

```sh
python -m mwsgi mywsgi --port 3000
```
