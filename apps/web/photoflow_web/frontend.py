"""Serve the client shell for known UI URLs, retaining genuine API/asset 404s."""

import re
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            route = "/" + path.strip("/")
            known = bool(
                re.fullmatch(
                    r"/(?:photos(?:/[^/]+)?|folders(?:/.*)?|favorites|duplicates|trash|activity|login)",
                    route,
                )
            )
            if (
                error.status_code == 404
                and scope["method"] in ("GET", "HEAD")
                and known
            ):
                return await super().get_response("index.html", scope)
            raise
