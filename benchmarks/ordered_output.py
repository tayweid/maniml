"""A0 control: prepare separate winding targets, then replay ordered output.

This intentionally changes no geometry or shader semantics. Unlike production's
scratch pool, each prepared fill keeps its own texture until output completes.
It is a comparison control, not an atlas or a production renderer.
"""

from time import perf_counter

from PIL import Image
import wgpu

from maniml.web.wgpu_renderer import WgpuRenderer


class _RecordedPass:
    def __init__(self):
        self.commands = []

    def __getattr__(self, name):
        if name not in {"set_viewport", "set_scissor_rect", "set_pipeline", "set_bind_group",
                        "set_vertex_buffer", "set_index_buffer", "draw", "draw_indexed"}:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.commands.append((name, args, kwargs))

    def end(self):
        pass


class OrderedOutputControl(WgpuRenderer):
    def __init__(self):
        super().__init__()
        self._recorded = []
        self._fill_slot = 0

    def _out_pass(self, encoder, clear_color=None):
        if clear_color is not None:
            raise ValueError("clear belongs to the single replay pass")
        result = _RecordedPass()
        self._recorded.append(result)
        return result

    def _fill_target(self, width, height):
        size = tuple(min(2 * limit, 1 << (2 * extent - 1).bit_length())
                     for extent, limit in zip((width, height), self._size[0]))
        key = (self._fill_slot, size)
        self._fill_slot += 1
        self._fill_targets_used.add(key)
        if key not in self._fill_targets:
            texture = self.device.create_texture(
                size=(*size, 1), format="rgba16float",
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING)
            self._fill_targets[key] = {"texture": texture, "view": texture.create_view(),
                                       "size": size}
        return self._fill_targets[key]

    def frame(self, header, data, *, image=False):
        if header.get("texture_data") or any(batch.get("textures") for batch in header["batches"]):
            raise ValueError("A0 ordered-output control has not integrated textured materials")
        resolution = tuple(header["resolution"])
        samples = 4 if header.get("samples") else 1
        self._ensure_targets(resolution, samples)
        self._fill_targets_used.clear()
        self._recorded = []
        self._fill_slot = 0
        started = perf_counter()
        encoder = self.device.create_command_encoder()
        for batch in header["batches"]:
            encode = self._encode_vmobject if batch["kind"] == "vmobject" else self._encode_plain
            encode(encoder, header, batch, data, samples)
        render_pass = super()._out_pass(encoder, header["background"])
        draw_count = 0
        for recorded in self._recorded:
            # A fresh pass previously reset both; composites restrict them.
            render_pass.set_viewport(0, 0, *resolution, 0, 1)
            render_pass.set_scissor_rect(0, 0, *resolution)
            for name, args, kwargs in recorded.commands:
                getattr(render_pass, name)(*args, **kwargs)
                draw_count += int(name in ("draw", "draw_indexed"))
        render_pass.end()
        command = encoder.finish()
        encoded = perf_counter()
        self.device.queue.submit([command])
        texture = self.resolve_texture or self.out_texture
        self.device.queue.read_texture(
            {"texture": texture, "origin": (0, 0, 0)},
            {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
        completed = perf_counter()
        picture = None
        if image:
            raw = self.device.queue.read_texture(
                {"texture": texture, "origin": (0, 0, 0)},
                {"offset": 0, "bytes_per_row": 4 * resolution[0], "rows_per_image": resolution[1]},
                (*resolution, 1))
            picture = Image.frombytes("RGBA", resolution, bytes(raw))
        for key in self._fill_targets.keys() - self._fill_targets_used:
            self._fill_targets.pop(key)["texture"].destroy()
        # Unlike the production snapshot cache, this harness retains no history
        # of geometry across morph frames. Completion makes retirement safe.
        used_batches = {batch["hash"] for batch in header["batches"]}
        for key in self.batch_cache.keys() - used_batches:
            for value in self.batch_cache.pop(key).values():
                if isinstance(value, wgpu.GPUBuffer):
                    value.destroy()
        self._recorded = []
        return picture, {
            "encode_ms": 1000 * (encoded - started),
            "submit_through_completion_ms": 1000 * (completed - encoded),
            "total_ms": 1000 * (completed - started),
            "passes": self._fill_slot + 1,
            "draws": self._fill_slot * 2 + draw_count,
            "retained_fill_target_bytes": sum(8 * target["size"][0] * target["size"][1]
                                               for target in self._fill_targets.values()),
        }

    def render(self, header, data):
        return self.frame(header, data, image=True)[0]
