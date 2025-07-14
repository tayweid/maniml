"""
TeX template compatibility.
"""

import warnings


class TexTemplate:
    """CE-compatible TeX template - simplified version."""
    
    def __init__(self, tex_compiler="latex", output_format="svg",
                 preamble="", placeholder_text="YourTextHere",
                 post_doc_commands=""):
        self.tex_compiler = tex_compiler
        self.output_format = output_format
        self.preamble = preamble
        self.placeholder_text = placeholder_text
        self.post_doc_commands = post_doc_commands
        
        if tex_compiler != "latex" or output_format != "svg":
            warnings.warn(
                "maniml: Custom TeX settings may not work with GL backend.",
                UserWarning
            )


class TexTemplateLibrary:
    """CE-compatible TeX template library."""
    
    @staticmethod
    def default():
        """Default template."""
        return TexTemplate()
    
    @staticmethod
    def ctex():
        """Chinese TeX template."""
        return TexTemplate(
            tex_compiler="xelatex",
            preamble=r"\usepackage{ctex}"
        )
    
    @staticmethod
    def ams():
        """AMS math template."""
        return TexTemplate(
            preamble=r"\usepackage{amsmath}\usepackage{amssymb}"
        )