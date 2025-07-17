# Text 3D Rendering Investigation and Plan

## Problem Statement

Text objects in maniml do not render correctly with depth testing in 3D scenes. The issue manifests as:
- Text fill always appears behind other objects
- Text stroke (wireframe) always appears in front of other objects
- This affects all VMobjects with fill, not just text

## Root Cause Analysis

### The Fill Rendering Pipeline

1. **VMobjects use a two-pass rendering system:**
   - Stroke pass: Renders the outline/wireframe
   - Fill pass: Renders the filled interior

2. **Fill rendering uses screen-space compositing:**
   - Fill is rendered to a separate texture using winding number algorithm
   - This texture is then composited back as a fullscreen quad
   - The composite shader hardcodes z=0 in clip space:
     ```glsl
     gl_Position = vec4((2.0 * texcoord - 1.0), 0.0, 1.0);
     ```

3. **Depth information is lost:**
   - While a depth texture is created and populated during fill rendering
   - The depth values are in object space, not scene space
   - When composited as a 2D quad, these depth values don't match the actual 3D scene depth

### Why Other 3D Objects Work

Objects like `Cube` and `Surface` work correctly because:
- They inherit from `Surface` or `Mobject`, not `VMobject`
- They use direct triangle rendering without fill/stroke separation
- They render directly to the framebuffer with proper depth testing

### ManimGL Comparison

Our investigation revealed that ManimGL has the **exact same architecture and limitation**:
- Same screen-space fill compositing approach
- Same shader code for the composite pass
- Likely has the same depth issues with text in 3D scenes

## Solution Options

### Option 1: Fix the Depth Compositing (Recommended)

**Approach:** Modify the fill rendering pipeline to preserve proper scene depth.

**Implementation Steps:**
1. Pass view/projection matrices to the depth rendering shader
2. Transform object-space depth to screen-space depth during fill rendering
3. Store the transformed depth values in the depth texture
4. Update the composite shader to correctly apply these depth values

**Pros:**
- Fixes the issue for ALL VMobjects, not just text
- Preserves the visual quality of filled objects
- Most comprehensive solution

**Cons:**
- Complex implementation
- Requires shader modifications
- Risk of breaking existing 2D rendering

### Option 2: Create Stroke-Only Text3D Class (Quick Workaround)

**Approach:** Create a specialized Text3D class that only uses stroke rendering.

**Implementation:**
```python
class Text3D(Text):
    def __init__(self, text, **kwargs):
        kwargs['fill_opacity'] = 0
        kwargs['stroke_width'] = kwargs.get('stroke_width', 2)
        super().__init__(text, **kwargs)
```

**Pros:**
- Works immediately with existing infrastructure
- Simple to implement
- No risk to existing functionality

**Cons:**
- Limited visual style (outline only)
- Not a complete solution

### Option 3: Implement True 3D Text Geometry (Most Robust)

**Approach:** Convert text to actual 3D geometry like Surface objects.

**Implementation Steps:**
1. Extract text paths from SVG representation
2. Triangulate the paths to create filled polygons
3. Generate 3D mesh data (vertices, normals, triangles)
4. Optionally add depth/extrusion for true 3D text

**Pros:**
- True 3D object with proper depth
- Can add actual thickness to text
- Works with all 3D transformations and effects
- Most flexible solution

**Cons:**
- Requires triangulation library (e.g., `earcut`, `triangle`)
- Complex implementation
- Higher performance cost

## Technical Details

### Current Shader Flow

1. **Fill Rendering:**
   ```
   Object vertices → Fill shader → Fill texture (with winding calculation)
   Object vertices → Depth shader → Depth texture (object-space depth)
   ```

2. **Composite Pass:**
   ```
   Fullscreen quad → Composite shader
   - Samples fill texture for color
   - Samples depth texture for gl_FragDepth
   - But quad is at z=0, breaking depth testing
   ```

### Required Changes for Option 1

1. **Add uniforms to depth shader:**
   ```glsl
   uniform mat4 view;
   uniform mat4 projection;
   ```

2. **Transform depth in depth shader:**
   ```glsl
   vec4 clip_pos = projection * view * vec4(world_pos, 1.0);
   float ndc_depth = clip_pos.z / clip_pos.w;
   ```

3. **Store transformed depth in texture**

4. **Use proper depth in composite shader**

## Recommendation

Start with **Option 2** as an immediate workaround for users who need 3D text now. Then implement **Option 1** as the proper fix, as it will solve the problem comprehensively for all VMobjects with fill.

Option 3 could be pursued later as an enhancement for users who need true 3D text with thickness and advanced effects.