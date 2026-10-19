"""wareApp views, one module per feature (split from the former views.py).

``from wareApp.views import *`` (wareApp/urls.py) still exposes every view.
"""

from .alarms import *  # noqa: F401,F403
from .auth import *  # noqa: F401,F403
from .baseline import *  # noqa: F401,F403
from .common import *  # noqa: F401,F403
from .common import _dg_fuel_db_alias, _dg_fuel_queryset  # noqa: F401
from .customer import *  # noqa: F401,F403
from .devices import *  # noqa: F401,F403
from .dg_fuel import *  # noqa: F401,F403
from .energy_saving import *  # noqa: F401,F403
from .fire import *  # noqa: F401,F403
from .load import *  # noqa: F401,F403
from .monitoring import *  # noqa: F401,F403
from .power_distribution import *  # noqa: F401,F403
from .provisioning import *  # noqa: F401,F403
from .site import *  # noqa: F401,F403
from .submetering import *  # noqa: F401,F403
from .superadmin import *  # noqa: F401,F403
