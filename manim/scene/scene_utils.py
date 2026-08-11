"""Utility functions for scene checkpoint management."""

import copy
from manim.renderer.opengl.mobject.mobject import Mobject


def deepcopy_namespace(namespace_or_checkpoint):
    """Deep copy a namespace or checkpoint, filtering out uncopyable items first."""
    import copy
    
    # Check if this is a checkpoint dict (has 'namespace' and 'state' keys)
    if isinstance(namespace_or_checkpoint, dict) and 'namespace' in namespace_or_checkpoint and 'state' in namespace_or_checkpoint:
        # This is a checkpoint - we need to deepcopy namespace and state together
        checkpoint = namespace_or_checkpoint
        
        # Combine namespace and state into one dict for deepcopying together
        combined = {}
        combined['__checkpoint_state__'] = checkpoint['state']
        
        # Add namespace items
        for name, value in checkpoint['namespace'].items():
            if name in ['__builtins__', '__loader__', '__spec__', '__cached__', 'self']:
                continue
            combined[name] = value
            
        # Test what can be deepcopied
        deepcopyable = {}
        non_deepcopyable = {}
        
        for name, value in combined.items():
            try:
                test_copy = copy.deepcopy(value)
                deepcopyable[name] = value
            except Exception:
                non_deepcopyable[name] = value
                
        # Deepcopy all deepcopyable items together
        try:
            copied_items = copy.deepcopy(deepcopyable)
            
            # Extract the state
            state = copied_items.pop('__checkpoint_state__', checkpoint['state'])
            
            # Add non-deepcopyable items
            for name, value in non_deepcopyable.items():
                if name != '__checkpoint_state__':
                    copied_items[name] = value
                    
            # Return checkpoint structure
            return {
                'index': checkpoint.get('index', 0),
                'line_number': checkpoint.get('line_number', 0),
                'state': state,
                'namespace': copied_items
            }
            
        except Exception as e:
            print(f"Warning: Checkpoint deepcopy failed ({e}), falling back")
            # Fall through to regular handling
    
    # Regular namespace handling
    namespace = namespace_or_checkpoint
    
    # First pass: test what can be deepcopied
    deepcopyable = {}
    non_deepcopyable = {}
    
    for name, value in namespace.items():
        # Always skip these
        if name in ['__builtins__', '__loader__', '__spec__', '__cached__', 'self']:
            continue
            
        # Test if this item can be deepcopied
        try:
            test_copy = copy.deepcopy(value)
            deepcopyable[name] = value
        except Exception:
            # Can't deepcopy this item, keep as reference
            non_deepcopyable[name] = value
    
    # Second pass: deepcopy all deepcopyable items together
    # This preserves reference relationships between them
    try:
        copied_items = copy.deepcopy(deepcopyable)
        
        # Add back the non-deepcopyable items as references
        for name, value in non_deepcopyable.items():
            copied_items[name] = value
            
        return copied_items
        
    except Exception as e:
        # If even this fails, fall back to manual implementation
        print(f"Warning: Filtered deepcopy failed ({e}), falling back to individual copy")
        
        # Fallback implementation
        new_namespace = {}
        
        for name, value in filtered.items():
            try:
                if isinstance(value, Mobject):
                    # Deep copy mobjects
                    new_namespace[name] = value.copy()
                elif isinstance(value, (list, tuple)):
                    # Handle collections that might contain mobjects
                    new_items = []
                    for item in value:
                        if isinstance(item, Mobject):
                            new_items.append(item.copy())
                        else:
                            new_items.append(item)
                    new_namespace[name] = type(value)(new_items)
                elif isinstance(value, dict):
                    # Handle dicts that might contain mobjects
                    new_dict = {}
                    for k, v in value.items():
                        if isinstance(v, Mobject):
                            new_dict[k] = v.copy()
                        else:
                            new_dict[k] = v
                    new_namespace[name] = new_dict
                else:
                    # Try to deepcopy, but fall back to reference if it fails
                    try:
                        new_namespace[name] = copy.deepcopy(value)
                    except (TypeError, AttributeError):
                        # Keep reference for unpicklable objects
                        new_namespace[name] = value
            except Exception:
                # If anything goes wrong, keep the reference
                new_namespace[name] = value
                
        return new_namespace