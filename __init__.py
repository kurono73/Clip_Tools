# Clip_Tools

# Authors (Original & Contributors):
# - Create Image Plane: Torbjörn Westerlund, Vladimir Spivak (cwolf3d) (from the Camera Image Plane for Blender 2.80+ addon)
# - Camera Projection Shader Concept: Nathan Vegdahl, Ian Hubert (from the Compify addon)


import bpy
import importlib
import re
import math
from mathutils import Matrix, Vector
from bpy.types import Operator, Panel
from . import track_tools
from . import plane_track_tools
from . import track_bridge_preview
from . import mask_tools

importlib.reload(track_tools)
importlib.reload(plane_track_tools)
importlib.reload(track_bridge_preview)
importlib.reload(mask_tools)

# --- Helper Functions ---

def is_clip_editor_with_active_clip(context):
    """Checks if the context is the Clip Editor with an active clip."""
    space = context.space_data
    return space and space.type == 'CLIP_EDITOR' and space.clip is not None

def get_frame_number_from_path(filepath):
    """Extracts the frame number sequence from the end of a filepath string."""
    if not filepath:
        return None

    filename = re.split(r'[\\/]', filepath)[-1]
    if not filename:
        return None

    # Ignore Blender data-block suffixes such as "plate_1001.jpg.001" when a
    # file path is not available and a name must be used as fallback.
    datablock_suffix = re.search(r'\.(\d{3})$', filename)
    if datablock_suffix and re.search(r'\.[A-Za-z][A-Za-z0-9]*\.\d{3}$', filename):
        filename = filename[:datablock_suffix.start()]
    stem = re.sub(r'\.[^.]*$', '', filename)
    match = re.search(r'(\d+)$', stem)
    return int(match.group(1)) if match else None

def set_clip_scene_frames(jump_to_start=True):
    bpy.ops.clip.set_scene_frames()
    if jump_to_start:
        bpy.ops.screen.frame_jump(end=False)

def constraint_uses_clip(constraint, clip):
    if constraint.type not in {'CAMERA_SOLVER', 'OBJECT_SOLVER'}:
        return False
    return constraint.use_active_clip or constraint.clip == clip

def get_camera_with_movieclip(context, clip):
    def camera_uses_movieclip(obj):
        return (
            obj and
            obj.type == 'CAMERA' and
            any(constraint_uses_clip(con, clip) for con in obj.constraints)
        )

    scene_camera = context.scene.camera
    if camera_uses_movieclip(scene_camera):
        return scene_camera

    for obj in bpy.data.objects:
        if camera_uses_movieclip(obj):
            return obj

    return None

def get_orientation_plus_object(context, clip, tracking_object):
    if tracking_object.is_camera:
        obj = get_camera_with_movieclip(context, clip)
    else:
        obj = context.view_layer.objects.active

    if obj and obj.parent:
        return obj.parent
    return obj

def get_clip_reconstruction_world_matrix(context, clip, tracking_object, camera=None):
    """Returns the matrix that maps reconstructed bundles into the scene."""
    camera = camera or get_camera_with_movieclip(context, clip)
    if not camera:
        return Matrix.Identity(4)

    reconstruction = tracking_object.reconstruction
    if not reconstruction or not reconstruction.is_valid:
        return Matrix.Identity(4)

    relative_frame = context.scene.frame_current - clip.frame_start + 1
    reconstructed_matrix = reconstruction.cameras.matrix_from_frame(frame=relative_frame)
    if not reconstructed_matrix:
        return Matrix.Identity(4)

    return camera.matrix_world @ reconstructed_matrix.inverted()

def get_selected_reconstructed_points(context, camera=None):
    """Gets selected reconstructed track bundle positions in world space."""
    clip = context.space_data.clip
    tracking_object = clip.tracking.objects.active
    if not tracking_object:
        return []

    world_matrix = get_clip_reconstruction_world_matrix(context, clip, tracking_object, camera)
    return [
        world_matrix @ track.bundle
        for track in tracking_object.tracks
        if track.select and track.has_bundle
    ]

def get_orientation_object_base_world_matrix(obj):
    if obj.parent:
        return obj.parent.matrix_world @ obj.matrix_basis
    return obj.matrix_basis.copy()

def get_evaluated_reconstructed_points(context, clip, tracking_object, camera, orientation_object, frame=None):
    """Gets selected reconstructed points using solved object matrices at the requested frame."""
    scene = context.scene
    original_frame = scene.frame_current
    if frame is not None and original_frame != frame:
        scene.frame_set(frame)

    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        camera_matrix = camera.evaluated_get(depsgraph).matrix_world.copy()
        orientation_matrix = get_orientation_object_base_world_matrix(orientation_object)
        reconstruction = tracking_object.reconstruction
        reconstructed_matrix = None
        if reconstruction and reconstruction.is_valid:
            relative_frame = scene.frame_current - clip.frame_start + 1
            reconstructed_matrix = reconstruction.cameras.matrix_from_frame(frame=relative_frame)

        if not reconstructed_matrix:
            return None, camera_matrix, orientation_matrix

        world_matrix = camera_matrix @ reconstructed_matrix.inverted()

        points = [
            world_matrix @ track.bundle
            for track in tracking_object.tracks
            if track.select and track.has_bundle
        ]
    finally:
        if frame is not None and original_frame != frame:
            scene.frame_set(original_frame)
            context.view_layer.update()

    return points, camera_matrix, orientation_matrix

def median_scalar(values):
    values = sorted(values)
    count = len(values)
    middle = count // 2
    if count % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) * 0.5

def reduce_points(points, method):
    if method == 'MEDIAN':
        return Vector((
            median_scalar([point.x for point in points]),
            median_scalar([point.y for point in points]),
            median_scalar([point.z for point in points]),
        ))

    center = Vector((0.0, 0.0, 0.0))
    for point in points:
        center += point
    return center / len(points)

def fit_plane_normal(points, center):
    seed = None
    for i in range(len(points) - 2):
        a = points[i] - center
        for j in range(i + 1, len(points) - 1):
            b = points[j] - center
            for k in range(j + 1, len(points)):
                c = points[k] - center
                normal = (b - a).cross(c - a)
                if normal.length > 1.0e-8:
                    seed = normal.normalized()
                    break
            if seed:
                break
        if seed:
            break

    if not seed:
        return None

    normal_sum = Vector((0.0, 0.0, 0.0))
    for i in range(len(points) - 1):
        a = points[i] - center
        for j in range(i + 1, len(points)):
            normal = a.cross(points[j] - center)
            if normal.length <= 1.0e-8:
                continue
            if normal.dot(seed) < 0.0:
                normal.negate()
            normal_sum += normal

    if normal_sum.length <= 1.0e-8:
        return seed
    return normal_sum.normalized()

def orient_normal_toward_camera(normal, point_on_plane, camera_matrix):
    camera_direction = camera_matrix.translation - point_on_plane
    if camera_direction.length <= 1.0e-8:
        return normal.normalized()

    normal = normal.normalized()
    if normal.dot(camera_direction) < 0.0:
        normal.negate()
    return normal

def translate_orientation_object_world(obj, delta):
    if obj.parent:
        local_delta = obj.parent.matrix_world.inverted().to_3x3() @ delta
    else:
        local_delta = delta
    obj.location += local_delta

def set_orientation_object_world_matrix(obj, matrix):
    if obj.parent:
        obj.matrix_basis = obj.parent.matrix_world.inverted() @ matrix
    else:
        obj.matrix_basis = matrix

def transform_orientation_object(obj, transform, base_matrix=None):
    matrix = base_matrix if base_matrix is not None else obj.matrix_world.copy()
    set_orientation_object_world_matrix(obj, transform @ matrix)

def get_orientation_plus_axis(settings, camera):
    # Wall labels describe the camera-facing side; the solver uses the opposite plane normal.
    axes = {
        'Z_POS': Vector((0.0, 0.0, 1.0)),
        'Z_NEG': Vector((0.0, 0.0, -1.0)),
        'X_POS': Vector((-1.0, 0.0, 0.0)),
        'X_NEG': Vector((1.0, 0.0, 0.0)),
        'Y_POS': Vector((0.0, -1.0, 0.0)),
        'Y_NEG': Vector((0.0, 1.0, 0.0)),
    }

    return axes[settings.contact_direction]

def get_orientation_plus_coordinate(settings, scene):
    if settings.coordinate_source == 'ORIGIN':
        return Vector((0.0, 0.0, 0.0))
    if settings.coordinate_source == 'CURSOR':
        return scene.cursor.location.copy()
    return Vector(settings.contact_origin)

def get_orientation_plus_target_point(settings, scene, camera_matrix):
    input_point = get_orientation_plus_coordinate(settings, scene)
    if settings.origin_source == 'CAMERA_POSITION':
        return Vector((0.0, 0.0, input_point.z))
    return input_point

def signed_angle_around_axis(from_vec, to_vec, axis):
    axis = axis.normalized()
    from_vec = (from_vec - axis * from_vec.dot(axis))
    to_vec = (to_vec - axis * to_vec.dot(axis))
    if from_vec.length <= 1.0e-8 or to_vec.length <= 1.0e-8:
        return 0.0
    from_vec.normalize()
    to_vec.normalize()
    return math.atan2(axis.dot(from_vec.cross(to_vec)), from_vec.dot(to_vec))

def basis_from_normal_and_reference(normal, reference):
    normal = normal.normalized()
    tangent = reference - normal * reference.dot(normal)
    if tangent.length <= 1.0e-8:
        fallback = Vector((1.0, 0.0, 0.0))
        if abs(fallback.dot(normal)) > 0.95:
            fallback = Vector((0.0, 1.0, 0.0))
        tangent = fallback - normal * fallback.dot(normal)
    tangent.normalize()
    bitangent = normal.cross(tangent).normalized()
    return Matrix((tangent, bitangent, normal)).transposed()

def get_floor_rotation_preserve_view(source_normal, target_normal, camera_matrix):
    view_axis = camera_matrix.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    source_basis = basis_from_normal_and_reference(source_normal, view_axis)
    target_basis = basis_from_normal_and_reference(target_normal, view_axis)
    return (target_basis @ source_basis.inverted()).to_quaternion()

def get_orientation_plus_rotation(source_normal, target_normal, camera_matrix):
    world_z = Vector((0.0, 0.0, 1.0))
    target_normal = target_normal.normalized()
    source_normal = source_normal.normalized()

    if abs(target_normal.dot(world_z)) > 0.999:
        if source_normal.dot(target_normal) > 0.999:
            return Matrix.Identity(4).to_quaternion()
        return get_floor_rotation_preserve_view(source_normal, target_normal, camera_matrix)

    projected_source = Vector((source_normal.x, source_normal.y, 0.0))
    if projected_source.length <= 1.0e-8:
        return source_normal.rotation_difference(target_normal)

    yaw = signed_angle_around_axis(projected_source, target_normal, world_z)
    yaw_rotation = Matrix.Rotation(yaw, 4, world_z)
    yawed_normal = (yaw_rotation.to_3x3() @ source_normal).normalized()
    wall_axis = world_z.cross(target_normal)
    if wall_axis.length <= 1.0e-8:
        return yaw_rotation.to_quaternion()

    tilt = signed_angle_around_axis(yawed_normal, target_normal, wall_axis)
    tilt_rotation = Matrix.Rotation(tilt, 4, wall_axis.normalized())
    return (tilt_rotation @ yaw_rotation).to_quaternion()

def solve_two_point_plane_angle(points, target_normal, camera_matrix, prefer_camera_view=False):
    world_z = Vector((0.0, 0.0, 1.0))
    target_normal = target_normal.normalized()
    camera_rotation = camera_matrix.to_quaternion()

    if abs(target_normal.dot(world_z)) > 0.999:
        axis = camera_rotation @ Vector((1.0, 0.0, 0.0))
        view_axis = camera_rotation @ Vector((0.0, 0.0, -1.0))
        point_delta = points[1] - points[0]
        depth_delta = abs(point_delta.dot(view_axis.normalized()))
        if depth_delta < max(1.0e-3, point_delta.length * 0.05):
            if target_normal.z < 0.0:
                return math.pi, axis, True
            return 0.0, axis, True
    else:
        axis = world_z.copy()

    if axis.length <= 1.0e-8:
        return 0.0, axis, False

    axis.normalize()
    delta = points[1] - points[0]
    a = target_normal.dot(delta)
    b = target_normal.dot(axis.cross(delta))
    c = target_normal.dot(axis) * axis.dot(delta)
    p = a - c
    radius = math.hypot(p, b)

    if radius <= 1.0e-8:
        return 0.0, axis, False

    value = max(-1.0, min(1.0, -c / radius))
    base = math.atan2(b, p)
    option_a = base + math.acos(value)
    option_b = base - math.acos(value)

    def wrap_angle(angle):
        return (angle + math.pi) % (math.tau) - math.pi

    options = [wrap_angle(option_a), wrap_angle(option_b)]

    def score_angle(angle):
        pivot = camera_matrix.translation
        rotation = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, axis) @ Matrix.Translation(-pivot)
        rotated_points = [rotation @ point for point in points]
        if prefer_camera_view:
            rotated_camera = rotation @ camera_matrix
            view_axis = rotated_camera.to_quaternion() @ Vector((0.0, 0.0, -1.0))
            view_axis.z = 0.0
            if view_axis.length <= 1.0e-8:
                return (-2.0, -abs(angle))
            view_axis.normalize()
            return ((-view_axis).dot(target_normal), -abs(angle))
        else:
            center = reduce_points(rotated_points, 'MEAN')
            normal = get_two_point_visible_normal(rotated_points, center, camera_matrix)
            if not normal:
                return (-2.0, -abs(angle))
            return (normal.dot(target_normal), -abs(angle))

    angle = max(options, key=score_angle)
    return angle, axis, False

def get_two_point_visible_normal(points, center, camera_matrix):
    line = points[1] - points[0]
    camera_ray = center - camera_matrix.translation
    if line.length <= 1.0e-8 or camera_ray.length <= 1.0e-8:
        return None
    normal = line.cross(camera_ray)
    if normal.length <= 1.0e-8:
        return None
    return orient_normal_toward_camera(normal, center, camera_matrix)

def get_one_point_wall_rotation(target_normal, camera_matrix):
    world_z = Vector((0.0, 0.0, 1.0))
    target_normal = target_normal.normalized()
    if abs(target_normal.dot(world_z)) > 0.999:
        return Matrix.Identity(4).to_quaternion()

    view_axis = camera_matrix.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    projected_view = view_axis - world_z * view_axis.dot(world_z)
    if projected_view.length <= 1.0e-8:
        return Matrix.Identity(4).to_quaternion()

    angle = signed_angle_around_axis(projected_view, -target_normal, world_z)
    return Matrix.Rotation(angle, 4, world_z).to_quaternion()

def get_one_point_floor_rotation(target_normal, camera_matrix):
    world_z = Vector((0.0, 0.0, 1.0))
    target_normal = target_normal.normalized()
    if target_normal.z >= 0.0:
        return Matrix.Identity(4).to_quaternion()

    view_axis = camera_matrix.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    flip_axis = view_axis - world_z * view_axis.dot(world_z)
    if flip_axis.length <= 1.0e-8:
        flip_axis = camera_matrix.to_quaternion() @ Vector((1.0, 0.0, 0.0))
        flip_axis = flip_axis - world_z * flip_axis.dot(world_z)
    if flip_axis.length <= 1.0e-8:
        flip_axis = Vector((1.0, 0.0, 0.0))
    return Matrix.Rotation(math.pi, 4, flip_axis.normalized()).to_quaternion()

def create_projection_node_group(camera_obj):
    """
    Creates a shader node group for camera projection.
    If a group for the given camera already exists, it will be replaced.
    """
    group_name = f"Camera Project | {camera_obj.name}"
    if group_name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[group_name])
        
    group = bpy.data.node_groups.new(name=group_name, type='ShaderNodeTree')
    group.interface.new_socket(name="Vector", in_out="OUTPUT", socket_type='NodeSocketVector')
    
    nodes = group.nodes
    links = group.links
    
    # Node layout columns
    col1, col2, col3, col4, col5, col6, col7, col8 = -600, -400, -200, 0, 250, 500, 750, 950

    # Node creation (Layout remains improved for readability)
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
    
    # Linking nodes
    links.new(tex_coord.outputs['Object'], sep_xyz_persp.inputs['Vector']); links.new(sep_xyz_persp.outputs['X'], math_persp2.inputs[0]); links.new(sep_xyz_persp.outputs['Y'], math_persp3.inputs[0]); links.new(sep_xyz_persp.outputs['Z'], math_persp2.inputs[1]); links.new(sep_xyz_persp.outputs['Z'], math_persp3.inputs[1]); links.new(sep_xyz_persp.outputs['Z'], combo_persp4.inputs['Z']); links.new(math_persp2.outputs['Value'], combo_persp4.inputs['X']); links.new(math_persp3.outputs['Value'], combo_persp4.inputs['Y']); links.new(val_lens.outputs['Value'], math_zoom1.inputs[0]); links.new(val_sensor.outputs['Value'], math_zoom1.inputs[1]); links.new(math_zoom1.outputs['Value'], math_zoom2.inputs[0]); links.new(val_shift_x.outputs['Value'], combo_shift1.inputs['X']); links.new(val_shift_y.outputs['Value'], combo_shift1.inputs['Y']); links.new(val_resolution.outputs['Value'], math_aspect_div.inputs[1]); links.new(val_resolution.outputs['Value'], math_aspect_lt.inputs[0]); links.new(val_resolution.outputs['Value'], combo_aspect1.inputs['Y']); links.new(combo_persp4.outputs['Vector'], vec_math_zoom3.inputs[0]); links.new(math_zoom2.outputs['Value'], vec_math_zoom3.inputs[1]); links.new(math_aspect_div.outputs['Value'], combo_aspect2.inputs['X']); links.new(vec_math_zoom3.outputs['Vector'], vec_math_shift2.inputs[0]); links.new(combo_shift1.outputs['Vector'], vec_math_shift2.inputs[1]); links.new(math_aspect_lt.outputs['Value'], mix_aspect_switch.inputs[0]); links.new(combo_aspect1.outputs['Vector'], mix_aspect_switch.inputs[6]); links.new(combo_aspect2.outputs['Vector'], mix_aspect_switch.inputs[7]); links.new(mix_aspect_switch.outputs[2], vec_math_user_transforms.inputs[1]); links.new(vec_math_shift2.outputs['Vector'], vec_math_user_transforms.inputs[0]); links.new(vec_math_user_transforms.outputs['Vector'], vec_math_recenter.inputs[0]); links.new(vec_math_recenter.outputs['Vector'], output_node.inputs['Vector'])
    
    value_nodes_to_drive = {"lens": val_lens, "sensor": val_sensor, "shift_x": val_shift_x, "shift_y": val_shift_y, "resolution": val_resolution}
    setup_drivers_for_group(value_nodes_to_drive, camera_obj)
    
    return group

def setup_drivers_for_group(nodes_to_drive, camera_obj):
    """Sets up drivers for the value nodes within the projection node group. (Original Logic)"""
    def add_driver(node, data_path):
        driver = node.outputs[0].driver_add('default_value').driver
        var = driver.variables.new()
        var.name = "var"
        var.targets[0].id_type = 'CAMERA'
        var.targets[0].id = camera_obj.data
        var.targets[0].data_path = data_path
        driver.expression = "var"
        
    add_driver(nodes_to_drive["lens"], "lens")
    add_driver(nodes_to_drive["sensor"], "sensor_width")
    add_driver(nodes_to_drive["shift_x"], "shift_x")
    add_driver(nodes_to_drive["shift_y"], "shift_y")
    
    res_driver = nodes_to_drive["resolution"].outputs[0].driver_add('default_value').driver
    res_driver.expression = "res_x / res_y if res_y != 0 else 1.0"
    
    var_x = res_driver.variables.new()
    var_x.name = "res_x"
    var_x.targets[0].id_type = 'SCENE'
    var_x.targets[0].id = bpy.context.scene
    var_x.targets[0].data_path = "render.resolution_x"
    
    var_y = res_driver.variables.new()
    var_y.name = "res_y"
    var_y.targets[0].id_type = 'SCENE'
    var_y.targets[0].id = bpy.context.scene
    var_y.targets[0].data_path = "render.resolution_y"


# --- Operator Classes (Formatted with Docstrings) ---

class CLIP_OT_setup_camera_solver(Operator):
    """Adds a Camera Solver constraint to the active camera for the current clip."""
    bl_idname = "clip.setup_camera_solver"
    bl_label = "Setup Camera Solver"
    bl_description = "Adds a Camera Solver constraint to the active camera"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.camera and is_clip_editor_with_active_clip(context)

    def execute(self, context):
        camera = context.scene.camera
        clip = context.space_data.clip
        for c in camera.constraints:
            if c.type == 'CAMERA_SOLVER':
                self.report({'INFO'}, f"Camera Solver constraint already exists on '{camera.name}'.")
                return {'CANCELLED'}
        constraint = camera.constraints.new(type='CAMERA_SOLVER')
        constraint.clip = clip
        constraint.use_active_clip = False
        self.report({'INFO'}, f"Added Camera Solver constraint to '{camera.name}' for clip '{clip.name}'.")
        return {'FINISHED'}


class CLIP_OT_setup_object_solver(Operator):
    """Creates a new Empty with an Object Solver constraint for the active tracking object."""
    bl_idname = "clip.setup_object_solver"
    bl_label = "Setup Object Solver"
    bl_description = "Creates a new Empty with an Object Solver constraint"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not is_clip_editor_with_active_clip(context):
            cls.poll_message_set("Requires an active clip in the editor.")
            return False
        active_track_obj = context.space_data.clip.tracking.objects.active
        if not active_track_obj:
            cls.poll_message_set("No active tracking object in the movie clip.")
            return False
        if active_track_obj.name == "Camera":
            cls.poll_message_set("Cannot setup Object Solver when 'Camera' track is active.")
            return False
        return True

    def execute(self, context):
        clip = context.space_data.clip
        camera = context.scene.camera
        tracking_object = clip.tracking.objects.active
        new_empty = None
        if not camera:
            self.report({'ERROR'}, "No active scene camera found. Operation cancelled.")
            return {'CANCELLED'}
        try:
            new_empty = bpy.data.objects.new("ObjectTrack", None)
            new_empty.empty_display_type = 'PLAIN_AXES'
            context.collection.objects.link(new_empty)
            constraint = new_empty.constraints.new(type='OBJECT_SOLVER')
            constraint.clip = clip
            constraint.use_active_clip = False
            constraint.object = tracking_object.name
            constraint.camera = camera
            for o in context.selected_objects:
                o.select_set(False)
            context.view_layer.objects.active = new_empty
            new_empty.select_set(True)
            self.report({'INFO'}, f"Created 'ObjectTrack' Empty and configured for track '{tracking_object.name}'.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to set up Object Solver: {e}")
            if new_empty:
                bpy.data.objects.remove(new_empty, do_unlink=True)
            return {'CANCELLED'}
        return {'FINISHED'}


class CLIP_OT_3d_markers_to_empty(Operator):
    """Creates an Empty at the 3D position of each selected track with reconstructed 3D data."""
    bl_idname = "clip.3d_markers_to_empty"
    bl_label = "3D Markers to Empty"
    bl_description = "Creates Empties from selected tracks with 3D reconstruction data"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return is_clip_editor_with_active_clip(context)
        
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
    """Sets the clip's start frame from a number in its filename."""
    bl_idname = "clip.set_start_frame_from_filename"
    bl_label = "Set Start Seq No."
    bl_description = "Set sequence start from its source filename, or run Set Scene Frames for movies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_clip_editor_with_active_clip(context)
        
    def execute(self, context):
        clip = context.space_data.clip
        if clip.source == 'MOVIE':
            set_clip_scene_frames()
            self.report({'INFO'}, "Scene frames updated from the movie clip.")
            return {'FINISHED'}
        source_path = clip.filepath or clip.name
        frame_start = get_frame_number_from_path(source_path)
        if frame_start is not None:
            clip.frame_start = frame_start; set_clip_scene_frames()
            self.report({'INFO'}, f"Clip '{clip.name}': start frame set to {frame_start} from '{source_path}'. Scene frames updated.")
        else:
            set_clip_scene_frames()
            self.report({'INFO'}, f"No trailing frame number found in '{source_path}'. Scene frames updated without changing clip start.")
        return {'FINISHED'}

class CLIP_OT_reset_start_frame_and_scene_frames(bpy.types.Operator):
    """Resets the active clip start frame to 1 and updates scene frames."""
    bl_idname = "clip.reset_start_frame_and_scene_frames"
    bl_label = "Reset Start Frame"
    bl_description = "Reset clip start frame to 1 and run Set Scene Frames"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_clip_editor_with_active_clip(context)

    def execute(self, context):
        clip = context.space_data.clip
        clip.frame_start = 1
        set_clip_scene_frames()
        self.report({'INFO'}, f"Clip '{clip.name}': start frame reset to 1. Scene frames updated.")
        return {'FINISHED'}

class CLIP_OT_duplicate_active_movieclip(bpy.types.Operator):
    """Creates a copy of the currently active Movie Clip data-block."""
    bl_idname = "clip.duplicate_active_movieclip"
    bl_label = "Duplicate Active Clip"
    bl_description = "Creates a copy of the currently active Movie Clip data-block"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return is_clip_editor_with_active_clip(context)

    def execute(self, context):
        space_clip = context.space_data; source_clip = space_clip.clip
        if source_clip is None: self.report({'WARNING'}, "No active Movie Clip to duplicate."); return {'CANCELLED'}
        try:
            new_clip = source_clip.copy(); space_clip.clip = new_clip
            self.report({'INFO'}, f"Movie Clip '{source_clip.name}' duplicated as '{new_clip.name}'. New clip is now active.")
        except Exception as e: self.report({'ERROR'}, f"Failed to duplicate Movie Clip: {e}"); return {'CANCELLED'}
        return {'FINISHED'}

class CLIP_OT_delete_active_movieclip(bpy.types.Operator):
    """Deletes the active Movie Clip data-block."""
    bl_idname = "clip.delete_active_movieclip"
    bl_label = "Delete Active Clip"
    bl_description = "Deletes the active Movie Clip. This action can be undone, but the data-block might be lost if not used elsewhere and the file is saved."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_clip_editor_with_active_clip(context)

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
    """Creates a camera-parented plane that matches the camera's view, using the active clip as its texture."""
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
        return has_camera and is_clip_editor_with_active_clip(context)

    def setup_driver_variables(self, driver, imageplane, camera):
        """Sets up the necessary variables for the image plane drivers. (Original Logic)"""
        scene = bpy.context.scene
        needed_vars = {
            'cA': ('CAMERA', "angle", camera.data), 'cT': ('CAMERA', 'type', camera.data),
            'cSx': ('CAMERA', 'shift_x', camera.data), 'cSy': ('CAMERA', 'shift_y', camera.data),
            'r_x': ('SCENE', 'render.resolution_x', scene), 'r_y': ('SCENE', 'render.resolution_y', scene),
            'p_x': ('SCENE', 'render.pixel_aspect_x', scene), 'p_y': ('SCENE', 'render.pixel_aspect_y', scene),
        }
        for name, (id_type, path, target_id) in needed_vars.items():
            if name not in driver.variables:
                var = driver.variables.new(); var.name = name; var.type = 'SINGLE_PROP'
                var.targets[0].id_type = id_type; var.targets[0].id = target_id; var.targets[0].data_path = path
        if 'depth' not in driver.variables:
            var = driver.variables.new(); var.name = 'depth'; var.type = 'TRANSFORMS'
            var.targets[0].id = imageplane; var.targets[0].data_path = 'location'
            var.targets[0].transform_type = 'LOC_Z'; var.targets[0].transform_space = 'LOCAL_SPACE'
        if 'scale_y' not in driver.variables:
            var = driver.variables.new(); var.name = 'scale_y'; var.type = 'SINGLE_PROP'
            var.targets[0].id = imageplane; var.targets[0].data_path = 'scale[1]'

    def setup_drivers_for_image_plane(self, imageplane, camera):
        """Sets up the drivers for the image plane's scale and location. (Original Logic)"""
        base_expr = "abs(depth) * tan(cA/2)"; aspect_expr = "(r_y * p_y) / (r_x * p_x)"
        half_width_expr = f"({base_expr})"; half_height_expr = f"({base_expr}) * {aspect_expr}"
        
        driver_x = imageplane.driver_add('scale', 0).driver; driver_x.type = 'SCRIPTED'
        self.setup_driver_variables(driver_x, imageplane, camera)
        driver_x.expression = f"{half_width_expr} if cT == 0 else 0"
        
        driver_y = imageplane.driver_add('scale', 1).driver; driver_y.type = 'SCRIPTED'
        self.setup_driver_variables(driver_y, imageplane, camera)
        driver_y.expression = f"{half_height_expr} if cT == 0 else 0"
        
        driver_loc_x = imageplane.driver_add('location', 0).driver; driver_loc_x.type = 'SCRIPTED'
        self.setup_driver_variables(driver_loc_x, imageplane, camera)
        driver_loc_x.expression = f"cSx * 2 * {half_width_expr}"
        
        driver_loc_y = imageplane.driver_add('location', 1).driver; driver_loc_y.type = 'SCRIPTED'
        self.setup_driver_variables(driver_loc_y, imageplane, camera)
        driver_loc_y.expression = f"cSy * 2 * scale_y * (r_x / r_y)"

    def create_image_plane(self, context, camera, image):
        """Creates and configures the image plane object and its material."""
        try:
            scene = context.scene; depth = self.depth 
            context.view_layer.objects.active = camera; camera.select_set(True)
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
                material = bpy.data.materials.new(name=material_name); material.use_nodes = True
                material.node_tree.nodes.clear()
                tex_image = material.node_tree.nodes.new('ShaderNodeTexImage')
                emission = material.node_tree.nodes.new('ShaderNodeEmission')
                transparent = material.node_tree.nodes.new('ShaderNodeBsdfTransparent')
                mix_shader = material.node_tree.nodes.new('ShaderNodeMixShader')
                output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
                tex_image.location = (-300, 300); emission.location = (0, 300)
                transparent.location = (0, 0); mix_shader.location = (300, 200)
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
                tex_image_node.image = image; img_user = tex_image_node.image_user
                img_user.use_cyclic = True; img_user.use_auto_refresh = True
                if image.source == 'SEQUENCE':
                    img_user.frame_duration = scene.frame_end - scene.frame_start + 1
                    first_frame = get_frame_number_from_path(image.filepath_raw)
                    if first_frame is not None:
                        img_user.frame_offset = first_frame - 1; img_user.frame_start = scene.frame_start
                    else:
                        img_user.frame_offset = 0; img_user.frame_start = scene.frame_start
                elif image.source == 'MOVIE':
                    img_user.frame_duration = scene.frame_end - scene.frame_start + 1
                    img_user.frame_offset = 0; img_user.frame_start = scene.frame_start
        except Exception as e:
            import traceback; traceback.print_exc()
            self.report({'ERROR'}, f"Failed to create image plane: {e}")
            return {'CANCELLED'}
        context.view_layer.objects.active = imageplane; imageplane.select_set(True)
        return {'FINISHED'}

    def execute(self, context):
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
    """Creates a camera projection material for the selected object."""
    bl_idname = "object.setup_projection_shader"
    bl_label = "Set Cam Projection"
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        active_obj = context.active_object
        if not active_obj: cls.poll_message_set("Please select an object"); return False
        if active_obj.type != 'MESH': cls.poll_message_set("Please select a MESH object"); return False
        if not context.scene.camera: cls.poll_message_set("Please set an active camera in the scene"); return False
        if not is_clip_editor_with_active_clip(context): cls.poll_message_set("Please open a clip in the Movie Clip Editor"); return False
        return True
        
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
            if image.source == 'SEQUENCE':
                first_frame = get_frame_number_from_path(image.filepath_raw)
                img_user.frame_offset = first_frame - 1 if first_frame is not None else 0
            else: img_user.frame_offset = 0
        if selected_obj.data.materials: selected_obj.data.materials[0] = material
        else: selected_obj.data.materials.append(material)
        self.report({'INFO'}, f"Material '{material.name}' has been set up."); return {'FINISHED'}

class CLIP_PG_orientation_plus_settings(bpy.types.PropertyGroup):
    """Settings for Orientation Plus tools."""

    contact_direction: bpy.props.EnumProperty(
        name="Target Surface",
        description="Floor or wall direction used for the contact plane",
        items=(
            ('Z_POS', "+Z Floor", "Use a floor plane with positive Z normal"),
            ('Z_NEG', "-Z Floor", "Use a floor plane with negative Z normal"),
            ('X_POS', "+X Wall", "Use a wall plane with positive X normal"),
            ('X_NEG', "-X Wall", "Use a wall plane with negative X normal"),
            ('Y_POS', "+Y Wall", "Use a wall plane with positive Y normal"),
            ('Y_NEG', "-Y Wall", "Use a wall plane with negative Y normal"),
        ),
        default='Z_POS',
    )

    origin_source: bpy.props.EnumProperty(
        name="Position Mode",
        description="How the target plane position is determined",
        items=(
            ('INPUT', "Move Plane To", "Move the selected track plane center to the chosen coordinate"),
            ('CAMERA_POSITION', "Keep Camera XY", "Keep the camera X/Y position and use only the chosen coordinate Z"),
        ),
        default='CAMERA_POSITION',
    )

    contact_origin: bpy.props.FloatVectorProperty(
        name="Manual Coordinate",
        description="Manual coordinate used as a point on the target plane",
        subtype='XYZ',
        size=3,
        default=(0.0, 0.0, 0.0),
    )

    coordinate_source: bpy.props.EnumProperty(
        name="Coordinate",
        description="Coordinate source used by the position mode",
        items=(
            ('ORIGIN', "None (Origin)", "Use the world origin"),
            ('CURSOR', "3D Cursor", "Use the current scene 3D cursor location directly"),
            ('MANUAL', "Manual", "Use the manual coordinate below"),
        ),
        default='ORIGIN',
    )

    aggregate_method: bpy.props.EnumProperty(
        name="Track Center",
        description="How selected reconstructed points are reduced to one representative point",
        items=(
            ('MEAN', "Average", "Use the average value of the selected points"),
            ('MEDIAN', "Median", "Use the median value of the selected points"),
        ),
        default='MEAN',
    )

class CLIP_OT_orientation_plus_origin_from_cursor(Operator):
    """Copies the 3D cursor location into Orientation Plus contact origin."""
    bl_idname = "clip.orientation_plus_origin_from_cursor"
    bl_label = "Origin From 3D Cursor"
    bl_description = "Copies the scene 3D cursor location to the contact origin"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.clip_tools_orientation_plus
        settings.contact_origin = context.scene.cursor.location
        settings.coordinate_source = 'MANUAL'
        self.report({'INFO'}, "3D cursor location copied to the manual coordinate.")
        return {'FINISHED'}

class CLIP_OT_orientation_plus_set_contact_plane(Operator):
    """Moves solved camera/object positions so selected reconstructed points lie on a target plane."""
    bl_idname = "clip.orientation_plus_set_contact_plane"
    bl_label = "Align Contact Plane"
    bl_description = "Fits selected reconstructed points onto the target floor or wall plane"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not is_clip_editor_with_active_clip(context):
            cls.poll_message_set("Requires an active clip in the Movie Clip Editor.")
            return False
        if not context.scene.camera:
            cls.poll_message_set("Requires an active scene camera.")
            return False
        return True

    def execute(self, context):
        clip = context.space_data.clip
        tracking_object = clip.tracking.objects.active
        if not tracking_object:
            self.report({'ERROR'}, "No active tracking object found.")
            return {'CANCELLED'}

        camera = get_camera_with_movieclip(context, clip)
        if not camera:
            self.report({'ERROR'}, "No camera using the active movie clip was found.")
            return {'CANCELLED'}

        orientation_object = get_orientation_plus_object(context, clip, tracking_object)
        if not orientation_object:
            self.report({'ERROR'}, "No object to apply orientation on.")
            return {'CANCELLED'}

        current_points, current_camera_matrix, current_orientation_matrix = get_evaluated_reconstructed_points(
            context, clip, tracking_object, camera, orientation_object
        )
        if current_points is None:
            self.report({'ERROR'}, "No solved camera reconstruction was found for the current frame.")
            return {'CANCELLED'}
        if len(current_points) < 1:
            self.report({'ERROR'}, "Select at least 1 reconstructed track with 3D bundle data.")
            return {'CANCELLED'}

        settings = context.scene.clip_tools_orientation_plus
        target_normal = get_orientation_plus_axis(settings, camera)
        target_point = get_orientation_plus_target_point(settings, context.scene, current_camera_matrix)
        current_source_point = reduce_points(current_points, settings.aggregate_method)

        if len(current_points) == 1:
            if settings.contact_direction.startswith('Z'):
                rotation = get_one_point_floor_rotation(target_normal, current_camera_matrix)
            else:
                rotation = get_one_point_wall_rotation(target_normal, current_camera_matrix)
        elif len(current_points) == 2:
            angle, axis, used_depth_fallback = solve_two_point_plane_angle(
                current_points,
                target_normal,
                current_camera_matrix,
                prefer_camera_view=not settings.contact_direction.startswith('Z'),
            )
            if axis.length <= 1.0e-8:
                self.report({'ERROR'}, "The selected 2 tracks cannot define a stable constrained rotation.")
                return {'CANCELLED'}
            rotation = Matrix.Rotation(angle, 4, axis.normalized()).to_quaternion()
            if used_depth_fallback:
                self.report({'WARNING'}, "2 selected tracks have too little depth; rotation correction was limited.")
        else:
            source_normal = fit_plane_normal(current_points, current_source_point)
            if not source_normal:
                self.report({'ERROR'}, "Selected reconstructed tracks are collinear; a plane cannot be fitted.")
                return {'CANCELLED'}
            source_normal = orient_normal_toward_camera(source_normal, current_source_point, current_camera_matrix)
            rotation = get_orientation_plus_rotation(source_normal, target_normal, current_camera_matrix)

        pivot = current_camera_matrix.translation.copy()
        rotation_transform = (
            Matrix.Translation(pivot) @
            rotation.to_matrix().to_4x4() @
            Matrix.Translation(-pivot)
        )
        rotated_source_point = rotation_transform @ current_source_point

        if settings.origin_source == 'INPUT':
            delta = target_point - rotated_source_point
        else:
            delta = Vector((0.0, 0.0, target_point.z - rotated_source_point.z))

        transform = Matrix.Translation(delta) @ rotation_transform
        rotation_angle = math.degrees(rotation.angle)

        if delta.length < 1.0e-8 and rotation.angle < 1.0e-8:
            self.report({'INFO'}, "Selected tracker plane is already aligned to the target plane.")
            return {'FINISHED'}

        transform_orientation_object(orientation_object, transform, current_orientation_matrix)
        context.view_layer.update()

        final_points, final_camera_matrix, _final_orientation_matrix = get_evaluated_reconstructed_points(
            context, clip, tracking_object, camera, orientation_object
        )
        if final_points is None:
            self.report({'ERROR'}, "No solved camera reconstruction was found after applying the transform.")
            return {'CANCELLED'}
        if settings.origin_source == 'INPUT':
            final_point = reduce_points(final_points, settings.aggregate_method)
            correction_delta = target_point - final_point
        else:
            final_track_point = reduce_points(final_points, settings.aggregate_method)
            correction_delta = Vector((0.0, 0.0, target_point.z - final_track_point.z))

        if correction_delta.length > 1.0e-8:
            translate_orientation_object_world(orientation_object, correction_delta)

        clip.update_tag()
        orientation_object.update_tag(refresh={'OBJECT'})
        context.view_layer.update()
        self.report({'INFO'}, f"Set tracker plane on '{orientation_object.name}'. Move {tuple(round(v, 4) for v in delta)}, rotation {rotation_angle:.3f} deg.")
        return {'FINISHED'}

# --- UI Panels ---
class CLIP_PT_tools_scenesetup(Panel):
    """UI Panel for general scene setup tools related to tracking."""
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

class CLIP_PT_tools_orientation_plus(Panel):
    """UI Panel for contact-only orientation helpers."""
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'TOOLS'
    bl_label = "Orientation Plus"
    bl_category = "Solve"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        sc = context.space_data
        return sc and sc.clip and sc.view == 'CLIP' and sc.mode == 'TRACKING'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.clip_tools_orientation_plus

        col = layout.column()
        col.prop(settings, "contact_direction")
        col.prop(settings, "origin_source")
        col.prop(settings, "coordinate_source")
        col.prop(settings, "aggregate_method")

        if settings.coordinate_source == 'MANUAL':
            col.separator()
            coord_col = col.column(align=True)
            coord_col.prop(settings, "contact_origin")
            col.operator(CLIP_OT_orientation_plus_origin_from_cursor.bl_idname, icon='PIVOT_CURSOR')

        col.separator()
        col.operator(CLIP_OT_orientation_plus_set_contact_plane.bl_idname, text="Align Contact Plane", icon='SNAP_FACE')

# --- UI and Registration ---
def draw_button_for_3d_markers_to_empty_panel(self, context): self.layout.operator(CLIP_OT_3d_markers_to_empty.bl_idname, icon='EMPTY_AXIS')
def draw_menu_item_for_3d_markers_to_empty(self, context): self.layout.separator(); self.layout.operator(CLIP_OT_3d_markers_to_empty.bl_idname, icon='EMPTY_AXIS')
def draw_button_for_set_start_frame_panel(self, context):
    row = self.layout.row(align=True)
    row.operator(CLIP_OT_reset_start_frame_and_scene_frames.bl_idname, text="", icon='LOOP_BACK')
    row.operator(CLIP_OT_set_start_frame_from_filename.bl_idname)
def draw_menu_item_for_setup_solvers(self, context): self.layout.operator(CLIP_OT_setup_camera_solver.bl_idname, icon='CON_CAMERASOLVER'); self.layout.operator(CLIP_OT_setup_object_solver.bl_idname, icon='CON_OBJECTSOLVER'); self.layout.separator()
def draw_menu_item_for_duplicate_clip(self, context): self.layout.operator(CLIP_OT_duplicate_active_movieclip.bl_idname, icon='DUPLICATE')
def draw_menu_item_for_delete_clip(self, context): self.layout.operator(CLIP_OT_delete_active_movieclip.bl_idname, icon='TRASH')
def draw_button_for_create_image_plane(self, context): self.layout.operator(CLIP_OT_create_image_plane_from_clip.bl_idname, text="Create Image Plane", icon='FILE_IMAGE')
def draw_menu_item_for_create_image_plane(self, context): self.layout.operator(CLIP_OT_create_image_plane_from_clip.bl_idname, icon='FILE_IMAGE')
def draw_button_for_set_cam_projection_panel(self, context): self.layout.operator(PROJECTION_OT_setup_shader.bl_idname, text="Set Cam Projection", icon='MATERIAL')
def draw_menu_item_for_set_cam_projection(self, context): self.layout.separator(); self.layout.operator(PROJECTION_OT_setup_shader.bl_idname, icon='MATERIAL')

classes_to_register = (
    CLIP_PG_orientation_plus_settings,
    CLIP_OT_setup_camera_solver,
    CLIP_OT_setup_object_solver,
    CLIP_OT_3d_markers_to_empty, 
    CLIP_OT_set_start_frame_from_filename, 
    CLIP_OT_reset_start_frame_and_scene_frames,
    CLIP_OT_duplicate_active_movieclip,
    CLIP_OT_delete_active_movieclip, 
    CLIP_OT_create_image_plane_from_clip, 
    CLIP_OT_orientation_plus_origin_from_cursor,
    CLIP_OT_orientation_plus_set_contact_plane,
    PROJECTION_OT_setup_shader,
    CLIP_PT_tools_scenesetup,
    CLIP_PT_tools_orientation_plus,
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
    """Registers all addon classes and appends UI elements."""
    track_tools.register()
    plane_track_tools.register()
    mask_tools.register()
    for cls in classes_to_register: bpy.utils.register_class(cls)
    bpy.types.Scene.clip_tools_orientation_plus = bpy.props.PointerProperty(type=CLIP_PG_orientation_plus_settings)
    for target_classname, draw_func in ui_additions:
        try:
            target_class = getattr(bpy.types, target_classname, None)
            if target_class: target_class.append(draw_func)
        except Exception as e: print(f"ERROR appending {draw_func.__name__} to {target_classname}: {e}")

def unregister():
    """Unregisters all addon classes and removes UI elements."""
    if hasattr(bpy.types.Scene, "clip_tools_orientation_plus"):
        del bpy.types.Scene.clip_tools_orientation_plus
    for target_classname, draw_func in ui_additions:
        try:
            target_class = getattr(bpy.types, target_classname, None)
            if target_class and hasattr(target_class, "remove"): target_class.remove(draw_func)
        except (AttributeError, RuntimeError): pass
    for cls in reversed(classes_to_register): bpy.utils.unregister_class(cls)
    track_tools.unregister()
    plane_track_tools.unregister()
    mask_tools.unregister()
