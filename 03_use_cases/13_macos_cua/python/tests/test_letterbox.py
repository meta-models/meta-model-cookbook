from metacua.letterbox import fit_transform, inverse_fit_point


def test_fit_transform_16_10_macbook_sizes_into_16_9_model():
    fit = fit_transform(1728, 1117, 1920, 1080)
    assert round(fit.scale, 6) == round(1080 / 1117.0, 6)
    assert fit.drawn_h == 1080
    assert fit.drawn_w == 1671
    assert fit.ox == 124
    assert fit.oy == 0

    fit = fit_transform(1512, 982, 1920, 1080)
    assert round(fit.scale, 6) == round(1080 / 982.0, 6)
    assert fit.drawn_h == 1080
    assert fit.drawn_w == 1663
    assert fit.ox == 128
    assert fit.oy == 0


def test_fit_transform_16_9_pass_through():
    fit = fit_transform(1920, 1080, 1920, 1080)
    assert fit.scale == 1.0
    assert fit.drawn_w == 1920
    assert fit.drawn_h == 1080
    assert fit.ox == 0
    assert fit.oy == 0


def test_inverse_mapping_round_trips_corners_and_center():
    screen_w, screen_h = 1728, 1117
    model_w, model_h = 1920, 1080
    fit = fit_transform(screen_w, screen_h, model_w, model_h)

    x, y = inverse_fit_point(fit.ox, fit.oy, screen_w, screen_h, model_w, model_h)
    assert (round(x), round(y)) == (0, 0)

    x, y = inverse_fit_point(
        fit.ox + fit.drawn_w, fit.oy + fit.drawn_h, screen_w, screen_h, model_w, model_h
    )
    assert (round(x), round(y)) == (screen_w - 1, screen_h - 1)

    x, y = inverse_fit_point(
        fit.ox + fit.drawn_w / 2.0,
        fit.oy + fit.drawn_h / 2.0,
        screen_w,
        screen_h,
        model_w,
        model_h,
    )
    assert round(x) == round(screen_w / 2.0)
    assert round(y) == round(screen_h / 2.0)


def test_inverse_mapping_clamps_bar_coordinates():
    screen_w, screen_h = 1728, 1117
    model_w, model_h = 1920, 1080
    x, y = inverse_fit_point(0, 100, screen_w, screen_h, model_w, model_h)
    assert x == 0
    assert 0 <= y <= screen_h - 1

    x, y = inverse_fit_point(model_w - 1, 100, screen_w, screen_h, model_w, model_h)
    assert x == screen_w - 1
    assert 0 <= y <= screen_h - 1
