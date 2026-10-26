"""Talkative's colors, in one place: the Settings window (both themes),
its header band and the listening line all read from here.

PALETTES holds the three schemes shown to the user on 2026-10-26 after
the first restyle read as "the generic AI look" (indigo/violet/pink,
Linear's #5E6AD2 territory). Each is inspired by a different product
direction, not copied from it. The user chose to let people pick one:
config.COLOR_SCHEME, Settings > General > Appearance. Every text/
background pair is checked for at least 4.5:1 contrast
(tools/e2e/palette_contrast_test.py).
"""

PALETTES = {
    # Warm editorial: cream paper, ink, deep forest green (in the spirit
    # of Wispr Flow's site), an orange listening line.
    "forest": {
        "label": "Forest",
        "light": dict(bg="#fbf8ee", fg="#1a1a1a", field="#ffffff", raised="#ece5d3",
                      border="#c2b99f", hover="#e0d7c0", title="#034f46", muted="#55513f"),
        "dark": dict(bg="#0f1f1c", fg="#f1eedf", field="#172a26", raised="#1f3530",
                     border="#3b574f", hover="#29443d", title="#93d4bf", muted="#b3bdb2"),
        "accent": "#035c51", "accent_fg": "#ffffff", "accent_hover": "#023f37",
        "header": ("#034f46", "#0b6b5c"), "header_fg": "#fbf8ee",
        "line": "#ff9f43", "line_halo": "#12221f",
    },
    # Graphite and coral (in the spirit of Raycast): near-black, one
    # warm red accent and line.
    "coral": {
        "label": "Coral",
        "light": dict(bg="#f6f6f7", fg="#16181d", field="#ffffff", raised="#e6e7ea",
                      border="#b6b9c1", hover="#d8dadf", title="#b42f29", muted="#4d515b"),
        "dark": dict(bg="#15171c", fg="#ececef", field="#1d2027", raised="#262a33",
                     border="#3e4350", hover="#30353f", title="#ff8f86", muted="#a9adb7"),
        "accent": "#c9342d", "accent_fg": "#ffffff", "accent_hover": "#a92a24",
        "header": ("#1b1d23", "#2a2d36"), "header_fg": "#ffffff",
        "line": "#ff6363", "line_halo": "#15171c",
    },
    # Calm teal on slate, a teal line.
    "teal": {
        "label": "Teal",
        "light": dict(bg="#f3f7f7", fg="#132022", field="#ffffff", raised="#e0eaea",
                      border="#adc2c2", hover="#d0dfdf", title="#0a6661", muted="#465a5b"),
        "dark": dict(bg="#0f191b", fg="#e6f0ef", field="#162325", raised="#1e2f31",
                     border="#385255", hover="#283d40", title="#6fd9cc", muted="#a5b9b8"),
        "accent": "#0b6f69", "accent_fg": "#ffffff", "accent_hover": "#08544f",
        "header": ("#0b5f5a", "#13807a"), "header_fg": "#ffffff",
        "line": "#2dd4bf", "line_halo": "#0f191b",
    },
}

DEFAULT = "forest"


def get():
    """The chosen scheme; an unknown name (hand-edited settings.json)
    falls back to the default."""
    from . import config
    return PALETTES.get(config.COLOR_SCHEME, PALETTES[DEFAULT])
