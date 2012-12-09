from django.conf import settings
from django.http import HttpResponse

def hello(request):
    first_app = settings.get_api("first_zrpc")
    return HttpResponse("ping? %s!" %(first_app.ping(), ),
                        content_type="text/plain")
