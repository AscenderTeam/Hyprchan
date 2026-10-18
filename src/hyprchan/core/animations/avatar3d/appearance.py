"""Persistent presentation choice, independent of GTK and the GL renderer."""
import json

OUTFITS = {'hoodie': '3D · turquoise hoodie',
           'cyan_yellow': '3D · cyan & yellow atelier'}


def read_appearance(path):
    try:
        saved = json.loads(path.read_text())
        if not isinstance(saved, dict): return 'pixel', 'hoodie'
    except (OSError, ValueError):
        return 'pixel', 'hoodie'
    mode = saved.get('mode', 'pixel')
    outfit = saved.get('outfit', 'hoodie')
    return (mode if mode in ('pixel', '3d') else 'pixel',
            outfit if isinstance(outfit, str) and outfit in OUTFITS else 'hoodie')


def save_appearance(path, mode, outfit):
    if mode not in ('pixel', '3d') or not isinstance(outfit, str) or outfit not in OUTFITS:
        raise ValueError('Unknown avatar appearance')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'mode': mode, 'outfit': outfit})+'\n')
    temporary.replace(path)
