"""Vector icon set in frosted silver. Every icon is a tiny SVG (24x24 grid, round stroke caps) drawn with a
silver gradient, rendered with QtSvg at the exact pixel sizes needed (so it is crisp at any DPI) and cached.

States: normal (silver), hover/checked (bright), disabled (dim). `icon(name)` returns a ready QIcon."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel

# Bodies are drawn with stroke="url(#s)" (set on the group); FILL marks the few solid shapes.
BODIES = {
    "chevron_left": '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    "chevron_right": '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
    "chevron_up": '<path d="M5.5 14.5 12 8l6.5 6.5"/>',
    "chevron_down": '<path d="M5.5 9.5 12 16l6.5-6.5"/>',
    "to_top": '<path d="M6.5 4.5h11"/><path d="M7 13.5 12 8.5l5 5"/><path d="M7 19.5l5-5 5 5"/>',
    "to_bottom": '<path d="M6.5 19.5h11"/><path d="M7 10.5l5 5 5-5"/><path d="M7 4.5l5 5 5-5"/>',
    "reload": '<path d="M20 12a8 8 0 1 1-2.35-5.65L20 8.5"/><path d="M20 3.5v5h-5"/>',
    "sidebar": '<rect x="3.5" y="4.5" width="17" height="15" rx="3.5"/><path d="M9.5 4.5v15"/>',
    "fullscreen": '<path d="M4 9V6a2 2 0 0 1 2-2h3"/><path d="M15 4h3a2 2 0 0 1 2 2v3"/>'
                  '<path d="M20 15v3a2 2 0 0 1-2 2h-3"/><path d="M9 20H6a2 2 0 0 1-2-2v-3"/>',
    "fullscreen_exit": '<path d="M9 4v3a2 2 0 0 1-2 2H4"/><path d="M20 9h-3a2 2 0 0 1-2-2V4"/>'
                       '<path d="M15 20v-3a2 2 0 0 1 2-2h3"/><path d="M4 15h3a2 2 0 0 1 2 2v3"/>',
    "zen": '<path d="M2.8 12S6.3 5.8 12 5.8 21.2 12 21.2 12 17.7 18.2 12 18.2 2.8 12 2.8 12Z"/><circle cx="12" cy="12" r="2.8"/>',
    "play": '<path d="M8.2 5.9v12.2a1 1 0 0 0 1.5.86l9.6-6.1a1 1 0 0 0 0-1.72L9.7 5.04A1 1 0 0 0 8.2 5.9Z" fill="FILL"/>',
    "pause": '<rect x="6.3" y="5" width="4" height="14" rx="1.4" fill="FILL"/>'
             '<rect x="13.7" y="5" width="4" height="14" rx="1.4" fill="FILL"/>',
    "volume": '<path d="M4 9.6h3l4.6-3.8v12.4L7 14.4H4Z"/><path d="M15.3 9.3a3.9 3.9 0 0 1 0 5.4"/>'
              '<path d="M18 6.7a7.6 7.6 0 0 1 0 10.6"/>',
    "text_smaller": '<path d="M3.5 19 8.7 6l5.2 13"/><path d="M5.5 14.6h6.4"/><path d="M16.5 9h5"/>',
    "text_larger": '<path d="M3.5 19 8.7 6l5.2 13"/><path d="M5.5 14.6h6.4"/><path d="M16.5 9h5"/><path d="M19 6.5v5"/>',
    "star": '<path d="M12 3.8l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8Z"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2.2h7.2a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>',
    "folder_open": '<path d="M3.5 17.3V7.5a2 2 0 0 1 2-2h3.8l2 2.2h5.2a2 2 0 0 1 2 2v1.3"/>'
                   '<path d="M3.7 17.8 6 11.9a2 2 0 0 1 1.9-1.3h12a1.2 1.2 0 0 1 1.1 1.7l-2.1 5.6a2 2 0 0 1-1.9 1.3H5.4a1.7 1.7 0 0 1-1.7-1.4Z"/>',
    "folder_plus": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2.2h7.2a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>'
                   '<path d="M12 10.8v5M9.5 13.3h5"/>',
    # preset kinds
    "globe": '<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/>'
             '<path d="M12 3.4c2.5 2.3 3.7 5.1 3.7 8.6s-1.2 6.3-3.7 8.6c-2.5-2.3-3.7-5.1-3.7-8.6S9.5 5.7 12 3.4Z"/>',
    "pdf": '<path d="M7 3.5h6.6l4.9 4.9V19a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5Z"/>'
           '<path d="M13.5 3.8v4.7h4.7"/><rect x="8.3" y="12.6" width="7.4" height="4.6" rx="1.2"/>',
    "text": '<path d="M7 3.5h6.6l4.9 4.9V19a1.5 1.5 0 0 1-1.5 1.5H7A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5Z"/>'
            '<path d="M13.5 3.8v4.7h4.7"/><path d="M8.5 13h7M8.5 16.5h4.5"/>',
    "video": '<rect x="3.5" y="5.5" width="17" height="13" rx="3.2"/>'
             '<path d="M10.3 9.5v5l4.2-2.5Z" fill="FILL" stroke-width="1.2"/>',
    "scene": '<rect x="3.5" y="4.5" width="17" height="15" rx="3.2"/><circle cx="9" cy="9.8" r="1.6"/>'
             '<path d="M4 17.2l4.8-4.3 3.4 3 3.2-2.7 5.1 4.2"/>',
}

# (top, bottom, opacity) of the silver gradient for each state
STYLES = {
    "normal": ("#f3f5f9", "#a7afbd", 1.0),
    "active": ("#ffffff", "#d6dce7", 1.0),
    "disabled": ("#a7afbd", "#868e9c", 0.38),
}
SIZES = (18, 24, 36, 54)             # rendered natively for 100% / 125% / 150-200% scaling; Qt picks the closest

_TEMPLATE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
             '<defs><linearGradient id="s" gradientUnits="userSpaceOnUse" x1="0" y1="3" x2="0" y2="21">'
             '<stop offset="0" stop-color="@1"/><stop offset="1" stop-color="@2"/></linearGradient></defs>'
             '<g opacity="@O" fill="none" stroke="url(#s)" stroke-width="1.8" stroke-linecap="round" '
             'stroke-linejoin="round">@B</g></svg>')


def svg(name: str, style: str = "normal") -> str:
    top, bot, op = STYLES[style]
    return (_TEMPLATE.replace("@1", top).replace("@2", bot).replace("@O", str(op))
            .replace("@B", BODIES[name].replace("FILL", "url(#s)")))


def _pixmap(renderer: QSvgRenderer, px: int) -> QPixmap:
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return pm


_CACHE: dict = {}


def icon(name: str) -> QIcon:
    ic = _CACHE.get(name)
    if ic is None:
        ic = QIcon()
        # the SVG is parsed once per state and rendered at every size (parsing, not drawing, is the costly part)
        renderers = {s: QSvgRenderer(QByteArray(svg(name, s).encode())) for s in ("normal", "active", "disabled")}
        for px in SIZES:
            normal, bright, dim = (_pixmap(renderers[s], px) for s in ("normal", "active", "disabled"))
            ic.addPixmap(normal, QIcon.Normal, QIcon.Off)
            ic.addPixmap(bright, QIcon.Active, QIcon.Off)       # hover
            ic.addPixmap(bright, QIcon.Normal, QIcon.On)        # checked
            ic.addPixmap(bright, QIcon.Active, QIcon.On)
            ic.addPixmap(dim, QIcon.Disabled, QIcon.Off)
            ic.addPixmap(dim, QIcon.Disabled, QIcon.On)
        _CACHE[name] = ic
    return ic


def label(name: str, size: int = 18) -> QLabel:
    """A QLabel that shows an icon (used where the UI had an emoji next to a slider)."""
    lb = QLabel()
    lb.setPixmap(icon(name).pixmap(size))
    return lb
