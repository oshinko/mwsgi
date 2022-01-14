import argparse
import cgi
import importlib
import inspect
import json
import logging
import pathlib
import re
import sys
import traceback
import urllib.parse
import wsgiref.simple_server

DEFAULT_LOG_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

DEFAULT_LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'

HTTP_STATUSES = {
    int(x.split(maxsplit=1)[0]): x
    for x in """
200 OK
201 Created
202 Accepted
203 Non-Authoritative Information
204 No Content
205 Reset Content
206 Partial Content
207 Multi-Status
208 Already Reported
226 IM Used
300 Multiple Choices
301 Moved Permanently
302 Found
303 See Other
304 Not Modified
305 Use Proxy
307 Temporary Redirect
308 Permanent Redirect
400 Bad Request
401 Unauthorized
402 Payment Required
403 Forbidden
404 Not Found
405 Method Not Allowed
406 Not Acceptable
407 Proxy Authentication Required
408 Request Timeout
409 Conflict
410 Gone
411 Length Required
412 Precondition Failed
413 Payload Too Large
414 URI Too Long
415 Unsupported Media Type
416 Range Not Satisfiable
417 Expectation Failed
418 I'm a teapot
421 Misdirected Request
422 Unprocessable Entity
423 Locked
424 Failed Dependency
425 Too Early
426 Upgrade Required
428 Precondition Required
429 Too Many Requests
431 Request Header Fields Too Large
451 Unavailable For Legal Reasons
501 Not Implemented
502 Bad Gateway
503 Service Unavailable
504 Gateway Timeout
505 HTTP Version Not Supported
506 Variant Also Negotiates
507 Insufficient Storage
508 Loop Detected
510 Not Extended
511 Network Authentication Required
""".strip().split('\n')
}

me = pathlib.Path(__file__)


def _default_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT, DEFAULT_LOG_DATE_FORMAT)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def _s2any(x):
    if not isinstance(x, str):
        return x
    if re.match(r'^\d+$', x):
        return int(x)
    if re.match(r'^\d+\.\d+$', x):
        return float(x)
    return x


class App:
    def __init__(self, logger=None):
        self.logger = logger or _default_logger(me.name)

    def handler(self, handle):
        self.handle = handle
        return self.handle

    def __call__(self, environ, start_response):
        class Request:
            method = 'GET'
            path = '/'
            headers = {}
            mimetype = 'text/plain'
            charset = 'utf8'
            query = {}
            data = b''
            text = ''
            form = {}
            json = None

        class Response:
            headers = {}
            status = None

            @property
            def status_text(self):
                return HTTP_STATUSES[self.status]

        class ReadOnlyHeaders:
            def __init__(self, environ):
                self.__dict__ = {
                    k.replace('HTTP_', '').replace('_', '-').lower(): _s2any(v)
                    for k, v in environ.items()
                    if (k in ['CONTENT_LENGTH', 'CONTENT_TYPE'] or
                        k.startswith('HTTP_'))
                }
                if 'content-length' in self.__dict__:
                    self.__dict__['content-length'] = \
                        max(self.__dict__['content-length'] or 0, 0)

            def __getitem__(self, key):
                return self.__dict__[key.lower()]

            def __repr__(self):
                return repr({k.replace('_', '-'): v
                             for k, v in self.__dict__.items()})

            def __str__(self):
                return str({k.replace('_', '-'): v
                            for k, v in self.__dict__.items()})

            def get(self, *args, **kwargs):
                return self.__dict__.get(*args, **kwargs)

        class RewritableHeaders(ReadOnlyHeaders):
            def __init__(self, source={}):
                super().__init__(source)

            def __setitem__(self, key, value):
                self.__dict__[key.lower()] = value

        req = Request()
        req.method = environ['REQUEST_METHOD']
        req.path = environ['PATH_INFO']
        req.headers = ReadOnlyHeaders(environ)
        req.mimetype, content_type_opts = \
            cgi.parse_header(req.headers['content-type'])
        req.charset = content_type_opts.get('charset', req.charset)
        req.query = dict(urllib.parse.parse_qsl(environ['QUERY_STRING']))
        req.data = environ['wsgi.input'].read(req.headers['content-length'])

        if req.charset:
            try:
                req.text = req.data.decode(req.charset)
            except UnicodeDecodeError:
                pass

        if req.mimetype == 'application/x-www-form-urlencoded':
            req.form = dict(urllib.parse.parse_qsl(req.text))
        elif req.mimetype == 'application/json':
            try:
                req.json = json.loads(req.text)
            except json.decoder.JSONDecodeError:
                self.logger.warning(traceback.format_exc())

        res = Response()
        res.headers = RewritableHeaders()

        spec = inspect.getfullargspec(self.handle)

        if len(spec.args) >= 2 or spec.varargs:
            args = req, res
        elif len(spec.args) == 1:
            args = req,
        else:
            args = ()

        data = self.handle(*args)

        if res.status is None:
            if data is None:
                res.status = 404
            else:
                res.status = 200 if data else 204

        if isinstance(data, (bytearray, bytes)):
            res.headers['content-type'] = \
                res.headers.get('content-type', 'application/octet-stream')
        elif isinstance(data, str):
            res.headers['content-type'] = \
                res.headers.get('content-type', 'text/plain')
            data = data.encode('utf8')
        elif data:
            res.headers['content-type'] = \
                res.headers.get('content-type', 'application/json')
            data = json.dumps(data).encode('utf8')

        start_response(res.status_text,
                       [(k, v) for k, v in vars(res.headers).items()])

        if data:
            yield data


def app_type(s):
    try:
        m, *v = s.rsplit(':')
        v = v[0] if v else 'app'
        return getattr(importlib.import_module(m), v)
    except Exception:
        raise argparse.ArgumentTypeError('Invalid app')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(me.stem)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('app', type=app_type)
    args = parser.parse_args()

    class RequestHandler(wsgiref.simple_server.WSGIRequestHandler):
        def log_message(self, format, *args_):
            args.app.logger.info(format, *args_)

    httpd = wsgiref.simple_server.make_server('', args.port, args.app,
                                              handler_class=RequestHandler)

    with httpd:
        args.app.logger.info(f'Starting {me.stem}')
        args.app.logger.info(f'Listening at http://127.0.0.1:{args.port}')
        httpd.serve_forever()
