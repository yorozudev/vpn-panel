import os
import re
from urllib.parse import quote


def build_content_disposition(username: str) -> str:
    """Build RFC 5987 compatible Content-Disposition with ASCII fallback and UTF-8 filename*."""
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", username or "profile")
    utf8_quoted = quote(username or "profile", safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8{{utf8_quoted}}'


def get_routing_header(user_agent: str, settings: dict) -> dict:
    """Build optional routing header for Happ/v2raytun/Incy clients.

    Incy reads the same `Routing` header as Happ and expects an
    `incy://routing/onadd/...` deeplink as its value.
    """
    routing_value = ""
    if re.search(r"v2raytun", user_agent or "", re.IGNORECASE):
        routing_value = str(settings.get("sub_routing_v2raytun") or "").strip()
    elif re.search(r"\bincy(?:/|\b)", user_agent or "", re.IGNORECASE):
        # Значение: настройка панели sub_routing_incy, либо переменная окружения INCY_ROUTING
        routing_value = str(
            settings.get("sub_routing_incy") or os.environ.get("INCY_ROUTING", "")
        ).strip()
    elif re.search(r"\bhapp(?:/|\b)", user_agent or "", re.IGNORECASE):
        routing_value = str(settings.get("sub_routing_happ") or "").strip()

    return {"routing": routing_value} if routing_value else {}
