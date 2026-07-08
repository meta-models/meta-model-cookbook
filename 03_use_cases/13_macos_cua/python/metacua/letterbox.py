"""Pure aspect-fit / letterbox geometry for pyautogui screenshot mode."""

from dataclasses import dataclass


@dataclass
class LetterboxFit:
    scale: float
    ox: int
    oy: int
    drawn_w: int
    drawn_h: int


def fit_transform(screen_w: int, screen_h: int, model_w: int, model_h: int) -> LetterboxFit:
    sw = max(1, int(screen_w))
    sh = max(1, int(screen_h))
    mw = max(1, int(model_w))
    mh = max(1, int(model_h))
    scale = min(float(mw) / float(sw), float(mh) / float(sh))
    drawn_w = max(1, int(round(float(sw) * scale)))
    drawn_h = max(1, int(round(float(sh) * scale)))
    ox = (mw - drawn_w) // 2
    oy = (mh - drawn_h) // 2
    return LetterboxFit(scale=scale, ox=ox, oy=oy, drawn_w=drawn_w, drawn_h=drawn_h)


def inverse_fit_point(model_x: float, model_y: float, screen_w: int, screen_h: int,
                      model_w: int, model_h: int):
    fit = fit_transform(screen_w, screen_h, model_w, model_h)
    x = (float(model_x) - fit.ox) / fit.scale
    y = (float(model_y) - fit.oy) / fit.scale
    if screen_w > 0:
        x = min(max(0.0, x), float(screen_w - 1))
    if screen_h > 0:
        y = min(max(0.0, y), float(screen_h - 1))
    return x, y
