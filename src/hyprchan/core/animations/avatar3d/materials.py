"""Portrait art direction layered over the VRM's MToon material parameters.

Colors below are authored in sRGB and converted before lighting. The VRM's
outline mask is retained, so the face outline does not draw over eyes or lips.
"""
import numpy as np


def linear(rgb):
    values = np.asarray(rgb, dtype=np.float32)
    return np.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4)


def portrait_material(material):
    name = material['name']
    printed = name in {'Sunshine emblem', 'Hyprchan W'}
    source = material.get('extensions', {}).get('VRMC_materials_mtoon', {})
    kind = (1 if 'HAIR' in name else 2 if 'EyeIris' in name else
            3 if 'SKIN' in name else 4 if name.startswith('Hoodie') or printed else
            5 if 'FaceBrow' in name else 6 if 'FaceEyeline' in name else 0)
    result = dict(kind=kind, shift=source.get('shadingShiftFactor', 0),
                  toony=source.get('shadingToonyFactor', .9),
                  shade=source.get('shadeColorFactor', [1, 1, 1]),
                  rim=source.get('parametricRimColorFactor', [0, 0, 0]),
                  rim_power=source.get('parametricRimFresnelPowerFactor', 5),
                  outline=linear([.15, .17, .25]), width=0.)
    if kind == 1:
        result.update(shift=-.12, toony=.88, shade=linear([.48, .68, .85]),
                      rim=linear([.16, .44, .46]), outline=linear([.025, .22, .28]), width=.0014)
    elif kind == 3:
        result.update(shift=.2, toony=.75, shade=linear([.98, .79, .80]),
                      rim=linear([.10, .07, .08]), outline=linear([.43, .25, .28]), width=.00075)
    elif kind == 4:
        result.update(shift=-.13, toony=.88, shade=linear([.61, .68, .84]),
                      rim=linear([.14, .24, .30]), outline=linear([.21, .29, .39]), width=.0011)
        if printed:
            # Ink receives the fabric's lighting and cast shadows. It has no
            # separate silhouette: a hull would expose stroke triangulation.
            result['width'] = 0
    elif name.startswith('Sunshine'):
        result.update(shift=0, shade=linear([.80, .57, .28]),
                      outline=linear([.35, .25, .14]), width=.00055)
    else:
        # Eye whites, lashes and painted highlights should stay legible in shade.
        result.update(shift=.5, shade=linear([.95, .93, .97]))
    return result
