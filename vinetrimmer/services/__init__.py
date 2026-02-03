import os
import re
from copy import copy

from vinetrimmer.services.BaseService import BaseService

SERVICE_MAP = {}

from vinetrimmer.services.amazon import Amazon
from vinetrimmer.services.appletvplus import AppleTVPlus
from vinetrimmer.services.bbciplayer import BBCiPlayer
from vinetrimmer.services.disneyplus import DisneyPlus
from vinetrimmer.services.f1tv import F1tv
from vinetrimmer.services.globoplay import Globoplay
from vinetrimmer.services.googleplay import GooglePlay
from vinetrimmer.services.hotstar import Hotstar
from vinetrimmer.services.hulu import Hulu
from vinetrimmer.services.itunes import iTunes
from vinetrimmer.services.jio import Jio
from vinetrimmer.services.max import Max
from vinetrimmer.services.moviesanywhere import MoviesAnywhere
from vinetrimmer.services.mubi import Mubi
from vinetrimmer.services.netflix import Netflix
from vinetrimmer.services.paramountplus import ParamountPlus
from vinetrimmer.services.peacock import Peacock
from vinetrimmer.services.rakutentv import RakutenTV 
from vinetrimmer.services.sonyliv import Sonyliv
from vinetrimmer.services.sunnxt import Sunnxt
from vinetrimmer.services.viu import Viu


# Above is necessary since dynamic imports like below fuck up Nuitka

# Below dynamic imports fuck with compiling when using Nuitka - exec() call is the problem
#for service in os.listdir(os.path.dirname(__file__)):
#    if service.startswith("_") or not service.endswith(".py"):
#        continue

#    service = os.path.splitext(service)[0]

#    if service in ("__init__", "BaseService"):
#        continue 

#    with open(os.path.join(os.path.dirname(__file__), f"{service}.py"), encoding="utf-8") as fd:
#        code = ""
#        for line in fd.readlines():
#            if re.match(r"\s*(?:import(?! click)|from)\s", line):
#                continue
#            code += line
#            if re.match(r"\s*super\(\)\.__init__\(", line):
#                break
#        exec(code)

for x in copy(globals()).values():
    if isinstance(x, type) and issubclass(x, BaseService) and x != BaseService:
        SERVICE_MAP[x.__name__] = x.ALIASES


def get_service_key(value):
    """
    Get the Service Key name (e.g. DisneyPlus, not dsnp, disney+, etc.) from the SERVICE_MAP.
    Input value can be of any case-sensitivity and can be either the key itself or an alias.
    """
    value = value.lower()
    for key, aliases in SERVICE_MAP.items():
        if value in map(str.lower, aliases) or value == key.lower():
            return key
