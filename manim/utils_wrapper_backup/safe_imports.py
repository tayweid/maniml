"""
Safe import utilities for maniml.

Handles importing from ManimGL with fallbacks when classes don't exist.
"""

import warnings
from typing import Any, Dict, Optional, Type


def safe_import_from_module(module_path: str, class_names: list) -> Dict[str, Optional[Any]]:
    """
    Safely import multiple classes from a module.
    
    Returns a dict mapping class names to the imported classes (or None if not found).
    """
    results = {}
    
    try:
        module = __import__(module_path, fromlist=class_names)
    except ImportError:
        warnings.warn(f"maniml: Module {module_path} not found", UserWarning)
        return {name: None for name in class_names}
    
    for name in class_names:
        try:
            results[name] = getattr(module, name)
        except AttributeError:
            results[name] = None
            
    return results


def create_fallback_class(base_class: Type, class_name: str, simplified_message: str = None):
    """Create a fallback class that warns when used."""
    
    class FallbackClass(base_class):
        def __init__(self, *args, **kwargs):
            message = simplified_message or f"maniml: {class_name} not available, using simplified version"
            warnings.warn(message, UserWarning)
            super().__init__(*args, **kwargs)
    
    FallbackClass.__name__ = class_name
    FallbackClass.__qualname__ = class_name
    
    return FallbackClass