from gi.repository import GdkPixbuf


def load_animation_frames(file_path: str, frame_width: int, frame_height: int):
    # Load the full spritesheet
    full_sheet = GdkPixbuf.Pixbuf.new_from_file(file_path)

    if not full_sheet:
        raise Exception("Failed to load sprite sheet")

    sheet_width = full_sheet.get_width()
    sheet_height = full_sheet.get_height()

    frames = []

    # Iterate through the grid (assuming horizontal for your file)
    for x in range(0, sheet_width, frame_width):
        # Create a "view" of the specific frame
        # new_subpixbuf(src, x, y, width, height)
        frame = full_sheet.new_subpixbuf(x, 0, frame_width, frame_height)
        frames.append(frame)

    return frames
