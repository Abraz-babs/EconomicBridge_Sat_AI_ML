"""Operator-run scripts (training, eval, dataset prep).

These are NOT part of the runtime FastAPI app — they're CLI tools the
operator runs manually (or via CI) to produce the artifacts the runtime
loads. Keep imports lightweight; heavy ML libs (torch + torchvision)
load lazily inside each script's `main()` so the package itself is
importable for testing without GPU/CPU torch installed.
"""
