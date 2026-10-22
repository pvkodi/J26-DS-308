"""Recorded distribution: deliberately contains no model client or network code."""
class InferenceError(RuntimeError): pass
class LocalModel:
    def __init__(self, *args, **kwargs): pass
    def complete(self, *args, **kwargs):
        raise InferenceError('Live inference is not included. Use the component owner laptop for live runs.')
