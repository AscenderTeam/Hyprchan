from __future__ import annotations

TOOL_TWITTER_POST = "twitter_post"
TOOL_TWITTER_REPLY = "twitter_reply"
TOOL_TWITTER_REPOST = "twitter_repost"

HYPRX_REQUIRED_ENV = (
    "HYPRX_API_KEY",
    "HYPRX_API_SECRET",
    "HYPRX_ACCESS_TOKEN",
    "HYPRX_ACCESS_TOKEN_SECRET",
)

# During stranger-mention cycles we keep only twitter_reply available.
HYPRX_REPLY_ONLY_TOOLSET = {TOOL_TWITTER_REPLY}
