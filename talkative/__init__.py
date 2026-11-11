__version__ = "1.3.23"
import os as _os

# Model downloads over plain HTTPS, not Hugging Face's Xet engine: Xet
# writes each file in a few big pieces at the end, so the Settings
# progress bars (which read bytes on disk) jumped 0% -> 69% -> done.
# Over HTTPS the file grows steadily; same speed here (2026-11-11, 0.5 GB
# in 18 s). Must be set before huggingface_hub is first imported.
_os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
_os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
