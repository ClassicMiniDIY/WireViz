# -*- coding: utf-8 -*-
"""Errors WireViz raises for problems in the input."""


class WireVizError(ValueError):
    """A problem in the harness description (YAML), not a bug in WireViz.

    It is a ValueError, so existing ``except ValueError`` code catches it.
    Input errors that are already a ValueError or TypeError keep their
    class; the connection-set context is added to their message.
    """
