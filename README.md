# ManimLive

ManimLive speeds up Manim's animation workflow by bringing hot reloading and interactive navigation on top of ManimGL's OpenGL renderer, all compatabile with the existing ManimCE API. 

## Features

- **ManimCE API compatibility**: *all existing ManimCE code will (should) render*
- **Live preview:** *real-time OpenGL rendering in a separate window*
- **Keyboard navigation:** *arrow keys navigate through the animations, built on dynamic checkpointing*
- **Hot reloading:** *the preview window automatically plays edited animations*

## Installation

```bash
pip install -e .
```

## Usage

Use exactly like ManimCE:

```python
from manim import *

class Example(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.wait()
```

Run with:
```bash
manim example.py Example
```

## Status

This is a work in progress. Most ManimCE features are implemented, but some are still being added. Bugs are to be expected. 

## OpenGL Backend and 3d Scenes

All mobjects are 3d. Wireframes are compatible with 2d done with bezier curves. Fills are done with triangles. 2d scenes just have all mobjects placed at z=0 with the camera facing directly down. Since all mobjects in 2d are at z=0, z_index controls which is visible when they overlap. In progress.

## Checkpoints and Hot Reloading

#### Goals

The main goal of the checkpoint system is to make it much easier to test and iterate on manim animations. It opens a preview window of the animations, allows navigating through animations, quickly jumping through animations, and hot reloading animations that have been updated in the source file. 

Only play() creates checkpoints. The wait() method does not create new checkpoints.

#### Description

When the program runs, it initiates the first checkpoint which is just a plank screen with no mobjects, then runs the first animation and saves a checkpoint.

Checkpoints contain: 
1. index: Animation number
2. line_number: Last line of the play() call inside construct
3. state: SceneState with mobject copies
4. namespace: The namespace taken from exec() at the end of the checkpoint

Checkpoint 0: checkpoints[0] = {index: 0, line_number: 0, state: {}, namespace: {# should contain the namespace of a baseline python instance}}

Running an animation:
0. Clears current window
1. Creates checkpoint_temporary
2. Uses current_checkpoint_index to find the line_number for the current checkpoint, commenting out all the code up to and including line_number, calling it current_checkpoint_code
3. Sets checkpoint_temporary['namespace'] = checkpoints[current_checkpoint_index]['namespace'].copy()
4. Sends current_checkpoint_code to exec in the namespace of checkpoint_temporary.
5. Updates current_checkpoint_index, retrieves line_number, collects state and namespace, adds them to checkpoint_temporary, and uses the new checkpoint_temporary to set checkpoints[current_checkpoint_index] = checkpoint_temporary. 

There may have to be a restore_scene run right before running exec(). I'm not sure how exec interacts with the window. 



ok so would there be a way to copy the namespace to give each object a different id than the objects in another checkpoint's namespace? 
if we could do this i think we could save a reference to the mobjects in the checkpoints namespace without introducing the possibility of conflicting with other checkpoint mobjects. 
this would create distinct bundles at each checkpoint. 
then we clear the screen, run code on the bundle to create the next checkpoint, and continue.

Yes, you're suggesting we deep copy the mobjects when copying the namespace, so each checkpoint has its own isolated set of mobject instances. This would create distinct "bundles" at each checkpoint. The key insight is that by deep copying mobjects when creating namespace copies, we create isolated "worlds" at each checkpoint, which is exactly what the spec seems to intend with the checkpoint_temporary workflow.



So running an animation creates a checkpoint when the .play() first method is called, exiting exec(). Creating a checkpoint saves the checkpoint `index`, the `line_number` of the LAST line of the play() call in the .py file to handle multiline play() calls, the `state` which stores the state of manim objects for quick reloading, and the `namespace` containing the environment at the code run up to the END of the checkpoing which enables quickly running code starting at the end of any checkpoint. 

If we’re at the furthest checkpoint created so far (checkpoints[-1]), then we have to use run_next_animation(), creating the next checkpoint.

If we're not at the furthest checkpoint created so far, we can either jump_to_next_animation() to jump forward to the end of the next animation, or run_next_animation() to play forward to the next animation. If we're not at the first animation, we can jump_to_previous_animation() to jump backward to the end of the previous animation.