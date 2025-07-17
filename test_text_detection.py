from manim import *

# Quick test to see text class hierarchy
text = Text("Test")
print("\nText class hierarchy:")
for cls in text.__class__.__mro__:
    print(f"  {cls.__name__}")

print(f"\nIs Text instance? {text.__class__.__name__ == 'Text'}")
print(f"Has Text in MRO? {any(base.__name__ == 'Text' for base in text.__class__.__mro__)}")
print(f"Has StringMobject in MRO? {any(base.__name__ == 'StringMobject' for base in text.__class__.__mro__)}")

# Test the condition from ThreeDScene.add
if hasattr(text, '__class__') and any(base.__name__ in ['Text', 'MarkupText', 'StringMobject'] 
                                     for base in text.__class__.__mro__):
    print("\nWould be detected as text object in ThreeDScene.add!")