"""Shape-key tools for the Movie Clip Editor's mask toolbar."""

import ctypes
import struct

import bpy
from bpy.types import Operator

from .track_tools import (
    change_clip_editor_frame, find_neighbor_frame, key_navigation_context, redraw_clip_editors,
)


class _ListBase(ctypes.Structure):
    _fields_ = [("first", ctypes.c_void_p), ("last", ctypes.c_void_p)]


class _LayerHeader(ctypes.Structure):
    _fields_ = [
        ("next", ctypes.c_void_p), ("prev", ctypes.c_void_p),
        ("name", ctypes.c_char * 64), ("splines", _ListBase), ("shapes", _ListBase),
    ]


class _ShapeHeader(ctypes.Structure):
    _fields_ = [
        ("next", ctypes.c_void_p), ("prev", ctypes.c_void_p),
        ("data", ctypes.c_void_p), ("tot_vert", ctypes.c_int),
        ("frame", ctypes.c_int), ("flag", ctypes.c_ubyte), ("pad", ctypes.c_char * 7),
    ]


def mask_key_access_supported():
    return ctypes.sizeof(ctypes.c_void_p) == 8 and (4, 2) <= bpy.app.version[:2] < (5, 3)


def mask_layer_key_frames(layer):
    # Shape keys are not exposed by RNA. Read the verified DNA_mask_types.h
    # headers only; every modification goes through native mask operators.
    if not mask_key_access_supported():
        raise RuntimeError("Mask key access is not verified for this Blender version")
    header = _LayerHeader.from_buffer_copy(ctypes.string_at(layer.as_pointer(), ctypes.sizeof(_LayerHeader)))
    splines = list(layer.splines)
    if (bytes(header.name) != layer.name.encode('utf-8')
            or header.splines.first != (splines[0].as_pointer() if splines else None)
            or header.splines.last != (splines[-1].as_pointer() if splines else None)
            or bool(header.shapes.first) != bool(header.shapes.last)):
        raise RuntimeError("Mask layer layout validation failed; no data was changed")
    frames = []
    seen = set()
    previous = None
    pointer = header.shapes.first
    total = sum(len(spline.points) for spline in splines)
    while pointer:
        if pointer in seen or pointer < 65536 or pointer % 8 or len(seen) >= 1000000:
            raise RuntimeError("Mask shape list validation failed")
        seen.add(pointer)
        shape = _ShapeHeader.from_buffer_copy(ctypes.string_at(pointer, ctypes.sizeof(_ShapeHeader)))
        if (shape.prev != previous or shape.tot_vert != total or not shape.data
                or shape.flag & ~1 or not -1048574 <= shape.frame <= 1048574
                or (frames and shape.frame <= frames[-1])):
            raise RuntimeError("Mask shape layout validation failed; no data was changed")
        frames.append(shape.frame)
        previous, pointer = pointer, shape.next
    if previous != header.shapes.last:
        raise RuntimeError("Mask shape list validation failed")
    return frames


def mask_point_selected(point):
    if hasattr(point, "select_control_point"):
        return point.select_control_point or point.select_left_handle or point.select_right_handle
    # Older RNA exposes only the left handle. Validate the shared BezTriple
    # coordinate prefix before reading the other two selection flags.
    data = struct.unpack("=12f6B", ctypes.string_at(point.as_pointer(), 54))
    if (data[:2] != tuple(point.handle_left) or data[3:5] != tuple(point.co)
            or data[6:8] != tuple(point.handle_right) or bool(data[-3] & 1) != point.select):
        raise RuntimeError("Mask point layout validation failed")
    return any(flag & 1 for flag in data[-3:])


def selected_mask_layers(mask):
    return [layer for layer in mask.layers if not layer.hide and not layer.hide_select
            and any(mask_point_selected(point)
                    for spline in layer.splines for point in spline.points)]


def mask_tools_poll(cls, context):
    space = getattr(context, "space_data", None)
    if not space or space.type != 'CLIP_EDITOR' or space.mode != 'MASK' or not space.mask:
        return False
    if not mask_key_access_supported():
        cls.poll_message_set("Mask key access is not verified for this Blender version")
        return False
    try:
        selected = selected_mask_layers(space.mask)
    except RuntimeError as error:
        cls.poll_message_set(str(error))
        return False
    if not selected:
        cls.poll_message_set("Select a point in an editable mask layer")
        return False
    return True


def refresh_mask(context):
    space = context.space_data
    frame, subframe = context.scene.frame_current, context.scene.frame_subframe
    space.mask.update_tag()
    if space.clip:
        space.clip_user.frame_current = context.scene.frame_current
        change_clip_editor_frame(context, space.clip, context.scene.frame_current)
        if context.scene.frame_subframe != subframe:
            context.scene.frame_set(frame, subframe=subframe)
    redraw_clip_editors(context)
    for area in context.screen.areas:
        if area.type in {'DOPESHEET_EDITOR', 'IMAGE_EDITOR', 'TIMELINE'}:
            area.tag_redraw()


def jump_mask_key(context, direction, report):
    try:
        frames = [frame for layer in selected_mask_layers(context.space_data.mask)
                  for frame in mask_layer_key_frames(layer)]
    except RuntimeError as error:
        report({'WARNING'}, str(error))
        return {'CANCELLED'}
    # Mask shape keys use scene frames, independent of footage start/offset.
    current = context.scene.frame_current + context.scene.frame_subframe
    target = find_neighbor_frame(frames, current, direction)
    if target is None:
        report({'INFO'}, "No mask shape keyframe found in that direction")
        return {'CANCELLED'}
    context.scene.frame_set(target)
    refresh_mask(context)
    return {'FINISHED'}


class MASK_OT_clip_tools_key_previous(Operator):
    bl_idname = "mask.clip_tools_key_previous"
    bl_label = "Previous Mask Key"
    bl_description = "Jump to the previous shape key on mask layers containing selected points"

    @classmethod
    def poll(cls, context):
        return mask_tools_poll(cls, context)

    def execute(self, context):
        return jump_mask_key(context, 'PREVIOUS', self.report)


class MASK_OT_clip_tools_key_next(Operator):
    bl_idname = "mask.clip_tools_key_next"
    bl_label = "Next Mask Key"
    bl_description = "Jump to the next shape key on mask layers containing selected points"

    @classmethod
    def poll(cls, context):
        return mask_tools_poll(cls, context)

    def execute(self, context):
        return jump_mask_key(context, 'NEXT', self.report)


class MASK_OT_clip_tools_keys_clear(Operator):
    bl_idname = "mask.clip_tools_keys_clear"
    bl_label = "Clear All Mask Keys"
    bl_description = "Remove all shape keys from mask layers containing selected points"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return mask_tools_poll(cls, context) and bpy.ops.mask.shape_key_clear.poll()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        mask = context.space_data.mask
        if not mask.is_editable:
            self.report({'WARNING'}, "The mask is not editable")
            return {'CANCELLED'}
        layers = selected_mask_layers(mask)
        try:
            frames = sorted({frame for layer in layers for frame in mask_layer_key_frames(layer)})
        except RuntimeError as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        if not frames:
            self.report({'INFO'}, "The selected mask layers have no shape keyframes")
            return {'CANCELLED'}
        scene = context.scene
        original_frame, original_subframe = scene.frame_current, scene.frame_subframe
        points = [(point, tuple(point.handle_left), tuple(point.co), tuple(point.handle_right), point.weight)
                  for layer in layers for spline in layer.splines for point in spline.points]
        cleared = 0
        error = None
        try:
            # Native clear reads cfra directly. Do not evaluate intermediate
            # frames, which would replace the displayed spline before clearing.
            for frame in frames:
                scene.frame_current = frame
                if bpy.ops.mask.shape_key_clear() != {'FINISHED'}:
                    raise RuntimeError("Blender could not remove a mask shape key")
                cleared += 1
        except RuntimeError as caught:
            error = caught
        finally:
            scene.frame_current = original_frame
            scene.frame_subframe = original_subframe
            for point, left, co, right, weight in points:
                point.co = co
                point.handle_left = left
                point.handle_right = right
                point.weight = weight
            refresh_mask(context)
        if error:
            self.report({'WARNING'}, f"Mask key clearing incomplete. {error}")
            return {'FINISHED'} if cleared else {'CANCELLED'}
        self.report({'INFO'}, "Cleared all shape keys from the selected mask layers")
        return {'FINISHED'}


def draw_mask_keys(self, context):
    row = self.layout.row(align=True)
    row.use_property_split = False
    row.operator_context = 'EXEC_DEFAULT'
    row.label(text="Keyframe:")
    navigation = row.row(align=True)
    navigation.scale_x = 1.25
    navigation.operator_context = key_navigation_context(context)
    navigation.operator("clip.jump_selected_track_key_previous", text="", icon='PREV_KEYFRAME')
    navigation.operator("clip.jump_selected_track_key_next", text="", icon='NEXT_KEYFRAME')
    row.operator_context = 'INVOKE_DEFAULT'
    row.operator(MASK_OT_clip_tools_keys_clear.bl_idname, text="", icon='TRASH')


classes = (MASK_OT_clip_tools_key_previous, MASK_OT_clip_tools_key_next, MASK_OT_clip_tools_keys_clear)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.CLIP_PT_tools_mask_tools.append(draw_mask_keys)


def unregister():
    bpy.types.CLIP_PT_tools_mask_tools.remove(draw_mask_keys)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
