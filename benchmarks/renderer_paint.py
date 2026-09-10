"""Production GPU paint checks against analytic/CPU fields, not prior pixels."""
import argparse
import json
from pathlib import Path
import numpy as np

from maniml.mobject.geometry import Square
from maniml.web.fill_paint import build_paint, evaluate_paint
from maniml.web.geometry import GeometryCache, serialize_scene, parse_geometry_message
from maniml.web.wgpu_renderer import WgpuRenderer
from tests.renderer_fixtures import build_scene, get_fixture


FIELDS = ('point', 'fill_rgba', 'fill_border_width', 'stroke_rgba', 'stroke_width')


def fingerprint(scene):
    return [tuple(obj.data[field].tobytes() for field in FIELDS)
            for obj in scene.mobjects]


def square():
    return Square(side_length=2, fill_opacity=.6, stroke_width=0, fill_border_width=12)


def affine(points):
    x, y = points[:, 0], points[:, 1]
    return np.column_stack([.4 + .15*x, .5 + .15*y, .6 - .1*x, .55 + .1*y])


def incoming_light(colors, points, light, normal, shading):
    direction = np.asarray(light, dtype=float) - points
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    cosine = direction @ normal
    # These independent probes set gloss=0, so the expected RGB is Lambert's
    # cosine diffuse brightening or the existing declared backside attenuation.
    rgb = colors[:, :3] + (1 - colors[:, :3]) * (np.maximum(cosine, 0) * shading[0])[:, None]
    rgb *= (1 - np.maximum(-cosine, 0) * shading[2])[:, None]
    return np.column_stack([rgb, colors[:, 3]])


def probe_case(renderer, name, scene, field, scope, output, report):
    before = fingerprint(scene)
    header, raw = parse_geometry_message(serialize_scene(scene, GeometryCache(), renderer='triangles'))
    assert any(batch['pipeline'].startswith('paint') for batch in header['batches'])
    scene.camera.refresh_uniforms()
    width, height = header['resolution']
    # Select interior pixel centers; scene cameras are centered and unrotated.
    xs, ys = np.meshgrid(np.arange(width), np.arange(height))
    xx = (2 * (xs + .5) / width - 1) * scene.camera.frame.get_width() / 2
    yy = -(2 * (ys + .5) / height - 1) * scene.camera.frame.get_height() / 2
    selection = (np.abs(xx) < .68) & (np.abs(yy) < .68)
    points = np.column_stack([xx[selection], yy[selection], np.zeros(selection.sum())])
    color = np.clip(field(points), 0, 1)
    bg = np.asarray(scene.camera.background_rgba)
    alpha = color[:, 3:4] + bg[3] * (1 - color[:, 3:4])
    expected = np.column_stack([color[:, :3]*color[:, 3:4] + bg[:3]*bg[3]*(1-color[:, 3:4]), alpha]) * 255
    values = {}
    for policy, scale, samples in [('pixel_center', 1, 1), ('ss2_msaa4', 2, 4)]:
        current = dict(header, supersample=scale, samples=samples)
        picture = renderer.render(current, raw)
        actual = np.asarray(picture, dtype=float)[selection]
        error = np.abs(actual - expected)
        values[policy] = {'probe_pixels': int(selection.sum()),
                          'max_rgb_error_255': float(error[:, :3].max()),
                          'mean_rgb_error_255': float(error[:, :3].mean()),
                          'max_alpha_error_255': float(error[:, 3].max()),
                          'passed': bool(error.max() <= 1.5)}
        if policy == 'ss2_msaa4':
            picture.save(output/(name+'.png'))
    assert fingerprint(scene) == before, 'source point/style bytes changed'
    report['cases'][name] = {'oracle': scope, 'policies': values,
        'coverage_draws': sum(bool(b.get('coverage')) for b in header['batches']),
        'source_contract_preserved': True}
    print(name, json.dumps(values), flush=True)



def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = {'route': "serialize_scene(renderer='triangles') -> WgpuRenderer.render",
              'scope': 'Interior paint and source-over; boundary AA is checked by renderer_aa.',
              'cases': {}}
    renderer = WgpuRenderer()
    try:
        obj = square()
        obj.data['fill_rgba'][:] = affine(obj.get_points())
        scene = build_scene(obj, resolution=(192, 128), samples=4)
        scene.camera.frame.set_height(3)
        probe_case(renderer, 'affine_rgba', scene, affine,
                   'Analytic affine RGBA field followed by one premultiplied source-over; independent of tessellation and CPU spline evaluator.', output, report)

        gradient = get_fixture('gradient_curve').build()
        gradient.camera.frame.set_height(3)
        obj = gradient.mobjects[0]
        paint = build_paint(obj.get_points(), obj.data['fill_rgba'])
        probe_case(renderer, 'gradient_curve', gradient,
                   lambda p: evaluate_paint(paint, p),
                   'Existing nonlinear gradient fixture; shader field compared against the production CPU field evaluator. This is CPU/GPU agreement, not an independent interior semantic oracle.', output, report)

        for name, light in [('diffuse_front', [0, 0, 10]), ('shadow_back', [0, 0, -10])]:
            obj = square()
            obj.set_fill(color='#3377AA', opacity=.6)
            obj.uniforms['shading'] = [.4, 0, .6]
            scene = build_scene(obj, resolution=(192, 128), samples=4)
            scene.camera.frame.set_height(3)
            scene.camera.light_source.move_to(light)
            rgba = obj.data['fill_rgba'][0].copy()
            probe_case(renderer, name, scene,
                lambda p, rgba=rgba, light=light: incoming_light(np.tile(rgba, (len(p), 1)), p, light,
                                                               np.array([0, 0, 1]), [.4, 0, .6]),
                'Analytic cosine diffuse/backside attenuation at each pixel center; uniform source paint and zero gloss.', output, report)
    finally:
        renderer.close()
    report['passed'] = all(policy['passed'] for case in report['cases'].values() for policy in case['policies'].values())
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not run(args.output)['passed']:
        raise SystemExit('Paint probe acceptance failed; inspect report.json')


if __name__ == '__main__':
    main()
