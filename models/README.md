# Local LLM Models Directory

This directory stores local GGUF models utilized by the Helix architecture, primarily for the `VisionCortex`. 

Large `.gguf` files are ignored by git to keep the repository lightweight. 

### Moondream Vision Model
Helix relies on the `moondream` model for lightweight local vision processing. You must download the text and projection models and place them in this folder.

You can download the GGUF models from HuggingFace (or equivalent repositories) and name them as follows:
- `moondream-text.gguf`
- `moondream-mmproj.gguf`

If you are using a different model, make sure to update the paths in `brain/vision_cortex.py`.
