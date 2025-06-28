# Authors (Original & Contributors):
# - Create Image Plane: Torbjörn Westerlund, Vladimir Spivak (cwolf3d) (from the Camera Image Plane for Blender 2.80+ addon)
# - Camera Projection Shader Concept: Nathan Vegdahl, Ian Hubert (from the Compify addon)


import bpy
import re
import math
from mathutils import Matrix
from bpy.types import Operator, Panel

# --- Helper Functions (No changes) ---
def create_projection_node_group(camera_obj):
    group_name = f"Camera Project | {camera_obj.name}"
    if group_name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[group_name])
    group = bpy.data.node_groups.new(name=group_name, type='ShaderNodeTree')
    group.interface.new_socket(name="Vector", in_out="OUTPUT", socket_type='NodeSocketVector')
    nodes = group.nodes; links = group.links
    col1, col2, col3, col4, col5, col6, col7, col8 = -600, -400, -200, 0, 250, 500, 750, 950
    tex_coord = nodes.new("ShaderNodeTexCoord"); tex_coord.label = "Camera Transform"; tex_coord.location = (col1, 200); tex_coord.object = camera_obj
    val_lens = nodes.new("ShaderNodeValue"); val_lens.label = "Lens"; val_lens.location = (col1, 0)
    val_sensor = nodes.new("ShaderNodeValue"); val_sensor.label = "Sensor Width"; val_sensor.location = (col1, -150)
    val_shift_x = nodes.new("ShaderNodeValue"); val_shift_x.label = "Lens Shift X"; val_shift_x.location = (col1, -300)
    val_shift_y = nodes.new("ShaderNodeValue"); val_shift_y.label = "Lens Shift Y"; val_shift_y.location = (col1, -450)
    val_resolution = nodes.new("ShaderNodeValue"); val_resolution.label = "Resolution"; val_resolution.location = (col1, -600)
    sep_xyz_persp = nodes.new("ShaderNodeSeparateXYZ"); sep_xyz_persp.label = "Perspective 1"; sep_xyz_persp.location = (col2, 200)
    math_zoom1 = nodes.new("ShaderNodeMath"); math_zoom1.label = "Zoom 1"; math_zoom1.operation = 'DIVIDE'; math_zoom1.location = (col2, 0)
    combo_shift1 = nodes.new("ShaderNodeCombineXYZ"); combo_shift1.label = "Lens Shift 1"; combo_shift1.location = (col2, -300)
    math_aspect_div = nodes.new("ShaderNodeMath"); math_aspect_div.label = "Divide"; math_aspect_div.operation = 'DIVIDE'; math_aspect_div.inputs[0].default_value = 1.0; math_aspect_div.location = (col2, -600)
    math_persp2 = nodes.new("ShaderNodeMath"); math_persp2.label = "Perspective 2"; math_persp2.operation = 'DIVIDE'; math_persp2.location = (col3, 250)
    math_persp3 = nodes.new("ShaderNodeMath"); math_persp3.label = "Perspective 3"; math_persp3.operation = 'DIVIDE'; math_persp3.location = (col3, 100)
    math_zoom2 = nodes.new("ShaderNodeMath"); math_zoom2.label = "Zoom 2"; math_zoom2.operation = 'MULTIPLY'; math_zoom2.inputs[1].default_value = -1.0; math_zoom2.location = (col3, 0)
    combo_persp4 = nodes.new("ShaderNodeCombineXYZ"); combo_persp4.label = "Perspective 4"; combo_persp4.location = (col4, 150)
    math_aspect_lt = nodes.new("ShaderNodeMath"); math_aspect_lt.label = "Less Than"; math_aspect_lt.operation = 'LESS_THAN'; math_aspect_lt.inputs[1].default_value = 1.0; math_aspect_lt.location = (col4, -450)
    combo_aspect1 = nodes.new("ShaderNodeCombineXYZ"); combo_aspect1.label = "Aspect Ratio 1"; combo_aspect1.inputs[0].default_value = 1.0; combo_aspect1.location = (col4, -600)
    combo_aspect2 = nodes.new("ShaderNodeCombineXYZ"); combo_aspect2.label = "Aspect Ratio 2"; combo_aspect2.inputs[1].default_value = 1.0; combo_aspect2.location = (col4, -750)
    mix_aspect_switch = nodes.new("ShaderNodeMix"); mix_aspect_switch.label = "Aspect Ratio Switch"; mix_aspect_switch.data_type = 'RGBA'; mix_aspect_switch.location = (col5, -600)
    vec_math_zoom3 = nodes.new("ShaderNodeVectorMath"); vec_math_zoom3.label = "Zoom 3"; vec_math_zoom3.operation = 'MULTIPLY'; vec_math_zoom3.location = (col5, 150)
    vec_math_shift2 = nodes.new("ShaderNodeVectorMath"); vec_math_shift2.label = "Lens Shift 2"; vec_math_shift2.operation = 'SUBTRACT'; vec_math_shift2.location = (col6, 100)
    vec_math_user_transforms = nodes.new("ShaderNodeVectorMath"); vec_math_user_transforms.label = "User Transforms"; vec_math_user_transforms.operation = 'MULTIPLY'; vec_math_user_transforms.location = (col7, 0)
    vec_math_recenter = nodes.new("ShaderNodeVectorMath"); vec_math_recenter.label = "Recenter"; vec_math_recenter.operation = 'ADD'; vec_math_recenter.inputs[1].default_value = (0.5, 0.5, 0.0); vec_math_recenter.location = (col8, 0)
    output_node = nodes.new('NodeGroupOutput'); output_node.location = (col8 + 200, 0)
    links.new(tex_coord.outputs['Object'], sep_xyz_persp.inputs['Vector']); links.new(sep_xyz_persp.outputs['X'], math_persp2.inputs[0]); links.new(sep_xyz_persp.outputs['Y'], math_persp3.inputs[0]); links.new(sep_xyz_persp.outputs['Z'], math_persp2.inputs[1]); links.new(sep_xyz_persp.outputs['Z'], math_persp3.inputs[1]); links.new(sep_xyz_persp.outputs['Z'], combo_persp4.inputs['Z']); links.new(math_persp2.outputs['Value'], combo_persp4.inputs['X']); links.new(math_persp3.outputs['Value'], combo_persp4.inputs['Y']); links.new(val_lens.outputs['Value'], math_zoom1.inputs[0]); links.new(val_sensor.outputs['Value'], math_zoom1.inputs[1]); links.new(math_zoom1.outputs['Value'], math_zoom2.inputs[0]); links.new(val_shift_x.outputs['Value'], combo_shift1.inputs['X']); links.new(val_shift_y.outputs['Value'], combo_shift1.inputs['Y']); links.new(val_resolution.outputs['Value'], math_aspect_div.inputs[1]); links.new(val_resolution.outputs['Value'], math_aspect_lt.inputs[0]); links.new(val_resolution.outputs['Value'], combo_aspect1.inputs['Y']); links.new(combo_persp4.outputs['Vector'], vec_math_zoom3.inputs[0]); links.new(math_zoom2.outputs['Value'], vec_math_zoom3.inputs[1]); links.new(math_aspect_div.outputs['Value'], combo_aspect2.inputs['X']); links.new(vec_math_zoom3.outputs['Vector'], vec_math_shift2.inputs[0]); links.new(combo_shift1.outputs['Vector'], vec_math_shift2.inputs[1]); links.new(math_aspect_lt.outputs['Value'], mix_aspect_switch.inputs[0]); links.new(combo_aspect1.outputs['Vector'], mix_aspect_switch.inputs[6]); links.new(combo_aspect2.outputs['Vector'], mix_aspect_switch.inputs[7]); links.new(mix_aspect_switch.outputs[2], vec_math_user_transforms.inputs[1]); links.new(vec_math_shift2.outputs['Vector'], vec_math_user_transforms.inputs[0]); links.new(vec_math_user_transforms.outputs['Vector'], vec_math_recenter.inputs[0]); links.new(vec_math_recenter.outputs['Vector'], output_node.inputs['Vector'])
    value_nodes_to_drive = {"lens": val_lens, "sensor": val_sensor, "shift_x": val_shift_x, "shift_y": val_shift_y, "resolution": val_resolution}
    setup_drivers_for_group(value_nodes_to_drive, camera_obj)
    return group

def setup_drivers_for_group(nodes_to_drive, camera_obj):
    def add_driver(node, data_path):
        driver = node.outputs[0].driver_add('default_value').driver; var = driver.variables.new(); var.name = "var"
        var.targets[0].id_type = 'CAMERA'; var.targets[0].id = camera_obj.data; var.targets[0].data_path = data_path
        driver.expression = "var"
    add_driver(nodes_to_drive["lens"], "lens"); add_driver(nodes_to_drive["sensor"], "sensor_width")
    add_driver(nodes_to_drive["shift_x"], "shift_x"); add_driver(nodes_to_drive["shift_y"], "shift_y")
    res_driver = nodes_to_drive["resolution"].outputs[0].driver_add('default_value').driver
    res_driver.expression = "res_x / res_y if res_y != 0 else 1.0"
    var_x = res_driver.variables.new(); var_x.name = "res_x"; var_x.targets[0].id_type = 'SCENE'; var_x.targets[0].id = bpy.context.scene; var_x.targets[0].data_path = "render.resolution_x"
    var_y = res_driver.variables.new(); var_y.name = "res_y"; var_y.targets[0].id_type = 'SCENE'; var_y.targets[0].id = bpy.context.scene; var_y.targets[0].data_path = "render.resolution_y"

# --- Operator Classes ---

class CLIP_OT_setup_camera_solver(Operator):
    bl_idname = "clip.setup_camera_solver"
    bl_label = "Setup Camera Solver"
    bl_description = "Adds a Camera Solver constraint to the active camera"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.camera and context.space_data and context.space_data.clip

    def execute(self, context):
        camera = context.scene.camera
        clip = context.space_data.clip

        # Check if a camera solver constraint already exists
        for c in camera.constraints:
            if c.type == 'CAMERA_SOLVER':
                self.report({'INFO'}, f"Camera Solver constraint already exists on '{camera.name}'.")
                return {'CANCELLED'}

        constraint = camera.constraints.new(type='CAMERA_SOLVER')
        constraint.clip = clip
        constraint.use_active_clip = False # Explicitly set to use the assigned clip
        
        self.report({'INFO'}, f"Added Camera Solver constraint to '{camera.name}' for clip '{clip.name}'.")
        return {'FINISHED'}


class CLIP_OT_setup_object_solver(Operator):
    bl_idname = "clip.setup_object_solver"
    bl_label = "Setup Object Solver"
    bl_description = "Adds an Object Solver constraint to the active object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.active_object:
            cls.poll_message_set("Requires an active object.")
            return False
        if not (context.space_data and context.space_data.clip):
            cls.poll_message_set("Requires an active clip in the editor.")
            return False
            
        active_track_obj = context.space_data.clip.tracking.objects.active
        if not active_track_obj:
            cls.poll_message_set("No active tracking object in the movie clip.")
            return False
        
        # 'Camera'という名前のトラッキングオブジェクトがアクティブな場合は実行しない
        if active_track_obj.name == "Camera":
            cls.poll_message_set("Cannot setup Object Solver when 'Camera' track is active.")
            return False
            
        return True

    def execute(self, context):
        active_obj = context.active_object
        clip = context.space_data.clip
        camera = context.scene.camera
        tracking_object = clip.tracking.objects.active
        constraint = None

        if not camera:
            self.report({'ERROR'}, "No active scene camera found. Operation cancelled.")
            return {'CANCELLED'}

        try:
            constraint = active_obj.constraints.new(type='OBJECT_SOLVER')
            constraint.clip = clip
            constraint.use_active_clip = False # Active Clipを無効にし、指定したクリップを使用するよう明示
            constraint.object = tracking_object.name # アクティブなトラッキングオブジェクトの名前を割り当てます
            constraint.camera = camera
            
            active_obj.location = (0.0, 0.0, 0.0)
            active_obj.rotation_euler = (0.0, 0.0, 0.0)

            self.report({'INFO'}, f"Object Solver configured for track '{tracking_object.name}'.")

        except Exception as e:
            self.report({'ERROR'}, f"Failed to set constraint: {e}")
            if constraint:
                active_obj.constraints.remove(constraint)
            return {'CANCELLED'}

        return {'FINISHED'}


class CLIP_OT_3d_markers_to_empty(Operator):
    bl_idname = "clip.3d_markers_to_empty"
    bl_label = "3D Markers to Empty"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        sc = context.space_data
        return sc and (sc.type == 'CLIP_EDITOR') and sc.clip
        
    def execute(self, context):
        sc = context.space_data
        clip = sc.clip
        tracking_object = clip.tracking.objects.active
        if not tracking_object:
            self.report({'ERROR'}, "No active tracking object found.")
            return {'CANCELLED'}
            
        scene = context.scene
        camera = scene.camera
        world_matrix = Matrix.Identity(4)
        
        if camera:
            reconstruction = tracking_object.reconstruction
            if reconstruction and reconstruction.is_valid:
                relative_frame = scene.frame_current - clip.frame_start + 1
                reconstructed_matrix = reconstruction.cameras.matrix_from_frame(frame=relative_frame)
                
                if reconstructed_matrix:
                    world_matrix = camera.matrix_world @ reconstructed_matrix.inverted()
        
        parent_empty = bpy.data.objects.new("Trackpoint", None)
        parent_empty.empty_display_type = 'PLAIN_AXES'
        parent_empty.empty_display_size = 1.0 
        context.collection.objects.link(parent_empty)

        created_empties = []
        for i, track in enumerate(tracking_object.tracks):
            if track.has_bundle and track.select:
                empty_name = f"Track_{i + 1:03}"
                empty = bpy.data.objects.new(empty_name, None)
                empty.empty_display_type = 'PLAIN_AXES'
                empty.location = world_matrix @ track.bundle
                context.collection.objects.link(empty)
                empty.parent = parent_empty
                created_empties.append(empty)
                
                d = empty.driver_add("empty_display_size").driver
                var = d.variables.new()
                var.name = "size"
                var.targets[0].id_type = 'OBJECT'
                var.targets[0].id = parent_empty
                var.targets[0].data_path = 'empty_display_size'
                d.expression = "size"

        parent_empty.location = (0, 0, 0)

        if not created_empties:
            if parent_empty.users == 1 and parent_empty.name in bpy.data.objects:
                bpy.data.objects.remove(parent_empty, do_unlink=True)
            self.report({'WARNING'}, "No selected tracks with 3D data found.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"{len(created_empties)} Empties created. Select 'Trackpoint' parent to change size via Object Data Properties.")
        return {'FINISHED'}

class CLIP_OT_set_start_frame_from_filename(bpy.types.Operator):
    bl_idname = "clip.set_start_frame_from_filename"; bl_label = "Set Start Seq No."; bl_description = "Sets clip start frame from a number in its name (e.g., 'clip.####.ext' or 'clip_####.ext')"; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        if context.area and context.area.type == 'CLIP_EDITOR': space = context.space_data; return space and hasattr(space, 'clip') and space.clip is not None
        return False
    def execute(self, context):
        clip = context.space_data.clip; name_to_parse = clip.name
        match = re.search(r"[._](\d{4,})\.", name_to_parse)
        if match:
            try: frame_start = int(match.group(1))
            except ValueError: self.report({'ERROR'}, f"Could not convert matched pattern '{match.group(1)}' to an integer."); return {'CANCELLED'}
            clip.frame_start = frame_start; bpy.ops.clip.set_scene_frames(); bpy.ops.screen.frame_jump(end=False)
            self.report({'INFO'}, f"Clip '{clip.name}': start frame set to {frame_start}. Scene frames updated.")
        else:
            self.report({'WARNING'}, f"No frame number pattern like '.####.' or '_####.' found in clip name: '{name_to_parse}'"); return {'CANCELLED'}
        return {'FINISHED'}

class CLIP_OT_duplicate_active_movieclip(bpy.types.Operator):
    bl_idname = "clip.duplicate_active_movieclip"; bl_label = "Duplicate Active Clip"; bl_description = "Creates a copy of the currently active Movie Clip data-block"; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        if context.area and context.area.type == 'CLIP_EDITOR': space = context.space_data; return space and hasattr(space, 'clip') and space.clip is not None
        return False
    def execute(self, context):
        space_clip = context.space_data; source_clip = space_clip.clip
        if source_clip is None: self.report({'WARNING'}, "No active Movie Clip to duplicate."); return {'CANCELLED'}
        try:
            new_clip = source_clip.copy(); space_clip.clip = new_clip
            self.report({'INFO'}, f"Movie Clip '{source_clip.name}' duplicated as '{new_clip.name}'. New clip is now active.")
        except Exception as e: self.report({'ERROR'}, f"Failed to duplicate Movie Clip: {e}"); return {'CANCELLED'}
        return {'FINISHED'}

class CLIP_OT_delete_active_movieclip(bpy.types.Operator):
    bl_idname = "clip.delete_active_movieclip"; bl_label = "Delete Active Clip"; bl_description = "Deletes the active Movie Clip. This action can be undone, but the data-block might be lost if not used elsewhere and the file is saved."; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        if context.area and context.area.type == 'CLIP_EDITOR':
            space = context.space_data; return space and hasattr(space, 'clip') and space.clip is not None
        return False
    def execute(self, context):
        space_clip = context.space_data; clip_to_delete = space_clip.clip
        if clip_to_delete is None: self.report({'WARNING'}, "No active Movie Clip to delete."); return {'CANCELLED'}
        clip_name = clip_to_delete.name
        try:
            space_clip.clip = None; bpy.data.movieclips.remove(clip_to_delete)
            self.report({'INFO'}, f"Movie Clip '{clip_name}' removed. Editor now has no active clip.")
        except Exception as e: self.report({'ERROR'}, f"Failed to delete Movie Clip '{clip_name}': {e}"); return {'CANCELLED'}
        return {'FINISHED'}

class CLIP_OT_create_image_plane_from_clip(bpy.types.Operator):
    bl_idname = "clip.create_image_plane_from_clip"
    bl_label = "Create Image Plane"
    bl_options = {'REGISTER', 'UNDO'}

    depth: bpy.props.FloatProperty(
        name="Depth",
        description="Distance from the camera",
        default=10.0,
        min=0.01,
        soft_max=100.0
    )

    @classmethod
    def poll(cls, context):
        has_camera = context.scene.camera is not None
        has_clip = context.space_data.clip is not None
        return has_camera and has_clip

    def setup_driver_variables(self, driver, imageplane, camera):
        # This helper function sets up all the variables a driver might need.
        scene = bpy.context.scene
        
        needed_vars = {
            'cA': ('CAMERA', "angle", camera.data),
            'cT': ('CAMERA', 'type', camera.data),
            'cSx': ('CAMERA', 'shift_x', camera.data),
            'cSy': ('CAMERA', 'shift_y', camera.data),
            'r_x': ('SCENE', 'render.resolution_x', scene),
            'r_y': ('SCENE', 'render.resolution_y', scene),
            'p_x': ('SCENE', 'render.pixel_aspect_x', scene),
            'p_y': ('SCENE', 'render.pixel_aspect_y', scene),
        }

        for name, (id_type, path, target_id) in needed_vars.items():
            if name not in driver.variables:
                var = driver.variables.new()
                var.name = name
                var.type = 'SINGLE_PROP'
                var.targets[0].id_type = id_type
                var.targets[0].id = target_id
                var.targets[0].data_path = path
        
        if 'depth' not in driver.variables:
            var = driver.variables.new()
            var.name = 'depth'
            var.type = 'TRANSFORMS'
            var.targets[0].id = imageplane
            var.targets[0].data_path = 'location'
            var.targets[0].transform_type = 'LOC_Z'
            var.targets[0].transform_space = 'LOCAL_SPACE'

        if 'scale_y' not in driver.variables:
            var = driver.variables.new()
            var.name = 'scale_y'
            var.type = 'SINGLE_PROP'
            var.targets[0].id = imageplane
            var.targets[0].data_path = 'scale[1]'

    def setup_drivers_for_image_plane(self, imageplane, camera):
        """Creates all necessary drivers for scale and location based on your perfected logic."""
        base_expr = "abs(depth) * tan(cA/2)"
        aspect_expr = "(r_y * p_y) / (r_x * p_x)"
        half_width_expr = f"({base_expr})"
        half_height_expr = f"({base_expr}) * {aspect_expr}"
        driver_x = imageplane.driver_add('scale', 0).driver
        driver_x.type = 'SCRIPTED'
        self.setup_driver_variables(driver_x, imageplane, camera)
        driver_x.expression = f"{half_width_expr} if cT == 0 else 0"
        driver_y = imageplane.driver_add('scale', 1).driver
        driver_y.type = 'SCRIPTED'
        self.setup_driver_variables(driver_y, imageplane, camera)
        driver_y.expression = f"{half_height_expr} if cT == 0 else 0"
        driver_loc_x = imageplane.driver_add('location', 0).driver
        driver_loc_x.type = 'SCRIPTED'
        self.setup_driver_variables(driver_loc_x, imageplane, camera)
        driver_loc_x.expression = f"cSx * 2 * {half_width_expr}"
        driver_loc_y = imageplane.driver_add('location', 1).driver
        driver_loc_y.type = 'SCRIPTED'
        self.setup_driver_variables(driver_loc_y, imageplane, camera)
        driver_loc_y.expression = f"cSy * 2 * scale_y * (r_x / r_y)"

    def get_frame_number_from_path(self, path):
        """Extracts the frame number from a file path."""
        match = re.search(r'(\d+)\.\w+$', path)
        if match:
            return int(match.group(1))
        return None

    def create_image_plane(self, context, camera, image):
        """Main function to create and configure the image plane."""
        try:
            scene = context.scene
            depth = self.depth 
            context.view_layer.objects.active = camera
            camera.select_set(True)
            bpy.ops.mesh.primitive_plane_add()
            imageplane = context.active_object
            imageplane.name = "ImagePlane_" + camera.name
            bpy.ops.object.parent_set(type='OBJECT', keep_transform=False)
            imageplane.parent = camera
            imageplane.location = (0, 0, -depth)
            self.setup_drivers_for_image_plane(imageplane, camera)
            material_name = 'mat_imageplane_' + image.name
            material = bpy.data.materials.get(material_name)
            if not material:
                material = bpy.data.materials.new(name=material_name)
                material.use_nodes = True
                material.node_tree.nodes.clear()
                tex_image = material.node_tree.nodes.new('ShaderNodeTexImage')
                emission = material.node_tree.nodes.new('ShaderNodeEmission')
                transparent = material.node_tree.nodes.new('ShaderNodeBsdfTransparent')
                mix_shader = material.node_tree.nodes.new('ShaderNodeMixShader')
                output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
                tex_image.location = (-300, 300)
                emission.location = (0, 300)
                transparent.location = (0, 0)
                mix_shader.location = (300, 200)
                output.location = (600, 200)
                links = material.node_tree.links
                links.new(tex_image.outputs['Color'], emission.inputs['Color'])
                links.new(tex_image.outputs['Alpha'], mix_shader.inputs['Fac'])
                links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
                links.new(emission.outputs['Emission'], mix_shader.inputs[2])
                links.new(mix_shader.outputs['Shader'], output.inputs['Surface'])
            
            if not imageplane.material_slots:
                imageplane.data.materials.append(material)
            else:
                imageplane.material_slots[0].material = material
            
            tex_image_node = material.node_tree.nodes.get("Image Texture")
            if tex_image_node:
                tex_image_node.image = image
                img_user = tex_image_node.image_user
                img_user.use_cyclic = True
                img_user.use_auto_refresh = True
                if image.source == 'SEQUENCE':
                    img_user.frame_duration = scene.frame_end - scene.frame_start + 1
                    first_frame = self.get_frame_number_from_path(image.filepath_raw)
                    if first_frame is not None:
                        offset = first_frame - 1
                        start_frame = scene.frame_start
                        img_user.frame_offset = offset
                        img_user.frame_start = start_frame
                    else:
                        img_user.frame_offset = 0
                        img_user.frame_start = scene.frame_start
                elif image.source == 'MOVIE':
                    img_user.frame_duration = scene.frame_end - scene.frame_start + 1
                    img_user.frame_offset = 0
                    img_user.frame_start = scene.frame_start
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Failed to create image plane: {e}")
            return {'CANCELLED'}
        
        context.view_layer.objects.active = imageplane
        imageplane.select_set(True)
        return {'FINISHED'}

    def execute(self, context):
        """Operator's main execution entry point."""
        clip = context.space_data.clip
        camera = context.scene.camera
        if not camera:
            self.report({'WARNING'}, "No active camera in the scene.")
            return {'CANCELLED'}
        try:
            image = bpy.data.images.load(clip.filepath, check_existing=True)
            if image.source == 'FILE':
                image.source = 'SEQUENCE'
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load image: {e}")
            return {'CANCELLED'}
        return self.create_image_plane(context, camera, image)

class PROJECTION_OT_setup_shader(bpy.types.Operator):
    bl_idname = "object.setup_projection_shader"; bl_label = "Set Cam Projection"; bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        active_obj = context.active_object
        if not active_obj: cls.poll_message_set("Please select an object"); return False
        if active_obj.type != 'MESH': cls.poll_message_set("Please select a MESH object"); return False
        if not context.scene.camera: cls.poll_message_set("Please set an active camera in the scene"); return False
        if not (hasattr(context.space_data, 'clip') and context.space_data.clip): cls.poll_message_set("Please open a clip in the Movie Clip Editor"); return False
        return True
    def get_frame_number_from_path(self, filepath):
        match = re.search(r'(\d+)\.\w+$', filepath);
        if match: return int(match.group(1))
        return None
    def execute(self, context):
        selected_obj = context.active_object; active_camera = context.scene.camera; movie_clip = context.space_data.clip; scene = context.scene
        try:
            image = bpy.data.images.load(movie_clip.filepath, check_existing=True)
            if image.source == 'FILE' and movie_clip.source == 'SEQUENCE': image.source = 'SEQUENCE'
        except Exception as e: self.report({'ERROR'}, f"Failed to load image from movie clip: {e}"); return {'CANCELLED'}
        projection_group = create_projection_node_group(active_camera)
        material_name = f"mat_projection_{selected_obj.name}"; material = bpy.data.materials.get(material_name)
        if not material: material = bpy.data.materials.new(name=material_name); material.use_nodes = True
        tree = material.node_tree; tree.nodes.clear(); links = tree.links
        proj_group_node = tree.nodes.new('ShaderNodeGroup'); proj_group_node.node_tree = projection_group; proj_group_node.location = (-500, 200)
        tex_image_node = tree.nodes.new('ShaderNodeTexImage'); tex_image_node.extension = 'EXTEND'; tex_image_node.location = (-250, 300)
        emission = tree.nodes.new('ShaderNodeEmission'); emission.location = (0, 300); transparent = tree.nodes.new('ShaderNodeBsdfTransparent'); transparent.location = (0, 100); mix_shader = tree.nodes.new('ShaderNodeMixShader'); mix_shader.location = (250, 200); output = tree.nodes.new('ShaderNodeOutputMaterial'); output.location = (500, 200)
        links.new(proj_group_node.outputs['Vector'], tex_image_node.inputs['Vector']); links.new(tex_image_node.outputs['Color'], emission.inputs['Color']); links.new(tex_image_node.outputs['Alpha'], mix_shader.inputs['Fac']); links.new(transparent.outputs['BSDF'], mix_shader.inputs[1]); links.new(emission.outputs['Emission'], mix_shader.inputs[2]); links.new(mix_shader.outputs['Shader'], output.inputs['Surface'])
        tex_image_node.image = image; img_user = tex_image_node.image_user; img_user.use_auto_refresh = True
        if image.source in {'SEQUENCE', 'MOVIE'}:
            img_user.use_cyclic = True; img_user.frame_duration = scene.frame_end - scene.frame_start + 1; img_user.frame_start = scene.frame_start
            if image.source == 'SEQUENCE': first_frame = self.get_frame_number_from_path(image.filepath_raw); img_user.frame_offset = first_frame - 1 if first_frame is not None else 0
            else: img_user.frame_offset = 0
        if selected_obj.data.materials: selected_obj.data.materials[0] = material
        else: selected_obj.data.materials.append(material)
        self.report({'INFO'}, f"Material '{material.name}' has been set up."); return {'FINISHED'}

# --- UI Panels ---
class CLIP_PT_tools_scenesetup(Panel):
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'TOOLS'
    bl_label = "Scene Setup"
    bl_category = "Solve"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sc = context.space_data
        return sc and sc.clip and sc.view == 'CLIP' and sc.mode != 'MASK'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("clip.set_viewport_background", icon='HIDE_OFF')
        col.operator("clip.setup_tracking_scene", icon='SCENE_DATA')
        col.separator()
        col.operator(CLIP_OT_setup_camera_solver.bl_idname, icon='CON_CAMERASOLVER')
        col.operator(CLIP_OT_setup_object_solver.bl_idname, icon='CON_OBJECTSOLVER')


# --- UI and Registration ---
def draw_button_for_3d_markers_to_empty_panel(self, context): self.layout.operator(CLIP_OT_3d_markers_to_empty.bl_idname, icon='EMPTY_AXIS')
def draw_menu_item_for_3d_markers_to_empty(self, context): self.layout.separator(); self.layout.operator(CLIP_OT_3d_markers_to_empty.bl_idname, icon='EMPTY_AXIS')
def draw_button_for_set_start_frame_panel(self, context): self.layout.operator(CLIP_OT_set_start_frame_from_filename.bl_idname)
def draw_menu_item_for_setup_solvers(self, context): self.layout.operator(CLIP_OT_setup_camera_solver.bl_idname, icon='CON_CAMERASOLVER'); self.layout.operator(CLIP_OT_setup_object_solver.bl_idname, icon='CON_OBJECTSOLVER'); self.layout.separator()
def draw_menu_item_for_duplicate_clip(self, context): self.layout.operator(CLIP_OT_duplicate_active_movieclip.bl_idname, icon='DUPLICATE')
def draw_menu_item_for_delete_clip(self, context): self.layout.operator(CLIP_OT_delete_active_movieclip.bl_idname, icon='TRASH')
def draw_button_for_create_image_plane(self, context): self.layout.operator(CLIP_OT_create_image_plane_from_clip.bl_idname, text="Create Image Plane", icon='FILE_IMAGE')
def draw_menu_item_for_create_image_plane(self, context): self.layout.operator(CLIP_OT_create_image_plane_from_clip.bl_idname, icon='FILE_IMAGE')
def draw_button_for_set_cam_projection_panel(self, context): self.layout.operator(PROJECTION_OT_setup_shader.bl_idname, text="Set Cam Projection", icon='MATERIAL')
def draw_menu_item_for_set_cam_projection(self, context): self.layout.separator(); self.layout.operator(PROJECTION_OT_setup_shader.bl_idname, icon='MATERIAL')

classes_to_register = (
    CLIP_OT_setup_camera_solver,
    CLIP_OT_setup_object_solver,
    CLIP_OT_3d_markers_to_empty, 
    CLIP_OT_set_start_frame_from_filename, 
    CLIP_OT_duplicate_active_movieclip,
    CLIP_OT_delete_active_movieclip, 
    CLIP_OT_create_image_plane_from_clip, 
    PROJECTION_OT_setup_shader,
    CLIP_PT_tools_scenesetup,
)

ui_additions = [
    ("CLIP_PT_tools_geometry", draw_button_for_3d_markers_to_empty_panel), 
    ("CLIP_PT_tools_geometry", draw_button_for_create_image_plane),
    ("CLIP_PT_tools_geometry", draw_button_for_set_cam_projection_panel),
    ("CLIP_PT_tools_clip", draw_button_for_set_start_frame_panel),
    ("CLIP_MT_reconstruction", draw_menu_item_for_3d_markers_to_empty),
    ("CLIP_MT_reconstruction", draw_menu_item_for_create_image_plane), 
    ("CLIP_MT_reconstruction", draw_menu_item_for_set_cam_projection),
    ("CLIP_MT_clip", draw_menu_item_for_setup_solvers),
    ("CLIP_MT_clip", draw_menu_item_for_duplicate_clip), 
    ("CLIP_MT_clip", draw_menu_item_for_delete_clip), 
]

def register():
    for cls in classes_to_register: bpy.utils.register_class(cls)
    for target_classname, draw_func in ui_additions:
        try:
            target_class = getattr(bpy.types, target_classname, None)
            if target_class: target_class.append(draw_func)
        except Exception as e: print(f"ERROR appending {draw_func.__name__} to {target_classname}: {e}")

def unregister():
    for target_classname, draw_func in ui_additions:
        try:
            target_class = getattr(bpy.types, target_classname, None)
            if target_class and hasattr(target_class, "remove"): target_class.remove(draw_func)
        except Exception: pass
    for cls in reversed(classes_to_register): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    try: unregister()
    except RuntimeError: pass
    register()