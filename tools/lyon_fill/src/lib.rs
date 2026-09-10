//! Small, versioned C ABI for the isolated CPU fill experiment.
//!
//! Only the Python adapter calls this ABI. It is not a sandbox for untrusted
//! native pointers. Output ownership belongs to Rust until ml_lyon_free.

use lyon_tessellation::geometry_builder::{FillGeometryBuilder, GeometryBuilder, StrokeGeometryBuilder};
use lyon_tessellation::math::point;
use lyon_tessellation::path::Path;
use lyon_tessellation::{
    FillOptions, FillRule, FillTessellator, FillVertex, GeometryBuilderError, LineJoin,
    StrokeOptions, StrokeTessellator, StrokeVertex, VertexId,
};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::{ptr, slice};

const MAX_SOURCE_POINTS: usize = 65_536;
const MAX_ATTRIBUTES: usize = 32;
const MAX_VERTICES: usize = 1_048_576;
const MAX_INDICES: usize = 6_291_456;
// Conservative subdivision-work gate, before Lyon builds its flattened event
// queue. This is not a total-memory cap on Lyon's internal intersection sweep.
const MAX_FLATTENED_SEGMENTS: usize = 262_144;

#[repr(C)]
pub struct MeshResult {
    // Each row is x, y, followed by attribute_count values.
    pub vertices: *mut f32,
    pub vertex_floats: usize,
    pub indices: *mut u32,
    pub index_count: usize,
}

impl Default for MeshResult {
    fn default() -> Self {
        Self { vertices: ptr::null_mut(), vertex_floats: 0,
            indices: ptr::null_mut(), index_count: 0 }
    }
}

struct BoundedMesh {
    vertices: Vec<f32>,
    indices: Vec<u32>,
    attributes: usize,
    max_vertices: usize,
    max_indices: usize,
    overflow: bool,
}

impl GeometryBuilder for BoundedMesh {
    fn begin_geometry(&mut self) {}

    fn add_triangle(&mut self, a: VertexId, b: VertexId, c: VertexId) {
        if self.indices.len() + 3 > self.max_indices {
            self.overflow = true;
            return;
        }
        self.indices.extend([a.0, b.0, c.0]);
    }

    fn abort_geometry(&mut self) {
        self.vertices.clear();
        self.indices.clear();
    }
}

impl FillGeometryBuilder for BoundedMesh {
    fn add_fill_vertex(&mut self, mut vertex: FillVertex) -> Result<VertexId, GeometryBuilderError> {
        let count = self.vertices.len() / (2 + self.attributes);
        if count >= self.max_vertices {
            self.overflow = true;
            return Err(GeometryBuilderError::TooManyVertices);
        }
        let p = vertex.position();
        self.vertices.extend([p.x, p.y]);
        if self.attributes > 0 {
            self.vertices.extend_from_slice(vertex.interpolated_attributes());
        }
        Ok(VertexId(count as u32))
    }
}

impl StrokeGeometryBuilder for BoundedMesh {
    fn add_stroke_vertex(&mut self, mut vertex: StrokeVertex) -> Result<VertexId, GeometryBuilderError> {
        let count = self.vertices.len() / (2 + self.attributes);
        if count >= self.max_vertices {
            self.overflow = true;
            return Err(GeometryBuilderError::TooManyVertices);
        }
        let p = vertex.position();
        self.vertices.extend([p.x, p.y]);
        if self.attributes > 0 {
            self.vertices.extend_from_slice(vertex.interpolated_attributes());
        }
        Ok(VertexId(count as u32))
    }
}

#[no_mangle]
pub extern "C" fn ml_lyon_abi_version() -> u32 { 1 }

/// Return 0 success, 1 invalid input, 2 output limit, 3 tessellation failure,
/// 4 caught panic. On every failure `output` is empty; partial meshes never escape.
///
/// # Safety
/// Input pointers must address the specified number of elements and output
/// must point to writable, unowned MeshResult storage. Arrays cannot alias it.
#[no_mangle]
pub unsafe extern "C" fn ml_lyon_tessellate(
    xy: *const f32, point_count: usize,
    contour_ends: *const u32, contour_count: usize,
    attributes: *const f32, attribute_count: usize,
    tolerance: f32, fill_rule: u32,
    max_vertices: usize, max_indices: usize,
    output: *mut MeshResult,
) -> u32 {
    tessellate_impl(xy, point_count, contour_ends, contour_count, attributes,
        attribute_count, tolerance, fill_rule, 0.0, 0, 4.0,
        max_vertices, max_indices, output)
}

/// Add a uniform closed-path border, then resolve fill and stroke overlap to
/// one nonzero mesh. Join codes: 0 bevel, 1 miter, 2 round. This is not Manim's
/// angle-dependent auto join or its smooth antialiasing coverage ramp.
///
/// # Safety
/// The same pointer and ownership requirements as ml_lyon_tessellate apply.
#[no_mangle]
pub unsafe extern "C" fn ml_lyon_tessellate_border(
    xy: *const f32, point_count: usize,
    contour_ends: *const u32, contour_count: usize,
    attributes: *const f32, attribute_count: usize,
    tolerance: f32, fill_rule: u32,
    border_width: f32, border_join: u32, border_miter_limit: f32,
    max_vertices: usize, max_indices: usize,
    output: *mut MeshResult,
) -> u32 {
    tessellate_impl(xy, point_count, contour_ends, contour_count, attributes,
        attribute_count, tolerance, fill_rule, border_width, border_join,
        border_miter_limit, max_vertices, max_indices, output)
}

unsafe fn tessellate_impl(
    xy: *const f32, point_count: usize,
    contour_ends: *const u32, contour_count: usize,
    attributes: *const f32, attribute_count: usize,
    tolerance: f32, fill_rule: u32,
    border_width: f32, border_join: u32, border_miter_limit: f32,
    max_vertices: usize, max_indices: usize,
    output: *mut MeshResult,
) -> u32 {
    if output.is_null() { return 1; }
    *output = MeshResult::default();
    if point_count > MAX_SOURCE_POINTS || attribute_count > MAX_ATTRIBUTES
        || max_vertices > MAX_VERTICES || max_indices > MAX_INDICES
        || !tolerance.is_finite() || tolerance <= 0.0 || fill_rule > 1
        || !border_width.is_finite() || border_width < 0.0 || border_join > 2
        || !border_miter_limit.is_finite() || border_miter_limit < 1.0
        || (point_count > 0 && xy.is_null())
        || (contour_count > 0 && contour_ends.is_null())
        || (attribute_count > 0 && point_count > 0 && attributes.is_null())
        || contour_count > point_count {
        return 1;
    }
    let outcome = catch_unwind(AssertUnwindSafe(|| -> Result<BoundedMesh, u32> {
        // Rust requires a non-null pointer even for a zero-length slice.
        let points = if point_count == 0 { &[] } else { slice::from_raw_parts(xy, point_count * 2) };
        let ends = if contour_count == 0 { &[] } else { slice::from_raw_parts(contour_ends, contour_count) };
        let attrs = if attribute_count == 0 || point_count == 0 { &[] }
            else { slice::from_raw_parts(attributes, point_count * attribute_count) };
        if points.iter().chain(attrs.iter()).any(|v| !v.is_finite()) { return Err(1); }
        let mut builder = Path::builder_with_attributes(attribute_count);
        let mut start = 0;
        let mut flattening_bound = 0usize;
        for &raw_end in ends {
            let end = raw_end as usize;
            if end <= start || end > point_count || (end - start) % 2 == 0 { return Err(1); }
            let attr = |i: usize| &attrs[i * attribute_count..(i + 1) * attribute_count];
            // A geometric union carries one paint field. Varying attributes
            // would need a separate, explicit field definition at overlaps.
            if border_width > 0.0 && (start..end).step_by(2)
                .any(|i| attr(i) != &attrs[..attribute_count]) { return Err(1); }
            builder.begin(point(points[2 * start], points[2 * start + 1]), attr(start));
            for i in ((start + 1)..end).step_by(2) {
                // For quadratic P, uniform n-way chord error is bounded by
                // |P0 - 2P1 + P2|/(4*n*n). Estimate in f64 to avoid overflowing
                // on finite f32 source coordinates. Lyon chooses its own actual
                // subdivision; this rejects requests beyond a declared budget.
                let dx = points[2 * (i - 1)] as f64 - 2.0 * points[2 * i] as f64
                    + points[2 * (i + 1)] as f64;
                let dy = points[2 * (i - 1) + 1] as f64 - 2.0 * points[2 * i + 1] as f64
                    + points[2 * (i + 1) + 1] as f64;
                let segments = (dx.hypot(dy) / (4.0 * tolerance as f64)).sqrt().ceil().max(1.0);
                if segments > MAX_FLATTENED_SEGMENTS as f64 { return Err(2); }
                flattening_bound += segments as usize;
                if flattening_bound > MAX_FLATTENED_SEGMENTS { return Err(2); }
                builder.quadratic_bezier_to(
                    point(points[2 * i], points[2 * i + 1]),
                    point(points[2 * (i + 1)], points[2 * (i + 1) + 1]),
                    attr(i + 1),
                );
            }
            // Filled open contours have an implicit closing segment.
            builder.end(true);
            start = end;
        }
        if start != point_count { return Err(1); }
        let path = builder.build();
        let options = FillOptions::default().with_tolerance(tolerance)
            .with_fill_rule(if fill_rule == 0 { FillRule::NonZero } else { FillRule::EvenOdd });
        let mut mesh = BoundedMesh { vertices: Vec::new(), indices: Vec::new(), attributes: attribute_count,
            max_vertices, max_indices, overflow: false };
        let result = FillTessellator::new().tessellate_path(&path, &options, &mut mesh);
        if mesh.overflow { return Err(2); }
        result.map_err(|_| 3u32)?;
        if mesh.vertices.iter().any(|v| !v.is_finite()) { return Err(3); }
        if border_width > 0.0 {
            let join = match border_join { 0 => LineJoin::Bevel, 1 => LineJoin::Miter,
                _ => LineJoin::Round };
            let stroke_options = StrokeOptions::default().with_tolerance(tolerance)
                .with_line_width(border_width).with_line_join(join)
                .with_miter_limit(border_miter_limit);
            // Stroke strips intentionally overlap. Never publish them directly
            // to an ordinary source-over pipeline, especially with translucency.
            let result = StrokeTessellator::new().tessellate_path(&path, &stroke_options, &mut mesh);
            if mesh.overflow { return Err(2); }
            result.map_err(|_| 3u32)?;
            if mesh.vertices.iter().any(|v| !v.is_finite()) { return Err(3); }
            // Each intermediate triangle contributes three straight sweep edges.
            if mesh.indices.len() > MAX_FLATTENED_SEGMENTS { return Err(2); }
            let mut union_builder = Path::builder_with_attributes(attribute_count);
            let stride = 2 + attribute_count;
            for triangle in mesh.indices.chunks_exact(3) {
                let pos = |i: u32| {
                    let offset = i as usize * stride;
                    point(mesh.vertices[offset], mesh.vertices[offset + 1])
                };
                let a = pos(triangle[0]);
                let mut b = pos(triangle[1]);
                let mut c = pos(triangle[2]);
                let cross = (b.x as f64 - a.x as f64) * (c.y as f64 - a.y as f64)
                    - (b.y as f64 - a.y as f64) * (c.x as f64 - a.x as f64);
                if cross < 0.0 { std::mem::swap(&mut b, &mut c); }
                // All triangle contours have the same winding. Concatenating
                // the original signed fill path and a stroke outline would
                // permit cancellation, which is not a geometric union.
                let uniform = &attrs[..attribute_count];
                union_builder.begin(a, uniform);
                union_builder.line_to(b, uniform);
                union_builder.line_to(c, uniform);
                union_builder.end(true);
            }
            let union_path = union_builder.build();
            drop(mesh);
            mesh = BoundedMesh { vertices: Vec::new(), indices: Vec::new(), attributes: attribute_count,
                max_vertices, max_indices, overflow: false };
            let union_options = options.with_fill_rule(FillRule::NonZero);
            let result = FillTessellator::new().tessellate_path(&union_path, &union_options, &mut mesh);
            if mesh.overflow { return Err(2); }
            result.map_err(|_| 3u32)?;
            if mesh.vertices.iter().any(|v| !v.is_finite()) { return Err(3); }
        }
        Ok(mesh)
    }));
    match outcome {
        Ok(Ok(mesh)) => {
            let vertices = mesh.vertices.into_boxed_slice();
            let indices = mesh.indices.into_boxed_slice();
            (*output).vertex_floats = vertices.len();
            (*output).index_count = indices.len();
            (*output).vertices = Box::into_raw(vertices) as *mut f32;
            (*output).indices = Box::into_raw(indices) as *mut u32;
            0
        }
        Ok(Err(code)) => code,
        Err(_) => 4,
    }
}

/// # Safety
/// `output` must be a result returned by this library, not already copied/freed.
#[no_mangle]
pub unsafe extern "C" fn ml_lyon_free(output: *mut MeshResult) {
    if output.is_null() { return; }
    if !(*output).vertices.is_null() {
        drop(Box::from_raw(ptr::slice_from_raw_parts_mut((*output).vertices, (*output).vertex_floats)));
    }
    if !(*output).indices.is_null() {
        drop(Box::from_raw(ptr::slice_from_raw_parts_mut((*output).indices, (*output).index_count)));
    }
    *output = MeshResult::default();
}
