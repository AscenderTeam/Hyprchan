from gi.repository import GdkPixbuf


def _infer_axis_size(
    sums: list[int],
    total: int,
    *,
    min_size: int,
    max_size: int,
    min_frames: int,
) -> int | None:
    if total < min_size:
        return None

    upper = min(max_size, total)
    candidates = [
        size
        for size in range(min_size, upper + 1)
        if total % size == 0 and (total // size) >= min_frames
    ]
    if not candidates:
        return None

    prefix = [0] * (total + 1)
    for i, v in enumerate(sums):
        prefix[i + 1] = prefix[i] + v

    best_score: float | None = None
    best_size: int | None = None
    for size in candidates:
        frames = total // size
        frame_sums = [
            prefix[(i + 1) * size] - prefix[i * size] for i in range(frames)
        ]
        mean = sum(frame_sums) / frames
        if mean <= 0:
            continue
        var = sum((s - mean) ** 2 for s in frame_sums) / frames
        score = var / mean
        if best_score is None or score < best_score:
            best_score = score
            best_size = size
        elif best_score is not None and score == best_score and best_size is not None:
            # Prefer larger frames when scores tie.
            best_size = max(best_size, size)

    return best_size


def _infer_frame_size_from_pixbuf(
    full_sheet: GdkPixbuf.Pixbuf,
    file_path: str,
    *,
    frames: int | None = None,
    rows: int | None = None,
    min_frame_size: int = 16,
    max_frame_size: int = 512,
    min_frames: int = 6,
) -> tuple[int, int]:
    sheet_width = full_sheet.get_width()
    sheet_height = full_sheet.get_height()

    if frames is not None:
        if frames <= 0 or sheet_width % frames != 0:
            raise ValueError(
                f"Invalid frames count {frames} for sheet {file_path} ({sheet_width}px)."
            )
        frame_width = sheet_width // frames
    else:
        pixels = full_sheet.get_pixels()
        rowstride = full_sheet.get_rowstride()
        n_channels = full_sheet.get_n_channels()
        has_alpha = full_sheet.get_has_alpha()
        alpha_offset = n_channels - 1

        data = memoryview(pixels)
        col_sums = [0] * sheet_width

        for y in range(sheet_height):
            row_start = y * rowstride
            for x in range(sheet_width):
                if has_alpha:
                    alpha = data[row_start + x * n_channels + alpha_offset]
                else:
                    alpha = 255
                col_sums[x] += alpha

        frame_width = _infer_axis_size(
            col_sums,
            sheet_width,
            min_size=min_frame_size,
            max_size=max_frame_size,
            min_frames=min_frames,
        )

        if frame_width is None:
            raise ValueError(
                f"Unable to infer frame width for {file_path}. "
                "Pass frame_width or frames explicitly."
            )

        if rows is not None:
            if rows <= 0 or sheet_height % rows != 0:
                raise ValueError(
                    f"Invalid rows count {rows} for sheet {file_path} ({sheet_height}px)."
                )
            frame_height = sheet_height // rows
        else:
            frame_height = sheet_height

        return frame_width, frame_height

    if rows is not None:
        if rows <= 0 or sheet_height % rows != 0:
            raise ValueError(
                f"Invalid rows count {rows} for sheet {file_path} ({sheet_height}px)."
            )
        frame_height = sheet_height // rows
    else:
        frame_height = sheet_height

    return frame_width, frame_height


def infer_frame_size(
    file_path: str,
    *,
    frames: int | None = None,
    rows: int | None = None,
    min_frame_size: int = 16,
    max_frame_size: int = 512,
    min_frames: int = 6,
) -> tuple[int, int]:
    full_sheet = GdkPixbuf.Pixbuf.new_from_file(file_path)

    if not full_sheet:
        raise Exception("Failed to load sprite sheet")

    return _infer_frame_size_from_pixbuf(
        full_sheet,
        file_path,
        frames=frames,
        rows=rows,
        min_frame_size=min_frame_size,
        max_frame_size=max_frame_size,
        min_frames=min_frames,
    )


def load_animation_frames(
    file_path: str,
    frame_width: int | None = None,
    frame_height: int | None = None,
    *,
    frames: int | None = None,
    rows: int | None = None,
    min_frame_size: int = 16,
    max_frame_size: int = 512,
    min_frames: int = 6,
):
    # Load the full spritesheet
    full_sheet = GdkPixbuf.Pixbuf.new_from_file(file_path)

    if not full_sheet:
        raise Exception("Failed to load sprite sheet")

    sheet_width = full_sheet.get_width()
    sheet_height = full_sheet.get_height()

    if frame_width is None or frame_height is None:
        inferred_width, inferred_height = _infer_frame_size_from_pixbuf(
            full_sheet,
            file_path,
            frames=frames,
            rows=rows,
            min_frame_size=min_frame_size,
            max_frame_size=max_frame_size,
            min_frames=min_frames,
        )
        frame_width = frame_width or inferred_width
        frame_height = frame_height or inferred_height
    assert frame_width is not None
    assert frame_height is not None

    if sheet_width < frame_width or sheet_height < frame_height:
        raise ValueError(
            f"Sprite sheet {file_path} is smaller than a single frame "
            f"({sheet_width}x{sheet_height} vs {frame_width}x{frame_height})."
        )

    if sheet_width % frame_width != 0 or sheet_height % frame_height != 0:
        raise ValueError(
            f"Sprite sheet {file_path} size ({sheet_width}x{sheet_height}) is not "
            f"an even multiple of frame size ({frame_width}x{frame_height}). "
            "Adjust frame dimensions or use a tightly packed sheet with no padding."
        )

    frame_list: list[GdkPixbuf.Pixbuf] = []

    cols = sheet_width // frame_width
    rows = sheet_height // frame_height

    # Iterate through the grid (row-major)
    for y in range(0, rows * frame_height, frame_height):
        for x in range(0, cols * frame_width, frame_width):
            # Create a "view" of the specific frame
            # new_subpixbuf(src, x, y, width, height)
            frame = full_sheet.new_subpixbuf(x, y, frame_width, frame_height)
            frame_list.append(frame)

    return frame_list
