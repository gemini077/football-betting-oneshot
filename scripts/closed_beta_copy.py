"""Shared user-facing Closed Beta trust-boundary copy."""

from __future__ import annotations

import html


CLOSED_BETA_LABEL = "Closed Beta / \u6d4b\u8bd5\u9636\u6bb5"
CLOSED_BETA_PREDICTION_COPY = "\u9884\u6d4b\u4ec5\u4f9b\u6bd4\u8d5b\u5206\u6790\u4e0e\u7814\u7a76\u53c2\u8003\uff0c\u53ef\u80fd\u51fa\u9519\u3002"
CLOSED_BETA_TRANSACTION_COPY = "\u672c\u4ea7\u54c1\u4e0d\u63d0\u4f9b\u8d2d\u5f69\u3001\u4ee3\u8d2d\u3001\u6536\u6b3e\u3001\u4e0b\u6ce8\u6216\u51fa\u7968\u670d\u52a1\u3002\u4e5f\u4e0d\u63d0\u4f9b\u652f\u4ed8\u670d\u52a1\u3002"
CLOSED_BETA_RESPONSIBLE_USE_COPY = (
    "\u5982\u53c2\u4e0e\u5408\u6cd5\u5f69\u7968\u8d2d\u4e70\uff0c\u8bf7\u901a\u8fc7\u5408\u6cd5\u6b63\u89c4\u6e20\u9053\u5e76\u7406\u6027\u53c2\u4e0e\uff1b\u672a\u6210\u5e74\u4eba\u4e0d\u5f97\u8d2d\u4e70\u5f69\u7968\u3002"
)


def render_closed_beta_notice(css_class: str) -> str:
    """Render the compact trust boundary using the caller's existing surface style."""
    class_name = html.escape(css_class, quote=True)
    return (
        f'<aside class="{class_name} closed-beta-notice" '
        f'aria-label="{html.escape(CLOSED_BETA_LABEL, quote=True)}">'
        f"<strong>{html.escape(CLOSED_BETA_LABEL)}</strong>"
        f"<span>{html.escape(CLOSED_BETA_PREDICTION_COPY)}</span>"
        f"<span>{html.escape(CLOSED_BETA_TRANSACTION_COPY)}</span>"
        f"<span>{html.escape(CLOSED_BETA_RESPONSIBLE_USE_COPY)}</span>"
        "</aside>"
    )
