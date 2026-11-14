#!/usr/bin/env python3
"""Thin shim — logic lives in ringwear/.

Re-exports the public API so that `import ring_wear; ring_wear.Params` keeps working.
"""
from ringwear import Params, analyse, IMG_EXT, write_excel, write_html, write_pptx, main, ImageFont
from ringwear.cli import collect

if __name__ == "__main__":
    main()
