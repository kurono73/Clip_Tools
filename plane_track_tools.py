"""Key navigation and native key editing for the active plane track."""

from contextlib import contextmanager
import ctypes
from math import isfinite
import struct

import bpy
from bpy.types import Operator
from mathutils.geometry import convex_hull_2d

from .track_tools import (
    change_clip_editor_frame,
    find_neighbor_frame,
    get_active_tracking_object,
    get_clip,
    get_enabled_islands,
    is_track_selected,
    key_navigation_context,
    redraw_clip_editors,
)


# DNA_tracking_types.h in Blender 4.2--5.2: corners[4][2], framenr, flag.
# RNA does not expose PLANE_MARKER_TRACKED. Only read this data; all edits go
# through Blender's native operator so the surrounding plane motion is retracked.
_PLANE_MARKER = struct.Struct("=8f2i")
_PLANE_MARKER_DISABLED = 1 << 0
_PLANE_MARKER_TRACKED = 1 << 1


def get_active_plane_track(context):
    tracking_object = get_active_tracking_object(context)
    if tracking_object is not None:
        return tracking_object.plane_tracks.active
    return None


def plane_key_access_supported():
    return ("is_keyed" in bpy.types.MovieTrackingPlaneMarker.bl_rna.properties
            or (4, 2) <= bpy.app.version[:2] < (5, 3))


def is_plane_marker_keyed(marker):
    if hasattr(marker, "is_keyed"):
        return bool(marker.is_keyed)
    if not plane_key_access_supported():
        raise RuntimeError("Plane key access is not verified for this Blender version")

    pointer = marker.as_pointer()
    if not pointer:
        raise RuntimeError("The plane marker is no longer valid")
    data = _PLANE_MARKER.unpack(ctypes.string_at(pointer, _PLANE_MARKER.size))
    corners = tuple(float(value) for corner in marker.corners for value in corner)
    frame, flags = data[-2:]
    # Fail closed if the native layout or flags differ from the verified DNA.
    if (frame != marker.frame or data[:8] != corners or flags & ~3
            or bool(flags & _PLANE_MARKER_DISABLED) != bool(marker.mute)):
        raise RuntimeError("Plane marker layout validation failed; no data was changed")
    return not bool(flags & _PLANE_MARKER_TRACKED)


def plane_key_frames(plane_track):
    return sorted(marker.frame for marker in plane_track.markers if is_plane_marker_keyed(marker))


def plane_track_poll(cls, context):
    space = getattr(context, "space_data", None)
    if not space or space.type != 'CLIP_EDITOR' or space.mode != 'TRACKING':
        return False
    if get_active_plane_track(context) is None:
        cls.poll_message_set("Select an active plane track")
        return False
    if not plane_key_access_supported():
        cls.poll_message_set("Plane key access is not verified for this Blender version")
        return False
    return True


def set_plane_marker_frame(context, frame):
    clip = get_clip(context)
    # Frame Offset affects footage loading, not the plane's marker frame numbers.
    scene_frame = frame + clip.frame_start - 1
    context.scene.frame_set(scene_frame)
    context.space_data.clip_user.frame_current = scene_frame
    clip.update_tag()
    change_clip_editor_frame(context, clip, scene_frame)
    redraw_clip_editors(context)


def jump_plane_key(context, direction, report):
    clip = get_clip(context)
    current = context.scene.frame_current - clip.frame_start + 1
    try:
        target = find_neighbor_frame(plane_key_frames(get_active_plane_track(context)), current, direction)
    except RuntimeError as error:
        report({'ERROR'}, str(error))
        return {'CANCELLED'}
    if target is None:
        report({'INFO'}, "No plane track keyframe found in that direction")
        return {'CANCELLED'}
    set_plane_marker_frame(context, target)
    return {'FINISHED'}


def plane_range_frames(plane_track):
    markers = sorted(plane_track.markers, key=lambda marker: marker.frame)
    frames = []
    for island in get_enabled_islands(markers):
        # Exclude one frame at each end for plane-range navigation only.
        start, end = island[0].frame + 1, island[-1].frame - 1
        if start <= end:
            frames.extend((start, end))
    return frames


def jump_plane_range(context, direction, report):
    clip = get_clip(context)
    current = context.scene.frame_current - clip.frame_start + 1
    target = find_neighbor_frame(plane_range_frames(get_active_plane_track(context)), current, direction)
    if target is None:
        report({'INFO'}, "No enabled plane track range boundary found in that direction")
        return {'CANCELLED'}
    set_plane_marker_frame(context, target)
    return {'FINISHED'}


@contextmanager
def isolated_plane_key_edit(context):
    tracking_object = get_active_tracking_object(context)
    plane = get_active_plane_track(context)
    selections = [(track, track.select_anchor, track.select_pattern, track.select_search)
                  for track in tracking_object.tracks]
    plane_selections = [(track, track.select) for track in tracking_object.plane_tracks]
    auto_keying = plane.use_auto_keying
    try:
        for track, _anchor, _pattern, _search in selections:
            track.select = False
        for track, _selected in plane_selections:
            track.select = track == plane
        # Without this flag Blender may retrack across the other authored keys.
        plane.use_auto_keying = True
        yield plane
    finally:
        plane.use_auto_keying = auto_keying
        for track, anchor, pattern, search in selections:
            track.select_anchor = anchor
            track.select_pattern = pattern
            track.select_search = search
        for track, selected in plane_selections:
            track.select = selected
        context.space_data.clip_user.frame_current = context.scene.frame_current


def edit_plane_key(context, plane, frame, insert=False):
    clip = get_clip(context)
    # The native operators use ClipUser's scene frame, not scene.frame_current.
    context.space_data.clip_user.frame_current = frame + clip.frame_start - 1
    operator = bpy.ops.clip.keyframe_insert if insert else bpy.ops.clip.keyframe_delete
    result = operator('EXEC_DEFAULT')
    marker = plane.markers.find_frame(frame, exact=True)
    keyed = marker is not None and is_plane_marker_keyed(marker)
    if 'FINISHED' not in result or keyed != insert:
        action = "insert" if insert else "remove"
        raise RuntimeError(f"Blender could not {action} the plane track keyframe at {frame}")


def ordered_plane_corners(points):
    if len(points) != 4 or not all(isfinite(value) for point in points for value in point):
        raise ValueError("Four finite marker positions are required")
    hull = convex_hull_2d(points)
    if len(hull) != 4:
        raise ValueError("The four points must be distinct corners of a convex quadrilateral")
    corners = [tuple(points[index]) for index in hull]
    extent = max(max(p[axis] for p in corners) - min(p[axis] for p in corners) for axis in (0, 1))
    for index in range(4):
        a, b, c = (corners[(index + offset) % 4] for offset in range(3))
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if cross <= extent * extent * 1.0e-7:
            raise ValueError("The selected points are too close to a straight line")
    # Native corner order is lower-left, lower-right, upper-right, upper-left.
    start = min(range(4), key=lambda index: (sum(corners[index]), corners[index][1], corners[index][0]))
    return corners[start:] + corners[:start]


class CLIP_OT_plane_track_create_from_points(Operator):
    bl_idname = "clip.plane_track_create_from_points"
    bl_label = "Create Plane Track"
    bl_description = "Create a plane on the four selected point markers with Auto Keyframe enabled"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        if not space or space.type != 'CLIP_EDITOR' or space.mode != 'TRACKING' or not get_clip(context):
            return False
        if not plane_key_access_supported():
            cls.poll_message_set("Plane key access is not verified for this Blender version")
            return False
        tracking_object = get_active_tracking_object(context)
        if tracking_object is None or sum(is_track_selected(track) for track in tracking_object.tracks) != 4:
            cls.poll_message_set("Select exactly four point tracks in the active tracking object")
            return False
        return get_clip(context).is_editable and bpy.ops.clip.create_plane_track.poll()

    def execute(self, context):
        clip = get_clip(context)
        tracking_object = get_active_tracking_object(context)
        tracks = [track for track in tracking_object.tracks if is_track_selected(track)]
        frame = context.scene.frame_current - clip.frame_start + 1
        try:
            points = []
            for track in tracks:
                marker = track.markers.find_frame(frame, exact=True)
                if track.hide or marker is None or marker.mute:
                    raise ValueError(f"'{track.name}' needs a visible, enabled marker at the current frame")
                points.append(tuple(marker.co))
            corners = ordered_plane_corners(points)
        except ValueError as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}

        selections = [(track, track.select_anchor, track.select_pattern, track.select_search)
                      for track in tracking_object.tracks]
        plane_selections = [(plane, plane.select) for plane in tracking_object.plane_tracks]
        old_active = tracking_object.tracks.active
        old_plane = get_active_plane_track(context)
        plane = None
        try:
            context.space_data.clip_user.frame_current = context.scene.frame_current
            result = bpy.ops.clip.create_plane_track('EXEC_DEFAULT')
            if 'FINISHED' not in result:
                raise RuntimeError("Blender could not create the plane track")
            plane = get_active_plane_track(context)
            if plane is None or any(plane == old for old, _selected in plane_selections):
                raise RuntimeError("Blender did not activate a new plane track")
            with isolated_plane_key_edit(context):
                marker = plane.markers.find_frame(frame, exact=True)
                if marker is None:
                    raise RuntimeError("The new plane has no marker at the current frame")
                if is_plane_marker_keyed(marker):
                    edit_plane_key(context, plane, frame)
                plane.markers.find_frame(frame, exact=True).corners = corners
                # A native key insertion rebuilds motion from the fitted corners.
                edit_plane_key(context, plane, frame, insert=True)
        except (RuntimeError, TypeError, ValueError) as error:
            if plane is not None and not any(plane == old for old, _selected in plane_selections):
                for track in tracking_object.tracks:
                    track.select = False
                for other in tracking_object.plane_tracks:
                    other.select = other == plane
                bpy.ops.clip.delete_track('EXEC_DEFAULT', confirm=False)
            for track, anchor, pattern, search in selections:
                track.select_anchor, track.select_pattern, track.select_search = anchor, pattern, search
            for old, selected in plane_selections:
                old.select = selected
            if old_active is not None:
                tracking_object.tracks.active = old_active
            if old_plane is not None:
                clip.tracking.plane_tracks.active = old_plane
            context.space_data.clip_user.frame_current = context.scene.frame_current
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

        # Native shape edits discard existing plane keys while Auto Keyframe is off.
        plane.use_auto_keying = True
        for other in tracking_object.plane_tracks:
            other.select = other == plane
        clip.update_tag()
        redraw_clip_editors(context)
        return {'FINISHED'}


class CLIP_OT_plane_track_key_previous(Operator):
    bl_idname = "clip.plane_track_key_previous"
    bl_label = "Previous Plane Track Key"
    bl_description = "Jump to the previous keyframe of the active plane track"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return plane_track_poll(cls, context)

    def execute(self, context):
        return jump_plane_key(context, 'PREVIOUS', self.report)


class CLIP_OT_plane_track_key_next(Operator):
    bl_idname = "clip.plane_track_key_next"
    bl_label = "Next Plane Track Key"
    bl_description = "Jump to the next keyframe of the active plane track"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return plane_track_poll(cls, context)

    def execute(self, context):
        return jump_plane_key(context, 'NEXT', self.report)


class CLIP_OT_plane_track_key_delete(Operator):
    bl_idname = "clip.plane_track_key_delete"
    bl_label = "Delete Plane Track Key"
    bl_description = "Delete the current keyframe from only the active plane track and retrack its motion"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return plane_track_poll(cls, context) and bpy.ops.clip.keyframe_delete.poll()

    def execute(self, context):
        clip = get_clip(context)
        plane = get_active_plane_track(context)
        if not clip.is_editable:
            self.report({'ERROR'}, "The movie clip is not editable")
            return {'CANCELLED'}
        frame = context.scene.frame_current - clip.frame_start + 1
        marker = plane.markers.find_frame(frame, exact=True)
        try:
            if marker is None or not is_plane_marker_keyed(marker):
                self.report({'INFO'}, "No plane track keyframe at the current frame")
                return {'CANCELLED'}
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

        try:
            with isolated_plane_key_edit(context):
                edit_plane_key(context, plane, frame)
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

        clip.update_tag()
        redraw_clip_editors(context)
        return {'FINISHED'}


class CLIP_OT_plane_track_key_insert(Operator):
    bl_idname = "clip.plane_track_key_insert"
    bl_label = "Insert Plane Track Key"
    bl_description = "Record the current plane shape and enable Auto Keyframe to protect it during later edits"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return plane_track_poll(cls, context) and bpy.ops.clip.keyframe_insert.poll()

    def execute(self, context):
        clip = get_clip(context)
        plane = get_active_plane_track(context)
        if not clip.is_editable:
            self.report({'ERROR'}, "The movie clip is not editable")
            return {'CANCELLED'}
        frame = context.scene.frame_current - clip.frame_start + 1
        editing = False
        try:
            # Validate existing markers before any native operation changes the data.
            plane_key_frames(plane)
            marker = plane.markers.find_frame(frame, exact=False)
            if marker is None:
                self.report({'INFO'}, "No plane marker shape is available at the current frame")
                return {'CANCELLED'}
            corners = tuple(tuple(corner) for corner in marker.corners)
            mute = marker.mute
            with isolated_plane_key_edit(context):
                editing = True
                if plane.markers.find_frame(frame, exact=True) is None:
                    plane.markers.insert_frame(frame)
                try:
                    # Native insert alone skips an existing key. Force the same
                    # homography rebuild as a confirmed Auto Keyframe corner edit.
                    edit_plane_key(context, plane, frame)
                finally:
                    marker = plane.markers.find_frame(frame, exact=True)
                    if marker is None:
                        marker = plane.markers.insert_frame(frame)
                    marker.corners = corners
                    marker.mute = mute
                    edit_plane_key(context, plane, frame, insert=True)
            plane.use_auto_keying = True
        except RuntimeError as error:
            if not editing:
                self.report({'ERROR'}, str(error))
                return {'CANCELLED'}
            # Keep any native changes undoable even if key insertion is interrupted.
            self.report({'WARNING'}, f"Plane key insertion incomplete. {error}")
        clip.update_tag()
        redraw_clip_editors(context)
        return {'FINISHED'}


class CLIP_OT_plane_track_update(Operator):
    bl_idname = "clip.plane_track_update"
    bl_label = "Update Plane Track"
    bl_description = "Recalculate motion from linked point tracks while preserving plane keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (plane_track_poll(cls, context) and bpy.ops.clip.keyframe_insert.poll()
                and bpy.ops.clip.keyframe_delete.poll())

    def execute(self, context):
        clip = get_clip(context)
        plane = get_active_plane_track(context)
        if not clip.is_editable:
            self.report({'ERROR'}, "The movie clip is not editable")
            return {'CANCELLED'}
        try:
            markers = [(marker.frame, tuple(tuple(corner) for corner in marker.corners),
                        marker.mute, is_plane_marker_keyed(marker)) for marker in plane.markers]
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        keys = [data for data in markers if data[3]]
        if not keys:
            self.report({'INFO'}, "Insert a plane track keyframe before updating its motion")
            return {'CANCELLED'}

        try:
            with isolated_plane_key_edit(context):
                try:
                    for frame, corners, mute, _keyed in keys:
                        try:
                            edit_plane_key(context, plane, frame)
                        finally:
                            # Deletion can recompute this frame from neighbouring keys.
                            # Restore its authored shape before reinserting the key.
                            marker = plane.markers.find_frame(frame, exact=True)
                            if marker is None:
                                marker = plane.markers.insert_frame(frame)
                            marker.corners = corners
                            marker.mute = mute
                            edit_plane_key(context, plane, frame, insert=True)
                finally:
                    # Native retracking may copy an anchor's OFF state to its neighbours.
                    for frame, _corners, mute, _keyed in markers:
                        marker = plane.markers.find_frame(frame, exact=True)
                        if marker is not None:
                            marker.mute = mute
        except RuntimeError as error:
            # Native edits may already have changed motion; retain an undo step.
            self.report({'WARNING'}, f"Plane track update incomplete. {error}")
        else:
            self.report({'INFO'}, "Updated plane track motion")
        clip.update_tag()
        redraw_clip_editors(context)
        return {'FINISHED'}


class CLIP_OT_plane_track_keys_clear(Operator):
    bl_idname = "clip.plane_track_keys_clear"
    bl_label = "Clear All Plane Track Keys"
    bl_description = "Clear all plane keys while keeping the current shape as the motion reference"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (plane_track_poll(cls, context) and bpy.ops.clip.keyframe_delete.poll()
                and bpy.ops.clip.keyframe_insert.poll())

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        clip = get_clip(context)
        plane = get_active_plane_track(context)
        if not clip.is_editable:
            self.report({'ERROR'}, "The movie clip is not editable")
            return {'CANCELLED'}
        cleared = 0
        frame = context.scene.frame_current - clip.frame_start + 1
        try:
            frames = plane_key_frames(plane)
            if not frames:
                self.report({'INFO'}, "The active plane track has no keyframes")
                return {'CANCELLED'}
            marker = plane.markers.find_frame(frame, exact=False)
            if marker is None:
                self.report({'INFO'}, "No plane marker shape is available at the current frame")
                return {'CANCELLED'}
            corners = tuple(tuple(corner) for corner in marker.corners)
            mute = marker.mute
            modes = [(marker.frame, marker.mute) for marker in plane.markers]
            with isolated_plane_key_edit(context):
                try:
                    for key_frame in frames:
                        edit_plane_key(context, plane, key_frame)
                        cleared += 1
                    marker = plane.markers.find_frame(frame, exact=True)
                    if marker is None:
                        marker = plane.markers.insert_frame(frame)
                    if is_plane_marker_keyed(marker):
                        edit_plane_key(context, plane, frame)
                    marker = plane.markers.find_frame(frame, exact=True)
                    marker.corners = corners
                    marker.mute = mute
                    # Rebuild around the displayed quad, then remove the sole
                    # temporary key without another anchor changing its shape.
                    edit_plane_key(context, plane, frame, insert=True)
                    edit_plane_key(context, plane, frame)
                finally:
                    marker = plane.markers.find_frame(frame, exact=True)
                    if marker is not None:
                        marker.corners = corners
                        marker.mute = mute
                    for marker_frame, original_mute in modes:
                        marker = plane.markers.find_frame(marker_frame, exact=True)
                        if marker is not None:
                            marker.mute = original_mute
        except RuntimeError as error:
            if not cleared:
                self.report({'ERROR'}, str(error))
                return {'CANCELLED'}
            # Keep a partial batch undoable if Blender declines a later key.
            self.report({'WARNING'}, f"Cleared {cleared} keyframes. {error}")
        else:
            self.report({'INFO'}, f"Cleared {cleared} plane track keyframes")
        clip.update_tag()
        redraw_clip_editors(context)
        return {'FINISHED'}


def draw_plane_track_keys(self, context):
    plane = get_active_plane_track(context)
    if plane is None:
        # The native panel disables its layout when no plane is active.
        self.layout.active = True
        row = self.layout.row()
        row.operator_context = 'EXEC_DEFAULT'
        row.operator(CLIP_OT_plane_track_create_from_points.bl_idname, icon='TRACKING')
        return
    row = self.layout.row(align=True)
    row.use_property_split = False
    row.operator_context = 'EXEC_DEFAULT'
    row.label(text="Keyframe:")
    navigation = row.row(align=True)
    navigation.operator_context = key_navigation_context(context)
    navigation.context_pointer_set("clip_tools_key_plane", plane)
    navigation.operator("clip.jump_selected_track_key_previous", text="", icon='PREV_KEYFRAME')
    navigation.operator("clip.jump_selected_track_key_next", text="", icon='NEXT_KEYFRAME')
    row.operator(CLIP_OT_plane_track_key_insert.bl_idname, text="", icon='KEY_HLT')
    row.operator(CLIP_OT_plane_track_key_delete.bl_idname, text="", icon='KEY_DEHLT')
    row.operator(CLIP_OT_plane_track_update.bl_idname, text="", icon='FILE_REFRESH')
    row.operator_context = 'INVOKE_DEFAULT'
    row.operator(CLIP_OT_plane_track_keys_clear.bl_idname, text="", icon='TRASH')


classes = (CLIP_OT_plane_track_create_from_points, CLIP_OT_plane_track_key_previous, CLIP_OT_plane_track_key_next,
           CLIP_OT_plane_track_key_insert, CLIP_OT_plane_track_key_delete,
           CLIP_OT_plane_track_update, CLIP_OT_plane_track_keys_clear)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.CLIP_PT_plane_track.append(draw_plane_track_keys)


def unregister():
    bpy.types.CLIP_PT_plane_track.remove(draw_plane_track_keys)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
