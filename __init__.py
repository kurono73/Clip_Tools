# Scene Duration Display


import bpy
from bpy.props import IntProperty
from bpy.app.handlers import persistent

# --- Globals ---
is_self_updating = False
msgbus_owner = object()

# --- Operators ---
class SCENE_OT_set_preview_in(bpy.types.Operator):
    """Set current frame as Preview Range Start and enable Preview Range"""
    bl_idname = "scene.set_preview_in"
    bl_label = "Set Preview In (I)"
    bl_description = "Enable Preview Range and set its start to the current frame"

    def execute(self, context):
        scene = context.scene
        scene.use_preview_range = True
        scene.frame_preview_start = scene.frame_current
        if scene.frame_preview_end < scene.frame_preview_start:
            scene.frame_preview_end = scene.frame_preview_start
        self.report({'INFO'}, f"Preview Range In set to {scene.frame_preview_start}")
        return {'FINISHED'}


class SCENE_OT_set_preview_out(bpy.types.Operator):
    """Set current frame as Preview Range End and enable Preview Range"""
    bl_idname = "scene.set_preview_out"
    bl_label = "Set Preview Out (O)"
    bl_description = "Enable Preview Range and set its end to the current frame"

    def execute(self, context):
        scene = context.scene
        scene.use_preview_range = True
        scene.frame_preview_end = scene.frame_current
        if scene.frame_preview_start > scene.frame_preview_end:
            scene.frame_preview_start = scene.frame_preview_end
        self.report({'INFO'}, f"Preview Range Out set to {scene.frame_preview_end}")
        return {'FINISHED'}

# --- Core Logic ---
def update_timeline_duration_from_scene(scene):
    global is_self_updating
    if not scene or is_self_updating:
        return

    is_self_updating = True
    try:
        if not hasattr(scene, "timeline_duration"):
            return
        start_f, end_f = (scene.frame_preview_start, scene.frame_preview_end) if scene.use_preview_range else (scene.frame_start, scene.frame_end)
        new_duration = max(1, end_f - start_f + 1)
        if scene.timeline_duration != new_duration:
            scene.timeline_duration = new_duration
    except Exception as e:
        print(f"[Scene Duration Display] update error: {e}")
    finally:
        is_self_updating = False

def duration_prop_update(self, context):
    global is_self_updating
    if is_self_updating:
        return
    is_self_updating = True
    try:
        scene = self
        duration = max(1, scene.timeline_duration)
        scene.timeline_duration = duration
        if scene.use_preview_range:
            scene.frame_preview_end = scene.frame_preview_start + duration - 1
        else:
            scene.frame_end = scene.frame_start + duration - 1
    except Exception as e:
        print(f"[Scene Duration Display] duration update error: {e}")
    finally:
        is_self_updating = False

def scene_properties_changed_via_msgbus():
    if bpy.context.scene:
        update_timeline_duration_from_scene(bpy.context.scene)

@persistent
def depsgraph_scene_update_callback(scene_from_handler, depsgraph):
    if scene_from_handler == bpy.context.scene:
        update_timeline_duration_from_scene(scene_from_handler)

def initial_sync_after_register():
    global is_self_updating
    original = is_self_updating
    is_self_updating = False
    try:
        if bpy.context.scene:
            update_timeline_duration_from_scene(bpy.context.scene)
    except Exception as e:
        print(f"[Scene Duration Display] initial sync error: {e}")
    finally:
        is_self_updating = original
    return None

@persistent
def on_file_loaded_callback(dummy):
    global msgbus_owner
    bpy.msgbus.clear_by_owner(msgbus_owner)
    msgbus_owner = object()

    props = ["frame_start", "frame_end", "use_preview_range", "frame_preview_start", "frame_preview_end"]
    for prop in props:
        key = (bpy.types.Scene, prop)
        bpy.msgbus.subscribe_rna(
            key=key,
            owner=msgbus_owner,
            args=(),
            notify=scene_properties_changed_via_msgbus,
        )

    if not hasattr(bpy.types.Scene, "timeline_duration"):
        bpy.types.Scene.timeline_duration = IntProperty(
            name="Duration",
            default=100,
            min=1,
            update=duration_prop_update,
        )

    if bpy.app.timers.is_registered(initial_sync_after_register):
        bpy.app.timers.unregister(initial_sync_after_register)
    bpy.app.timers.register(initial_sync_after_register, first_interval=0.1)

# --- UI ---
def draw_duration_in_header(self, context):
    space = context.space_data
    if space.type != 'DOPESHEET_EDITOR' or space.mode != 'TIMELINE':
        return

    layout = self.layout
    scene = context.scene
    if not scene:
        return

    layout.separator(factor=1.0)
    row = layout.row(align=True)
    row.operator(SCENE_OT_set_preview_in.bl_idname, text="I<")
    row.prop(scene, "timeline_duration", text="")
    row.operator(SCENE_OT_set_preview_out.bl_idname, text=">O")

# --- Registration ---
classes = (SCENE_OT_set_preview_in, SCENE_OT_set_preview_out)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.timeline_duration = IntProperty(
        name="Duration",
        default=100,
        min=1,
        update=duration_prop_update,
    )

    bpy.app.handlers.load_post.append(on_file_loaded_callback)
    bpy.app.handlers.depsgraph_update_post.append(depsgraph_scene_update_callback)

    bpy.types.DOPESHEET_HT_header.append(draw_duration_in_header)

    bpy.app.timers.register(initial_sync_after_register, first_interval=0.01)

def unregister():
    if bpy.app.timers.is_registered(initial_sync_after_register):
        bpy.app.timers.unregister(initial_sync_after_register)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    bpy.msgbus.clear_by_owner(msgbus_owner)

    if on_file_loaded_callback in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_file_loaded_callback)

    if depsgraph_scene_update_callback in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_scene_update_callback)

    try:
        bpy.types.DOPESHEET_HT_header.remove(draw_duration_in_header)
    except Exception:
        pass

    if hasattr(bpy.types.Scene, "timeline_duration"):
        del bpy.types.Scene.timeline_duration

# For reloading in text editor
if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()
