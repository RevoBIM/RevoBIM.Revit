# -*- coding: utf-8 -*-
"""A small JSON reader and writer.

Pure Python, no .NET, no stdlib json: which modules an IronPython engine
ships varies by pyRevit release, and settings already avoid json for the
same reason. Only what the Autodesk Data Management API sends is needed.
"""


class JsonError(ValueError):
    pass


_ESCAPES = {u'"': u'"', u"\\": u"\\", u"/": u"/", u"b": u"\b",
            u"f": u"\f", u"n": u"\n", u"r": u"\r", u"t": u"\t"}
_WHITE = u" \t\r\n"


def _text(value):
    if isinstance(value, bytes):
        return value.decode(u"utf-8")
    return u"{0}".format(value) if not _is_text(value) else value


def _is_text(value):
    try:
        return isinstance(value, basestring)  # noqa: F821 - IronPython 2.7
    except NameError:
        return isinstance(value, str)


class _Reader(object):
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def fail(self, message):
        raise JsonError(u"{0} at character {1}".format(message, self.pos))

    def skip(self):
        text = self.text
        while self.pos < len(text) and text[self.pos] in _WHITE:
            self.pos += 1

    def value(self):
        self.skip()
        if self.pos >= len(self.text):
            self.fail(u"unexpected end")
        ch = self.text[self.pos]
        if ch == u"{":
            return self.obj()
        if ch == u"[":
            return self.arr()
        if ch == u'"':
            return self.string()
        if self.text.startswith(u"true", self.pos):
            self.pos += 4
            return True
        if self.text.startswith(u"false", self.pos):
            self.pos += 5
            return False
        if self.text.startswith(u"null", self.pos):
            self.pos += 4
            return None
        return self.number()

    def obj(self):
        out = {}
        self.pos += 1
        self.skip()
        if self.text[self.pos:self.pos + 1] == u"}":
            self.pos += 1
            return out
        while True:
            self.skip()
            if self.text[self.pos:self.pos + 1] != u'"':
                self.fail(u"expected a key")
            key = self.string()
            self.skip()
            if self.text[self.pos:self.pos + 1] != u":":
                self.fail(u"expected ':'")
            self.pos += 1
            out[key] = self.value()
            self.skip()
            ch = self.text[self.pos:self.pos + 1]
            self.pos += 1
            if ch == u"}":
                return out
            if ch != u",":
                self.fail(u"expected ',' or '}'")

    def arr(self):
        out = []
        self.pos += 1
        self.skip()
        if self.text[self.pos:self.pos + 1] == u"]":
            self.pos += 1
            return out
        while True:
            out.append(self.value())
            self.skip()
            ch = self.text[self.pos:self.pos + 1]
            self.pos += 1
            if ch == u"]":
                return out
            if ch != u",":
                self.fail(u"expected ',' or ']'")

    def string(self):
        self.pos += 1
        parts = []
        text = self.text
        while True:
            if self.pos >= len(text):
                self.fail(u"unterminated string")
            ch = text[self.pos]
            if ch == u'"':
                self.pos += 1
                return u"".join(parts)
            if ch == u"\\":
                code = text[self.pos + 1:self.pos + 2]
                if code == u"u":
                    hex_digits = text[self.pos + 2:self.pos + 6]
                    try:
                        point = int(hex_digits, 16)
                    except ValueError:
                        self.fail(u"bad \\u escape")
                    self.pos += 6
                    if 0xD800 <= point < 0xDC00 and text[self.pos:self.pos + 2] == u"\\u":
                        low = int(text[self.pos + 2:self.pos + 6], 16)
                        point = 0x10000 + ((point - 0xD800) << 10) + (low - 0xDC00)
                        self.pos += 6
                    parts.append(_chr(point))
                    continue
                if code not in _ESCAPES:
                    self.fail(u"bad escape")
                parts.append(_ESCAPES[code])
                self.pos += 2
                continue
            parts.append(ch)
            self.pos += 1

    def number(self):
        start = self.pos
        text = self.text
        while self.pos < len(text) and text[self.pos] in u"+-0123456789.eE":
            self.pos += 1
        raw = text[start:self.pos]
        if not raw:
            self.fail(u"unexpected character")
        try:
            if any(c in raw for c in u".eE"):
                return float(raw)
            return int(raw)
        except ValueError:
            self.fail(u"bad number")


def _chr(point):
    try:
        return unichr(point)  # noqa: F821 - IronPython 2.7
    except NameError:
        return chr(point)
    except ValueError:
        return u"\ufffd"


def loads(text):
    reader = _Reader(_text(text))
    result = reader.value()
    reader.skip()
    if reader.pos != len(reader.text):
        reader.fail(u"extra data")
    return result


def _quote(value):
    out = [u'"']
    for ch in value:
        if ch == u'"':
            out.append(u'\\"')
        elif ch == u"\\":
            out.append(u"\\\\")
        elif ch == u"\n":
            out.append(u"\\n")
        elif ch == u"\r":
            out.append(u"\\r")
        elif ch == u"\t":
            out.append(u"\\t")
        elif ord(ch) < 0x20 or ord(ch) > 0x7E:
            out.append(u"\\u{0:04x}".format(ord(ch)))
        else:
            out.append(ch)
    out.append(u'"')
    return u"".join(out)


def dumps(value):
    if value is None:
        return u"null"
    if value is True:
        return u"true"
    if value is False:
        return u"false"
    if isinstance(value, (int, float)):
        return u"{0}".format(value)
    if isinstance(value, dict):
        return u"{" + u",".join(
            _quote(_text(k)) + u":" + dumps(v) for k, v in sorted(value.items())) + u"}"
    if isinstance(value, (list, tuple)):
        return u"[" + u",".join(dumps(v) for v in value) + u"]"
    return _quote(_text(value))


def dig(data, *path):
    """data['a'][0]['b'] without the KeyErrors; None when any step is missing."""
    current = data
    for step in path:
        try:
            current = current[step]
        except (KeyError, IndexError, TypeError):
            return None
    return current
