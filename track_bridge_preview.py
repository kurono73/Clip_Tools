"""Non-destructive Track Bridge overlay for the Movie Clip Editor."""

from math import isfinite

import bpy
from bpy.app.handlers import persistent


_handle = None
_shader = None
_point_shader = None
_cache = {}


def _area_key(context):
    return (context.area.as_pointer(), context.space_data.as_pointer())


def _has_distortion(clip):
    camera = clip.tracking.camera
    fields = {
        'POLYNOMIAL': ('k1', 'k2', 'k3'),
        'DIVISION': ('division_k1', 'division_k2'),
        'NUKE': ('nuke_k1', 'nuke_k2'),
        'BROWN': ('brown_k1', 'brown_k2', 'brown_k3', 'brown_k4', 'brown_p1', 'brown_p2'),
    }.get(camera.distortion_model, ())
    return any(abs(getattr(camera, field, 0.0)) > 1.0e-10 for field in fields)


def view_status(space):
    if space.mode != 'TRACKING' or space.view != 'CLIP':
        return "Preview requires Clip View"
    if space.show_stable and space.clip.tracking.stabilization.use_2d_stabilization:
        return "Disable Stabilized View"
    if space.clip_user.use_render_undistorted and _has_distortion(space.clip):
        return "Disable Undistorted View"
    return ""


def refresh_context(context):
    from . import track_tools

    clip = track_tools.get_clip(context)
    obj = track_tools.get_active_tracking_object(context)
    if not clip or not obj:
        return None
    settings = context.scene.track_gap_interp_settings
    tracks = [track for track in obj.tracks if track_tools.is_track_selected(track)]
    current = track_tools.scene_to_marker_frame(clip, context.scene.frame_current)
    status = view_status(context.space_data)
    gaps = tuple(track_tools.find_nearest_gap_index(
        track_tools.get_enabled_islands(sorted(track.markers, key=lambda marker: marker.frame)), current)
        for track in tracks)
    # Scrubbing within the same gap only moves the indicator, not the fitted path.
    signature = (clip.as_pointer(), obj.as_pointer(), gaps, status,
                 settings.interpolation_method, settings.join_short_islands,
                 settings.max_island_length, settings.outer_reference_keys, settings.tangent_strength,
                 tuple((track.as_pointer(), track.name,
                        tuple((marker.frame, tuple(marker.co), marker.mute) for marker in track.markers))
                       for track in tracks))
    key = _area_key(context)
    previous = _cache.get(key)
    if previous and previous["signature"] == signature:
        return previous
    plans = []
    skipped = 0
    if not status:
        for track in tracks:
            plan, _error = track_tools.plan_track_gap(track, current, settings)
            if plan is None:
                skipped += 1
            else:
                plans.append(plan)
        if not tracks:
            status = "Select a track"
        elif not plans:
            status = "No bridgeable gap"
        elif skipped:
            status = f"{skipped} track(s) skipped"
    data = {"signature": signature, "clip": clip.as_pointer(), "object": obj.as_pointer(),
            "plans": tuple(plans), "status": status}
    _cache[key] = data
    context.area.tag_redraw()
    return data


def status_for_context(context):
    if context.area is None:
        return ""
    data = _cache.get(_area_key(context))
    return data["status"] if data else ""


def _any_enabled():
    return any(getattr(getattr(scene, "track_gap_interp_settings", None), "preview_enabled", False)
               for scene in bpy.data.scenes)


def _refresh_timer():
    if not _any_enabled():
        stop(remove_timer=False)
        return None
    visible = set()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'CLIP_EDITOR' or not area.spaces.active.clip:
                continue
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            if region is None:
                continue
            with bpy.context.temp_override(window=window, area=area, region=region):
                context = bpy.context
                if context.scene.track_gap_interp_settings.preview_enabled:
                    visible.add(_area_key(context))
                    refresh_context(context)
    for key in list(_cache):
        if key not in visible:
            del _cache[key]
    return 0.15


def set_enabled(context, enabled):
    global _handle
    if enabled:
        if not bpy.app.background and _handle is None:
            _handle = bpy.types.SpaceClipEditor.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')
        if not bpy.app.background and not bpy.app.timers.is_registered(_refresh_timer):
            bpy.app.timers.register(_refresh_timer, first_interval=0.05)
        if context.area and context.area.type == 'CLIP_EDITOR' and context.space_data.clip:
            refresh_context(context)
    elif not _any_enabled():
        stop()
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'CLIP_EDITOR':
                area.tag_redraw()


def screen_point(region, co):
    # Invert View2D in floats to avoid the integer rounding of view_to_region.
    lower = region.view2d.region_to_view(0, 0)
    upper = region.view2d.region_to_view(region.width, region.height)
    dx, dy = upper[0] - lower[0], upper[1] - lower[1]
    if abs(dx) < 1.0e-12 or abs(dy) < 1.0e-12:
        return None
    point = ((co[0] - lower[0]) * region.width / dx,
             (co[1] - lower[1]) * region.height / dy)
    return point if all(isfinite(value) for value in point) else None


def _squares(points, half):
    vertices = []
    for x, y in points:
        a, b, c, d = (x - half, y - half), (x + half, y - half), (x + half, y + half), (x - half, y + half)
        vertices.extend((a, b, c, a, c, d))
    return vertices


def _draw():
    global _shader, _point_shader
    from .track_tools import get_active_tracking_object

    context = bpy.context
    space = context.space_data
    if (not space or space.type != 'CLIP_EDITOR' or space.view != 'CLIP' or not space.clip
            or not context.scene.track_gap_interp_settings.preview_enabled
            or not getattr(getattr(space, "overlay", None), "show_overlays", True)):
        return
    data = _cache.get(_area_key(context))
    obj = get_active_tracking_object(context)
    if (not data or not obj or data["clip"] != space.clip.as_pointer()
            or data["object"] != obj.as_pointer() or not data["plans"] or view_status(space)):
        return
    region = context.region
    display_frame = context.scene.frame_current - space.clip.frame_start + 1
    lines, existing_lines, points, current_points = [], [], [], []
    for plan in data["plans"]:
        for paths, vertices in ((plan["paths"], lines), (plan["existing_paths"], existing_lines)):
            for path in paths:
                positions = [screen_point(region, co) for _frame, co in path]
                for a, b in zip(positions, positions[1:]):
                    if a is not None and b is not None:
                        vertices.extend((a, b))
        for frame, co in plan["positions"]:
            point = screen_point(region, co)
            if point is not None:
                points.append(point)
                if frame == display_frame:
                    current_points.append(point)
    if not lines:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader

    if _shader is None:
        _shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        _point_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    old_blend, old_depth = gpu.state.blend_get(), gpu.state.depth_test_get()
    try:
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        batch = batch_for_shader(_shader, 'LINES', {"pos": lines})
        _shader.bind()
        _shader.uniform_float("viewportSize", (region.width, region.height))
        if existing_lines:
            _shader.uniform_float("lineWidth", 1.5)
            _shader.uniform_float("color", (0.65, 0.65, 0.65, 0.85))
            batch_for_shader(_shader, 'LINES', {"pos": existing_lines}).draw(_shader)
        for width, color in ((5.0, (0.02, 0.02, 0.02, 0.9)), (2.5, (0.1, 1.0, 0.45, 1.0))):
            _shader.uniform_float("lineWidth", width)
            _shader.uniform_float("color", color)
            batch.draw(_shader)
        for centers, half, color in ((points, 1.5, (0.1, 1.0, 0.45, 1.0)),
                                     (current_points, 3.5, (1.0, 0.85, 0.1, 1.0))):
            if centers:
                _point_shader.bind()
                _point_shader.uniform_float("color", color)
                batch_for_shader(_point_shader, 'TRIS', {"pos": _squares(centers, half)}).draw(_point_shader)
    finally:
        gpu.state.blend_set(old_blend)
        gpu.state.depth_test_set(old_depth)


def stop(remove_timer=True):
    global _handle, _shader, _point_shader
    if _handle is not None:
        bpy.types.SpaceClipEditor.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    if remove_timer and bpy.app.timers.is_registered(_refresh_timer):
        bpy.app.timers.unregister(_refresh_timer)
    if bpy.app.timers.is_registered(_restore_preview):
        bpy.app.timers.unregister(_restore_preview)
    _cache.clear()
    _shader = _point_shader = None


@persistent
def _load_pre(_unused):
    stop()


def _restore_preview():
    if _any_enabled():
        set_enabled(bpy.context, True)
    return None


def register():
    if _load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_load_pre)
    # Addon enable runs under RestrictBlend; defer all scene/context access.
    if not bpy.app.timers.is_registered(_restore_preview):
        bpy.app.timers.register(_restore_preview, first_interval=0.0)


def unregister():
    stop()
    if _load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_load_pre)
