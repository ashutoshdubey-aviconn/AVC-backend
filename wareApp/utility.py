import logging
import time
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from rest_framework import status
from django.core.exceptions import ObjectDoesNotExist
logger = logging.getLogger('django.request')

def entryExit(aFunc):
    """Trace entry, exit and exceptions."""

    def loggedFunc(*args, **kw):
        logger.debug('enter In Function : {} at {} '.format(aFunc.__name__, str(time.strftime('%I:%M:%S %p'))))
        try:
            result = aFunc(*args, **kw)
            logger.info("These are the arguments {} and results {}".format(args, result))
        except AttributeError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        except NameError as e:
            return Response({"error":"Please try after some time."}, status=status.HTTP_400_BAD_REQUEST)
        except ObjectDoesNotExist:
            return Response({"error":"Invalid Payload"}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({"error":e.detail}, status=e.status_code)
        except Exception as e:
            logger.critical('exception in {}  and {}'.format(aFunc.__name__, e))
            return Response({"error":"API Error"}, status=status.HTTP_400_BAD_REQUEST)

        logger.debug('exit from Function : {} at {} '.format(aFunc.__name__, str(time.strftime('%I:%M:%S %p'))))
        return result

    loggedFunc.__name__ = aFunc.__name__
    loggedFunc.__doc__ = aFunc.__doc__
    return loggedFunc
