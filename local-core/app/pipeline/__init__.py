"""Live perception → state pipeline (M2).

Dependency discipline: this package's core (types, geometry, state engine,
runtime orchestration) imports NO heavy libraries. YOLO and OpenCV live behind
the Detector/FrameSource protocols and are imported lazily only by their
concrete implementations, so the engine is fully testable with fakes.
"""
