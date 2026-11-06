import logging
from functools import wraps

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response

logger = logging.getLogger("django.request")


def entryExit(aFunc):
    """Trace entry and exit of a view method and turn errors into 400 responses.

    Response bodies and status codes are unchanged from the original decorator;
    only the handlers that crashed (they read a ``.detail`` that AttributeError
    and ValueError do not have) are fixed, and unexpected errors are logged with
    their traceback. Arguments and results are logged at DEBUG only.
    """

    @wraps(aFunc)
    def loggedFunc(*args, **kw):
        logger.debug("enter %s", aFunc.__qualname__)
        try:
            result = aFunc(*args, **kw)
        except AttributeError as error:
            logger.exception("AttributeError in %s", aFunc.__qualname__)
            return Response(
                {"error": getattr(error, "detail", "API Error")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except NameError:
            logger.exception("NameError in %s", aFunc.__qualname__)
            return Response(
                {"error": "Please try after some time."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ObjectDoesNotExist:
            return Response({"error": "Invalid Payload"}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as error:
            return Response(
                {"error": getattr(error, "detail", str(error))},
                status=getattr(error, "status_code", status.HTTP_400_BAD_REQUEST),
            )
        except APIException as error:
            # Expected client errors (e.g. invalid login): one line, no traceback.
            logger.warning("%s in %s: %s", type(error).__name__, aFunc.__qualname__, error)
            return Response({"error": "API Error"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("Exception in %s", aFunc.__qualname__)
            return Response({"error": "API Error"}, status=status.HTTP_400_BAD_REQUEST)
        logger.debug("exit %s", aFunc.__qualname__)
        return result

    return loggedFunc
