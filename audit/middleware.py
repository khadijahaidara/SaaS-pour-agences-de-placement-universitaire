from . import context


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = context.set_request(request)
        try:
            return self.get_response(request)
        finally:
            context.reset(token)
