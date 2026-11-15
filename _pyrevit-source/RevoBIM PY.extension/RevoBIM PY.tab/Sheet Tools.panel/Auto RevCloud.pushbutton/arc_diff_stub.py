# -*- coding: utf-8 -*-
"""Bench shim: the parts of arc_diff that are plain Python.

arc_diff cannot be imported under CPython - it opens with Revit imports - but
`still_in_host` is ordinary logic and is the rule that decides whether an
element counts as deleted. Read out of the source so it cannot drift from the
real one.
"""
import ast
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_NAMESPACE = {}


def _load(name):
    if name in _NAMESPACE:
        return _NAMESPACE[name]
    with io.open(os.path.join(HERE, u"arc_diff.py"), u"r", encoding=u"utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            code = compile(module, u"arc_diff.py", u"exec")
            scope = {}
            exec(code, scope)
            _NAMESPACE[name] = scope[name]
            return _NAMESPACE[name]
    raise RuntimeError(u"{0} not found in arc_diff.py".format(name))


def still_in_host(doc, changes):
    return _load(u"still_in_host")(doc, changes)
