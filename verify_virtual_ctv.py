    # Pixel proof: most pixels inside the (shrunk) quad are red-dominant.
    # The digital-twin "DIGITAL TWIN" watermark badge is intentionally centered
    # over this strip, so ALL badge pixels are EXCLUDED from the count — both
    # the cyan/teal text & border and the dark translucent pill background — so
    # we verify the strip is red in the region the badge does not cover.
    shrunk = _shrink(quad, 0.55)
    xs = [p[0] for p in shrunk]
    ys = [p[1] for p in shrunk]
    wm_r, wm_g, wm_b = WATERMARK_COLOR
    hits = total = 0
    for py in range(int(min(ys)), int(max(ys)) + 1):
        for px in range(int(min(xs)), int(max(xs)) + 1):
            if not _point_in_quad(px, py, shrunk):
                continue
            r, g, b = img.getpixel((px, py))
            # Skip cyan/teal badge text & border pixels.
            if abs(r - wm_r) <= 40 and abs(g - wm_g) <= 40 and abs(b - wm_b) <= 40:
                continue
            # Skip the badge's dark translucent pill background.
            if r < 45 and g < 45 and b < 45:
                continue
            total += 1
            if r > 70 and r > 1.5 * g and r > 1.5 * b:
                hits += 1
    assert total > 50, f"strip quad too small to sample: {total}"
    assert hits / total > 0.5, \
        f"strip not red inside its quad: {hits}/{total}"