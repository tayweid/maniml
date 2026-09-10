//! Small, versioned C ABI for the isolated CPU fill experiment.
//!
//! Only the Python adapter calls this ABI. It is not a sandbox for untrusted
//! native pointers. Output ownership belongs to Rust until ml_lyon_free.

use lyon_tessellation::geometry_builder::{FillGeometryBuilder, GeometryBuilder};
use lyon_tessellation::math::point;
use lyon_tessellation::path::Path;
use lyon_tessellation::{
    FillOptions, FillRule, FillTessellator, FillVertex, GeometryBuilderError, VertexId,
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
    if output.is_null() { return 1; }
    *output = MeshResult::default();
    if point_count > MAX_SOURCE_POINTS || attribute_count > MAX_ATTRIBUTES
        || max_vertices > MAX_VERTICES || max_indices > MAX_INDICES
        || !tolerance.is_finite() || tolerance <= 0.0 || fill_rule > 1
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
