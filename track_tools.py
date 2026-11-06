from bisect import bisect_left, insort
from math import isfinite

import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty


MARKER_OFFSET_CACHE = None
SUPPRESS_MARKER_OFFSET_UPDATE = False


def get_clip(context):
    if not context:
        return None

    space = context.space_data
    if space and space.type == 'CLIP_EDITOR' and space.clip:
        return space.clip

    return getattr(context, "edit_movieclip", None)


def get_active_tracking_object(context):
    clip = get_clip(context)
    if not clip:
        return None

    tracking = clip.tracking
    active_object = getattr(tracking.objects, "active", None)
    if active_object:
        return active_object

    index = tracking.active_object_index
    if 0 <= index < len(tracking.objects):
        return tracking.objects[index]

    return None


def get_active_tracks(context):
    tracking_object = get_active_tracking_object(context)
    if tracking_object:
        return tracking_object.tracks

    return []


def get_selected_navigation_tracks(context):
    tracks = get_active_tracks(context)
    if not tracks:
        return []

    selected_tracks = [track for track in tracks if is_track_selected(track)]
    active_track = getattr(tracks, "active", None)
    if active_track and active_track in selected_tracks:
        return [active_track]
    if active_track and not selected_tracks:
        return [active_track]

    return selected_tracks


def scene_to_marker_frame(clip, scene_frame):
    return int(round(scene_frame - clip.frame_start + 1 + clip.frame_offset))


def marker_to_scene_frame(clip, marker_frame):
    return int(round(marker_frame + clip.frame_start - 1 - clip.frame_offset))


def redraw_clip_editors(context):
    if not context:
        return

    context.view_layer.update()
    screen = getattr(context, "screen", None)
    if not screen:
        return

    for area in screen.areas:
        if area.type == 'CLIP_EDITOR':
            area.tag_redraw()


def change_clip_editor_frame(context, clip, scene_frame):
    screen = getattr(context, "screen", None)
    if not screen:
        return False

    changed = False
    for area in screen.areas:
        if area.type != 'CLIP_EDITOR':
            continue

        for space in area.spaces:
            if space.type != 'CLIP_EDITOR' or space.clip != clip:
                continue

            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            override = {"area": area, "space_data": space}
            if region:
                override["region"] = region

            try:
                with context.temp_override(**override):
                    bpy.ops.clip.change_frame(frame=scene_frame)
                changed = True
            except RuntimeError:
                pass

    return changed


def set_current_marker_frame(context, marker_frame):
    clip = get_clip(context)
    scene_frame = marker_to_scene_frame(clip, marker_frame) if clip else marker_frame
    context.scene.frame_set(scene_frame)
    if clip:
        clip.update_tag()
        change_clip_editor_frame(context, clip, scene_frame)
    redraw_clip_editors(context)


def clear_clip_solution(context):
    if not get_clip(context):
        return False

    try:
        bpy.ops.clip.clear_solution()
    except RuntimeError:
        return False

    return True


def marker_offset_vec2(v):
    return (v[0], v[1])


def collect_marker_offset_marker_data(track):
    return [
        {
            "frame": marker.frame,
            "co": marker_offset_vec2(marker.co),
            "pattern_corners": [marker_offset_vec2(corner) for corner in marker.pattern_corners],
            "search_min": marker_offset_vec2(marker.search_min),
            "search_max": marker_offset_vec2(marker.search_max),
            "mute": getattr(marker, "mute", False),
        }
        for marker in track.markers
    ]


def collect_marker_offset_track_data(tracking_object, selected_only):
    tracks = []
    for track in tracking_object.tracks:
        if selected_only and not track.select:
            continue

        markers = collect_marker_offset_marker_data(track)
        if markers:
            tracks.append({
                "name": track.name,
                "pointer": track.as_pointer(),
                "markers": markers,
            })

    return tracks


def collect_marker_offset_object_data(clip, selected_only, active_object):
    source_objects = [active_object] if selected_only else list(clip.tracking.objects)
    objects = []
    for tracking_object in source_objects:
        if not tracking_object:
            continue

        tracks = collect_marker_offset_track_data(tracking_object, selected_only)
        if tracks:
            objects.append({
                "name": tracking_object.name,
                "pointer": tracking_object.as_pointer(),
                "tracks": tracks,
            })

    return objects


def clear_track_markers(track):
    for frame in [marker.frame for marker in track.markers]:
        track.markers.delete_frame(frame)


def insert_marker_offset_marker(track, data, frame):
    marker = track.markers.insert_frame(frame=frame, co=data["co"])
    for i in range(4):
        marker.pattern_corners[i] = data["pattern_corners"][i]

    marker.search_min = data["search_min"]
    marker.search_max = data["search_max"]
    if hasattr(marker, "mute"):
        marker.mute = data["mute"]


def restore_track_markers(track, marker_data):
    clear_track_markers(track)
    for data in marker_data:
        insert_marker_offset_marker(track, data, data["frame"])


def find_by_pointer(collection, pointer):
    for item in collection:
        if item.as_pointer() == pointer:
            return item

    return None


def find_marker_offset_tracking_object(clip, cached_object):
    return (
        find_by_pointer(clip.tracking.objects, cached_object["pointer"])
        or clip.tracking.objects.get(cached_object["name"])
    )


def find_marker_offset_track(tracking_object, cached_track):
    return (
        find_by_pointer(tracking_object.tracks, cached_track["pointer"])
        or tracking_object.tracks.get(cached_track["name"])
    )


def set_marker_offset_status(context, message):
    scene = context.scene if context else None
    if scene and hasattr(scene, "clip_tools_marker_offset_status"):
        scene.clip_tools_marker_offset_status = message


def make_marker_offset_cache(context, selected_only):
    clip = get_clip(context)
    if not clip:
        return None, "Open a clip in the Movie Clip Editor"

    active_object = get_active_tracking_object(context)
    if selected_only and not active_object:
        return None, "No active tracking object"

    objects = collect_marker_offset_object_data(clip, selected_only, active_object)
    if not objects:
        return None, "No selected tracks with markers" if selected_only else "No tracks with markers"

    cache = {
        "clip_pointer": clip.as_pointer(),
        "clip_name": clip.name,
        "selected_only": selected_only,
        "objects": objects,
    }

    object_count = len(objects)
    track_count = sum(len(obj["tracks"]) for obj in objects)
    marker_count = sum(
        len(track["markers"])
        for obj in objects
        for track in obj["tracks"]
    )
    scope = "active object selection" if selected_only else "all tracking objects"
    message = f"Captured {marker_count} marker(s), {track_count} track(s), {object_count} object(s) from {scope}"

    return cache, message


def validate_marker_offset_cache(context):
    if not MARKER_OFFSET_CACHE:
        return None, "Click Get Trackers first"

    clip = get_clip(context)
    if not clip:
        return None, "Open a clip in the Movie Clip Editor"

    if clip.as_pointer() != MARKER_OFFSET_CACHE["clip_pointer"]:
        return None, "The cached clip is no longer active"

    return clip, None


def apply_cached_marker_offset(context, offset):
    clip, error = validate_marker_offset_cache(context)
    if error:
        return False, error, False

    resolved_tracks = []
    restore_data = []
    moved_count = 0
    skipped_count = 0

    for cached_object in MARKER_OFFSET_CACHE["objects"]:
        tracking_object = find_marker_offset_tracking_object(clip, cached_object)
        if not tracking_object:
            return False, f"Missing tracking object: {cached_object['name']}", False

        for cached_track in cached_object["tracks"]:
            track = find_marker_offset_track(tracking_object, cached_track)
            if not track:
                return False, f"Missing track: {cached_object['name']} / {cached_track['name']}", False

            resolved_tracks.append((track, cached_track["markers"]))

    try:
        for track, cached_markers in resolved_tracks:
            restore_data.append((track, collect_marker_offset_marker_data(track)))
            clear_track_markers(track)

            for marker_data in cached_markers:
                new_frame = marker_data["frame"] + offset
                if new_frame < 1:
                    skipped_count += 1
                    continue

                insert_marker_offset_marker(track, marker_data, new_frame)
                moved_count += 1
    except Exception as exc:
        for track, marker_data in restore_data:
            restore_track_markers(track, marker_data)
        return False, f"Offset failed; current markers were restored: {exc}", False

    message = f"Applied offset {offset}: {moved_count} marker(s)"
    if skipped_count:
        message += f", {skipped_count} skipped before frame 1"

    changed_solution_input = offset != 0 and (moved_count > 0 or skipped_count > 0)
    return True, message, changed_solution_input


def count_marker_offset_before_frame_one(offset):
    if not MARKER_OFFSET_CACHE or offset >= 0:
        return 0

    return sum(
        1
        for cached_object in MARKER_OFFSET_CACHE["objects"]
        for cached_track in cached_object["tracks"]
        for marker_data in cached_track["markers"]
        if marker_data["frame"] + offset < 1
    )


def on_marker_offset_changed(scene, context):
    if SUPPRESS_MARKER_OFFSET_UPDATE:
        return

    ok, message, changed_solution_input = apply_cached_marker_offset(context, scene.clip_tools_marker_offset)
    if ok and changed_solution_input:
        if clear_clip_solution(context):
            message += "; solution cleared"
        else:
            message += "; solution clear failed"
    set_marker_offset_status(context, message)


def on_bridge_preview_changed(settings, context):
    from . import track_bridge_preview
    track_bridge_preview.set_enabled(context, settings.preview_enabled)


class TrackGapInterpSettings(PropertyGroup):
    preview_enabled: BoolProperty(
        name="Preview", default=False, options={'SKIP_SAVE'},
        description="Overlay the interpolated path without changing any markers",
        update=on_bridge_preview_changed,
    )
    interpolation_method: EnumProperty(
        name="Method",
        items=[
            ('LINEAR', "Linear", "Straight linear interpolation between the surrounding enabled keys"),
            ('SMOOTHSTEP', "Ease Linear", "Straight interpolation with eased timing near the surrounding keys"),
            ('CATMULL_ROM', "Trend Hermite", "Curved interpolation that follows motion trend from reference keys"),
            ('NATURAL_CUBIC', "Natural Cubic", "Smooth spline interpolation through the reference keys"),
            ('AKIMA', "Akima", "Smooth curved interpolation with reduced overshoot on uneven marker motion"),
        ],
        default='CATMULL_ROM',
    )

    join_short_islands: BoolProperty(name="Join Islands", default=True)
    max_island_length: IntProperty(name="Max", default=1, min=1, max=100)
    outer_reference_keys: IntProperty(
        name="Refs",
        default=4,
        min=0,
        max=10,
        description="Enabled keys before/after the baked range used to preserve tangent direction",
    )
    tangent_strength: FloatProperty(
        name="Tangent",
        default=1.0,
        min=0.0,
        max=3.0,
        description="How strongly the estimated in/out motion bends the curve",
    )
    disable_range_start: IntProperty(name="Start", default=1, min=0, description="First frame to clear")
    disable_range_end: IntProperty(name="End", default=250, min=0, description="Last frame to clear")


def smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def vector_length(value):
    if hasattr(value, "length"):
        return value.length

    return sum(component * component for component in value) ** 0.5


def hermite(p1, p2, m1, m2, t):
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    return h00 * p1 + h10 * m1 + h01 * p2 + h11 * m2


def estimate_tangent(points, index):
    point = points[index]
    frame = point["frame"]
    co = point["co"]
    tangent = co * 0.0
    weight_sum = 0.0

    for other in points:
        delta_frame = other["frame"] - frame
        if delta_frame == 0:
            continue

        tangent += (other["co"] - co) * delta_frame
        weight_sum += delta_frame * delta_frame

    if weight_sum == 0.0:
        return tangent

    return tangent * (1.0 / weight_sum)


def trend_hermite(points, seg_index, frame, tangent_strength):
    p1 = points[seg_index]
    p2 = points[seg_index + 1]
    f1 = p1["frame"]
    f2 = p2["frame"]
    if f1 == f2:
        return p1["co"].copy()

    segment_length = f2 - f1
    t = (frame - f1) / segment_length
    m1 = estimate_tangent(points, seg_index) * segment_length * tangent_strength
    m2 = estimate_tangent(points, seg_index + 1) * segment_length * tangent_strength
    return hermite(p1["co"], p2["co"], m1, m2, t)


def solve_natural_cubic_second_derivatives(points):
    count = len(points)
    zero = points[0]["co"] * 0.0
    if count <= 2:
        return [zero.copy() for _ in points]

    lower = [0.0] * count
    diagonal = [1.0] * count
    upper = [0.0] * count
    rhs = [zero.copy() for _ in points]

    for i in range(1, count - 1):
        h0 = points[i]["frame"] - points[i - 1]["frame"]
        h1 = points[i + 1]["frame"] - points[i]["frame"]
        if h0 == 0 or h1 == 0:
            continue

        slope0 = (points[i]["co"] - points[i - 1]["co"]) * (1.0 / h0)
        slope1 = (points[i + 1]["co"] - points[i]["co"]) * (1.0 / h1)
        lower[i] = h0
        diagonal[i] = 2.0 * (h0 + h1)
        upper[i] = h1
        rhs[i] = (slope1 - slope0) * 6.0

    for i in range(1, count):
        if diagonal[i - 1] == 0.0:
            continue

        factor = lower[i] / diagonal[i - 1]
        diagonal[i] -= factor * upper[i - 1]
        rhs[i] -= rhs[i - 1] * factor

    result = [zero.copy() for _ in points]
    if diagonal[-1] != 0.0:
        result[-1] = rhs[-1] * (1.0 / diagonal[-1])

    for i in range(count - 2, -1, -1):
        if diagonal[i] == 0.0:
            result[i] = zero.copy()
        else:
            result[i] = (rhs[i] - result[i + 1] * upper[i]) * (1.0 / diagonal[i])

    return result


def natural_cubic(points, seg_index, frame):
    p1 = points[seg_index]
    p2 = points[seg_index + 1]
    f1 = p1["frame"]
    f2 = p2["frame"]
    if f1 == f2:
        return p1["co"].copy()

    second = solve_natural_cubic_second_derivatives(points)
    h = f2 - f1
    a = (f2 - frame) / h
    b = (frame - f1) / h
    curve = p1["co"] * a + p2["co"] * b
    bend = (
        second[seg_index] * (a * a * a - a) +
        second[seg_index + 1] * (b * b * b - b)
    ) * ((h * h) / 6.0)
    return curve + bend


def akima_slope(slopes, index):
    last = len(slopes) - 1
    if index < 0:
        if len(slopes) == 1:
            return slopes[0]

        return slopes[0] * 2.0 - slopes[min(1, last)]

    if index > last:
        if len(slopes) == 1:
            return slopes[0]

        return slopes[last] * 2.0 - slopes[max(last - 1, 0)]

    return slopes[index]


def akima_tangent(points, index):
    slopes = []
    for i in range(len(points) - 1):
        frame_delta = points[i + 1]["frame"] - points[i]["frame"]
        if frame_delta == 0:
            slopes.append(points[i]["co"] * 0.0)
        else:
            slopes.append((points[i + 1]["co"] - points[i]["co"]) * (1.0 / frame_delta))

    if not slopes:
        return points[index]["co"] * 0.0

    if len(slopes) == 1:
        return slopes[0]

    s0 = akima_slope(slopes, index - 2)
    s1 = akima_slope(slopes, index - 1)
    s2 = akima_slope(slopes, index)
    s3 = akima_slope(slopes, index + 1)
    w1 = vector_length(s3 - s2)
    w2 = vector_length(s1 - s0)
    if w1 + w2 == 0.0:
        return (s1 + s2) * 0.5

    return (s1 * w1 + s2 * w2) * (1.0 / (w1 + w2))


def akima(points, seg_index, frame, tangent_strength):
    p1 = points[seg_index]
    p2 = points[seg_index + 1]
    f1 = p1["frame"]
    f2 = p2["frame"]
    if f1 == f2:
        return p1["co"].copy()

    segment_length = f2 - f1
    t = (frame - f1) / segment_length
    m1 = akima_tangent(points, seg_index) * segment_length * tangent_strength
    m2 = akima_tangent(points, seg_index + 1) * segment_length * tangent_strength
    return hermite(p1["co"], p2["co"], m1, m2, t)


def get_enabled_islands(markers):
    islands = []
    current = []
    for marker in markers:
        if marker.mute:
            if current:
                islands.append(current)
                current = []
            continue

        if not current:
            current = [marker]
        elif marker.frame == current[-1].frame + 1:
            current.append(marker)
        else:
            islands.append(current)
            current = [marker]

    if current:
        islands.append(current)

    return islands


def island_length(island):
    return island[-1].frame - island[0].frame + 1


def marker_point(marker):
    return {"frame": marker.frame, "co": marker.co.copy()}


def marker_parameter_data(marker):
    return {
        "pattern_corners": [tuple(corner) for corner in marker.pattern_corners],
        "search_min": tuple(marker.search_min),
        "search_max": tuple(marker.search_max),
        "mute": getattr(marker, "mute", False),
        "is_keyed": getattr(marker, "is_keyed", True),
    }


def apply_marker_parameters(marker, data):
    for i in range(4):
        marker.pattern_corners[i] = data["pattern_corners"][i]

    marker.search_min = data["search_min"]
    marker.search_max = data["search_max"]
    if hasattr(marker, "is_keyed"):
        marker.is_keyed = data["is_keyed"]
    if hasattr(marker, "mute"):
        marker.mute = data["mute"]


def previous_marker_parameters(markers, frame):
    previous_marker = None
    for marker in markers:
        if marker.frame >= frame:
            break
        previous_marker = marker

    if previous_marker:
        return marker_parameter_data(previous_marker)

    if markers:
        return marker_parameter_data(markers[0])

    return None


def unique_markers_by_frame(markers):
    unique = {}
    for marker in markers:
        unique[marker.frame] = marker

    return sorted(unique.values(), key=lambda m: m.frame)


def interpolate_between_points(points, frame, method, tangent_strength=1.0):
    points = sorted(points, key=lambda p: p["frame"])
    if frame <= points[0]["frame"]:
        return points[0]["co"].copy()

    if frame >= points[-1]["frame"]:
        return points[-1]["co"].copy()

    seg_index = None
    for i in range(len(points) - 1):
        if points[i]["frame"] <= frame <= points[i + 1]["frame"]:
            seg_index = i
            break

    if seg_index is None:
        return points[0]["co"].copy()

    p1 = points[seg_index]
    p2 = points[seg_index + 1]
    f1 = p1["frame"]
    f2 = p2["frame"]
    if f1 == f2:
        return p1["co"].copy()

    t = (frame - f1) / (f2 - f1)
    co1 = p1["co"]
    co2 = p2["co"]
    if method == 'LINEAR':
        return co1 + (co2 - co1) * t

    if method == 'SMOOTHSTEP':
        return co1 + (co2 - co1) * smoothstep(t)

    if method == 'CATMULL_ROM':
        return trend_hermite(points, seg_index, frame, tangent_strength)

    if method == 'NATURAL_CUBIC':
        return natural_cubic(points, seg_index, frame)

    if method == 'AKIMA':
        return akima(points, seg_index, frame, tangent_strength)

    return co1 + (co2 - co1) * t


def is_track_selected(track):
    return any(
        bool(getattr(track, attr, False))
        for attr in ("select", "select_anchor", "select_pattern", "select_search")
    )


def find_neighbor_frame(frames, current_frame, direction):
    frames = sorted(set(int(frame) for frame in frames))
    if direction == 'PREVIOUS':
        previous_frames = [frame for frame in frames if frame < current_frame]
        return previous_frames[-1] if previous_frames else None

    next_frames = [frame for frame in frames if frame > current_frame]
    return next_frames[0] if next_frames else None


def get_track_key_frames(track):
    markers = sorted(track.markers, key=lambda marker: marker.frame)
    keyed_frames = [
        marker.frame
        for marker in markers
        if bool(getattr(marker, "is_keyed", False))
    ]
    if keyed_frames:
        return keyed_frames

    return [marker.frame for marker in markers]


def get_selected_key_frames(context):
    frames = []
    for track in get_selected_navigation_tracks(context):
        frames.extend(get_track_key_frames(track))

    return frames


def get_selected_enabled_range_frames(context):
    frames = []
    for track in get_selected_navigation_tracks(context):
        markers = sorted(track.markers, key=lambda marker: marker.frame)
        for island in get_enabled_islands(markers):
            frames.append(island[0].frame)
            frames.append(island[-1].frame)

    return frames


def track_label(track):
    return getattr(track, "name", "Track")


def find_nearest_gap_index(islands, current_frame):
    best_index = None
    best_distance = None
    for i in range(len(islands) - 1):
        left = islands[i]
        right = islands[i + 1]
        gap_start = left[-1].frame + 1
        gap_end = right[0].frame - 1
        if gap_start > gap_end:
            continue

        if gap_start <= current_frame <= gap_end:
            distance = 0
        elif current_frame < gap_start:
            distance = gap_start - current_frame
        else:
            distance = current_frame - gap_end

        if best_distance is None or distance < best_distance:
            best_index = i
            best_distance = distance

    return best_index


def expand_gap_with_short_islands(islands, gap_index, settings):
    start_island_index = gap_index
    end_island_index = gap_index + 1
    if settings.join_short_islands:
        while start_island_index - 1 >= 0:
            island_to_check = islands[start_island_index]
            if island_length(island_to_check) <= settings.max_island_length:
                start_island_index -= 1
            else:
                break

        while end_island_index + 1 < len(islands):
            island_to_check = islands[end_island_index]
            if island_length(island_to_check) <= settings.max_island_length:
                end_island_index += 1
            else:
                break

    return islands[start_island_index:end_island_index + 1]


def get_bridge_markers(selected_islands):
    bridge_markers = []
    if len(selected_islands) == 1:
        bridge_markers.extend(marker for marker in selected_islands[0] if not marker.mute)
    else:
        bridge_markers.append(selected_islands[0][-1])
        for island in selected_islands[1:-1]:
            bridge_markers.extend(marker for marker in island if not marker.mute)
        bridge_markers.append(selected_islands[-1][0])

    return unique_markers_by_frame(bridge_markers)


def get_bridge_bake_frames(track, selected_islands):
    frames = []
    for left_island, right_island in zip(selected_islands, selected_islands[1:]):
        start = left_island[-1].frame + 1
        end = right_island[0].frame - 1
        for frame in range(start, end + 1):
            marker = track.markers.find_frame(frame, exact=True)
            if marker is None or marker.mute:
                frames.append(frame)

    return frames


def plan_track_gap(track, current_frame, settings):
    markers = sorted(track.markers, key=lambda m: m.frame)
    if len(markers) < 2:
        return None, "Not enough markers."

    enabled_markers = sorted([m for m in markers if not m.mute], key=lambda m: m.frame)
    if len(enabled_markers) < 2:
        return None, "At least two enabled markers are required."

    islands = get_enabled_islands(markers)
    target_gap_index = find_nearest_gap_index(islands, current_frame)
    if target_gap_index is None:
        return None, "No interpolatable OFF range between enabled islands."

    selected_islands = expand_gap_with_short_islands(islands, target_gap_index, settings)
    bridge_markers = get_bridge_markers(selected_islands)
    if len(bridge_markers) < 2:
        return None, "Not enough bridge control points."

    bake_frames = get_bridge_bake_frames(track, selected_islands)
    if not bake_frames:
        return None, "No OFF frames to bridge."

    bake_start = min(bake_frames)
    bake_end = max(bake_frames)
    outer_count = settings.outer_reference_keys
    before = [marker for marker in enabled_markers if marker.frame < bake_start]
    after = [marker for marker in enabled_markers if marker.frame > bake_end]

    reference_markers = []
    reference_markers.extend(before[-outer_count:] if outer_count > 0 else [])
    reference_markers.extend(bridge_markers)
    reference_markers.extend(after[:outer_count] if outer_count > 0 else [])
    reference_markers = unique_markers_by_frame(reference_markers)
    control_points = [marker_point(marker) for marker in reference_markers]
    if len(control_points) < 2:
        return None, "Not enough reference control points."

    positions = []
    for frame in bake_frames:
        co = interpolate_between_points(control_points, frame, settings.interpolation_method, settings.tangent_strength)
        if not all(isfinite(value) for value in co):
            return None, "Interpolation produced an invalid position."
        positions.append((frame, tuple(co)))
    positions_by_frame = dict(positions)
    paths = []
    for left, right in zip(selected_islands, selected_islands[1:]):
        path = [(left[-1].frame, tuple(left[-1].co))]
        path.extend((frame, positions_by_frame[frame])
                    for frame in range(left[-1].frame + 1, right[0].frame)
                    if frame in positions_by_frame)
        path.append((right[0].frame, tuple(right[0].co)))
        paths.append(tuple(path))
    existing_paths = []
    context_count = max(2, outer_count)
    for index, island in enumerate(selected_islands):
        visible = island[-context_count:] if index == 0 else island
        if index == len(selected_islands) - 1:
            visible = visible[:context_count]
        existing_paths.append(tuple((marker.frame, tuple(marker.co)) for marker in visible))
    return {"count": len(positions), "bake_start": bake_start, "bake_end": bake_end,
            "method": settings.interpolation_method, "positions": tuple(positions),
            "paths": tuple(paths), "existing_paths": tuple(existing_paths)}, None


def interpolate_track_gap(track, current_frame, settings):
    plan, error = plan_track_gap(track, current_frame, settings)
    if plan is None:
        return None, error
    # Detach marker parameters before insert/delete can invalidate RNA pointers.
    parameters = [(marker.frame, marker_parameter_data(marker)) for marker in track.markers]
    parameters.sort(key=lambda item: item[0])
    parameter_frames = [frame for frame, _data in parameters]
    parameters_by_frame = dict(parameters)
    for frame, co in plan["positions"]:
        index = max(0, bisect_left(parameter_frames, frame) - 1)
        parameter_data = parameters_by_frame[parameter_frames[index]]
        existing = track.markers.find_frame(frame, exact=True)
        if existing is not None:
            track.markers.delete_frame(frame)

        marker = track.markers.insert_frame(frame, co=co)
        if parameter_data:
            apply_marker_parameters(marker, parameter_data)
        marker.mute = False
        if frame not in parameters_by_frame:
            insort(parameter_frames, frame)
        parameters_by_frame[frame] = marker_parameter_data(marker)
    return {key: plan[key] for key in ("count", "bake_start", "bake_end", "method")}, None


def disable_track_markers_in_range(track, frame_start, frame_end):
    start = min(frame_start, frame_end)
    end = max(frame_start, frame_end)
    count = 0
    for marker in track.markers:
        if start <= marker.frame <= end and not marker.mute:
            marker.mute = True
            count += 1

    if count == 0:
        return None, "No enabled markers in range."

    return {"count": count, "frame_start": start, "frame_end": end}, None


class CLIP_OT_marker_offset_get_source(Operator):
    """Captures marker positions as the offset source."""
    bl_idname = "clip.marker_offset_get_source"
    bl_label = "Get Trackers"
    bl_description = "Capture marker positions as the offset source"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_clip(context) is not None

    def execute(self, context):
        global MARKER_OFFSET_CACHE
        global SUPPRESS_MARKER_OFFSET_UPDATE

        selected_only = context.scene.clip_tools_marker_offset_selected_only
        cache, message = make_marker_offset_cache(context, selected_only)
        if not cache:
            self.report({'WARNING'}, message)
            set_marker_offset_status(context, message)
            return {'CANCELLED'}

        MARKER_OFFSET_CACHE = cache
        SUPPRESS_MARKER_OFFSET_UPDATE = True
        try:
            context.scene.clip_tools_marker_offset = 0
        finally:
            SUPPRESS_MARKER_OFFSET_UPDATE = False

        set_marker_offset_status(context, message)
        self.report({'INFO'}, message)
        return {'FINISHED'}


def jump_selected_track_frames(context, direction, frame_getter, boundary_message, report):
    if not get_selected_navigation_tracks(context):
        report({'ERROR'}, "Select a track in the active tracking object.")
        return {'CANCELLED'}

    clip = get_clip(context)
    current_marker_frame = scene_to_marker_frame(clip, context.scene.frame_current)
    target_frame = find_neighbor_frame(
        frame_getter(context),
        current_marker_frame,
        direction,
    )
    if target_frame is None:
        report({'INFO'}, boundary_message)
        return {'CANCELLED'}

    set_current_marker_frame(context, target_frame)
    return {'FINISHED'}


def jump_selected_track_key(context, direction, report):
    if context.space_data.mode == 'MASK':
        from .mask_tools import jump_mask_key
        return jump_mask_key(context, direction, report)
    # Imported at execution time because plane tools use the common clip helpers.
    from .plane_track_tools import get_active_plane_track, jump_plane_key

    plane = get_active_plane_track(context)
    if plane is not None and (plane.select or getattr(context, "clip_tools_key_plane", None) == plane):
        return jump_plane_key(context, direction, report)
    boundary = ("No keyed marker frame found before the current frame."
                if direction == 'PREVIOUS' else "No keyed marker frame found after the current frame.")
    return jump_selected_track_frames(context, direction, get_selected_key_frames, boundary, report)


def track_key_jump_poll(cls, context):
    if getattr(context.space_data, "mode", None) == 'MASK':
        from .mask_tools import mask_tools_poll
        return mask_tools_poll(cls, context)
    if getattr(context, "clip_tools_key_plane", None) is not None:
        from .plane_track_tools import plane_track_poll
        return plane_track_poll(cls, context)
    return get_clip(context) is not None


class CLIP_OT_jump_selected_track_key_previous(Operator):
    bl_idname = "clip.jump_selected_track_key_previous"
    bl_label = "Previous Track Key"
    bl_description = "Jump to the previous keyframe on selected point/plane tracks or mask layers"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return track_key_jump_poll(cls, context)

    def execute(self, context):
        return jump_selected_track_key(context, 'PREVIOUS', self.report)


class CLIP_OT_jump_selected_track_key_next(Operator):
    bl_idname = "clip.jump_selected_track_key_next"
    bl_label = "Next Track Key"
    bl_description = "Jump to the next keyframe on selected point/plane tracks or mask layers"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return track_key_jump_poll(cls, context)

    def execute(self, context):
        return jump_selected_track_key(context, 'NEXT', self.report)


def jump_selected_track_range(context, direction, report):
    from .plane_track_tools import get_active_plane_track, jump_plane_range

    plane = get_active_plane_track(context)
    if plane is not None and plane.select:
        return jump_plane_range(context, direction, report)
    if not get_selected_navigation_tracks(context):
        report({'INFO'}, "Select a point or plane track in the active tracking object.")
        return {'CANCELLED'}
    boundary = ("No enabled tracking range boundary found before the current frame."
                if direction == 'PREVIOUS' else "No enabled tracking range boundary found after the current frame.")
    return jump_selected_track_frames(context, direction, get_selected_enabled_range_frames, boundary, report)


class CLIP_OT_jump_selected_track_range_previous(Operator):
    bl_idname = "clip.jump_selected_track_range_previous"
    bl_label = "Previous Track Range"
    bl_description = "Jump to the previous enabled range boundary on the selected point or plane track"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return get_clip(context) is not None

    def execute(self, context):
        return jump_selected_track_range(context, 'PREVIOUS', self.report)


class CLIP_OT_jump_selected_track_range_next(Operator):
    bl_idname = "clip.jump_selected_track_range_next"
    bl_label = "Next Track Range"
    bl_description = "Jump to the next enabled range boundary on the selected point or plane track"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return get_clip(context) is not None

    def execute(self, context):
        return jump_selected_track_range(context, 'NEXT', self.report)


class CLIP_OT_auto_interpolate_track_gap_with_islands(Operator):
    bl_idname = "clip.auto_interpolate_track_gap_with_islands"
    bl_label = "Track Bridge"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if get_clip(context) is None:
            self.report({'ERROR'}, "Open a clip in the Movie Clip Editor.")
            return {'CANCELLED'}

        clip = get_clip(context)
        settings = context.scene.track_gap_interp_settings
        current_scene_frame = context.scene.frame_current
        current_frame = scene_to_marker_frame(clip, current_scene_frame)
        tracks = [track for track in get_active_tracks(context) if is_track_selected(track)]
        if not tracks:
            self.report({'ERROR'}, "Select at least one track in the active tracking object to interpolate.")
            return {'CANCELLED'}

        processed = []
        skipped = []
        for track in tracks:
            result, error = interpolate_track_gap(track, current_frame, settings)
            if result is None:
                skipped.append(f"{track_label(track)}: {error}")
            else:
                processed.append((track, result))

        if not processed:
            self.report({'ERROR'}, skipped[0] if skipped else "No tracks processed.")
            return {'CANCELLED'}

        if settings.preview_enabled:
            settings.preview_enabled = False
        total_markers = sum(result["count"] for _, result in processed)
        first_result = processed[0][1]
        solution_status = " Solution cleared." if clear_clip_solution(context) else ""

        if skipped:
            self.report({'WARNING'}, f"Processed {len(processed)}/{len(tracks)} tracks. Skipped: {len(skipped)}")

        self.report(
            {'INFO'},
            f"{first_result['method']}: Baked {total_markers} markers on {len(processed)} track(s) near frame {current_scene_frame}.{solution_status}"
        )
        return {'FINISHED'}


class CLIP_OT_track_bridge_disable_range(Operator):
    bl_idname = "clip.track_bridge_disable_range"
    bl_label = "Clear Track Range"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if get_clip(context) is None:
            self.report({'ERROR'}, "Open a clip in the Movie Clip Editor.")
            return {'CANCELLED'}

        settings = context.scene.track_gap_interp_settings
        clip = get_clip(context)
        frame_start = scene_to_marker_frame(clip, settings.disable_range_start)
        frame_end = scene_to_marker_frame(clip, settings.disable_range_end)
        tracks = [track for track in get_active_tracks(context) if is_track_selected(track)]
        if not tracks:
            self.report({'ERROR'}, "Select at least one track in the active tracking object.")
            return {'CANCELLED'}

        processed = []
        skipped = []
        for track in tracks:
            result, error = disable_track_markers_in_range(
                track,
                frame_start,
                frame_end,
            )
            if result is None:
                skipped.append(f"{track_label(track)}: {error}")
            else:
                processed.append((track, result))

        if not processed:
            self.report({'ERROR'}, skipped[0] if skipped else "No keys disabled.")
            return {'CANCELLED'}

        total = sum(result["count"] for _, result in processed)
        scene_start = min(settings.disable_range_start, settings.disable_range_end)
        scene_end = max(settings.disable_range_start, settings.disable_range_end)
        solution_status = " Solution cleared." if clear_clip_solution(context) else ""

        if skipped:
            self.report({'WARNING'}, f"Disabled keys on {len(processed)}/{len(tracks)} tracks. Skipped: {len(skipped)}")

        self.report(
            {'INFO'},
            f"Disabled {total} key(s) on {len(processed)} track(s), frames {scene_start}-{scene_end}.{solution_status}"
        )
        return {'FINISHED'}


class CLIP_OT_track_bridge_set_disable_range_start(Operator):
    bl_idname = "clip.track_bridge_set_disable_range_start"
    bl_label = "Set Clear Track Range In"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.track_gap_interp_settings.disable_range_start = context.scene.frame_current
        return {'FINISHED'}


class CLIP_OT_track_bridge_set_disable_range_end(Operator):
    bl_idname = "clip.track_bridge_set_disable_range_end"
    bl_label = "Set Clear Track Range Out"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.track_gap_interp_settings.disable_range_end = context.scene.frame_current
        return {'FINISHED'}


def draw_track_jump_buttons(row):
    row.operator(CLIP_OT_jump_selected_track_range_previous.bl_idname, text="", icon='TRIA_LEFT_BAR')
    row.operator(CLIP_OT_jump_selected_track_key_previous.bl_idname, text="", icon='PREV_KEYFRAME')
    row.operator(CLIP_OT_jump_selected_track_key_next.bl_idname, text="", icon='NEXT_KEYFRAME')
    row.operator(CLIP_OT_jump_selected_track_range_next.bl_idname, text="", icon='TRIA_RIGHT_BAR')


def key_navigation_context(context):
    return ('EXEC_REGION_PREVIEW' if context.space_data.view in {'GRAPH', 'DOPESHEET'}
            else 'EXEC_REGION_WIN')


def draw_track_jump_button_row(layout, context):
    previous_context = layout.operator_context
    layout.operator_context = key_navigation_context(context)
    try:
        row = layout.row(align=True)
        draw_track_jump_buttons(row)
    finally:
        layout.operator_context = previous_context


def draw_track_jump_header(self, context):
    space = context.space_data
    if not space or space.type != 'CLIP_EDITOR' or space.view not in {'GRAPH', 'DOPESHEET'}:
        return
    if get_clip(context) is None:
        return

    draw_track_jump_button_row(self.layout, context)


def draw_track_jump_tools_tracking(self, context):
    if get_clip(context) is None:
        return

    row = self.layout.row(align=True)
    row.label(text="Jump:")
    previous_context = row.operator_context
    row.operator_context = key_navigation_context(context)
    draw_track_jump_buttons(row)
    row.operator_context = previous_context


class CLIP_PT_track_time_offset(Panel):
    """UI panel for offsetting tracking marker frames."""
    bl_label = "Track Time Offset"
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Tool"

    @classmethod
    def poll(cls, context):
        return get_clip(context) is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        tracking_object = get_active_tracking_object(context)

        if scene.clip_tools_marker_offset_selected_only:
            active_name = tracking_object.name if tracking_object else "None"
            layout.label(text=f"Active: {active_name}")
        else:
            layout.label(text="Scope: All Tracking Objects")

        row = layout.row(align=True)
        row.prop(scene, "clip_tools_marker_offset_selected_only")
        row.operator(CLIP_OT_marker_offset_get_source.bl_idname, text="Get Trackers")

        layout.prop(scene, "clip_tools_marker_offset")
        skipped_count = count_marker_offset_before_frame_one(scene.clip_tools_marker_offset)
        if skipped_count:
            layout.label(text="Before Start Frame are removed", icon='ERROR')

        if scene.clip_tools_marker_offset_status:
            layout.label(text=scene.clip_tools_marker_offset_status)


class CLIP_PT_auto_interpolate_track_gap_with_islands(Panel):
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Tool'
    bl_label = "Track Bridge"

    @classmethod
    def poll(cls, context):
        return get_clip(context) is not None

    def draw(self, context):
        layout = self.layout
        settings = context.scene.track_gap_interp_settings
        col = layout.column(align=True)
        col.prop(settings, "interpolation_method", text="")

        row = col.row(align=True)
        row.prop(settings, "join_short_islands", text="Join")
        sub = row.row(align=True)
        sub.enabled = settings.join_short_islands
        sub.prop(settings, "max_island_length")

        row = col.row(align=True)
        row.prop(settings, "outer_reference_keys")
        tangent_col = row.row(align=True)
        tangent_col.enabled = settings.interpolation_method in {'CATMULL_ROM', 'AKIMA'}
        tangent_col.prop(settings, "tangent_strength")
        col.prop(settings, "preview_enabled", toggle=True, icon='HIDE_OFF')
        if settings.preview_enabled:
            from . import track_bridge_preview
            status = track_bridge_preview.status_for_context(context)
            if status:
                col.label(text=status, icon='INFO')
        col.operator(CLIP_OT_auto_interpolate_track_gap_with_islands.bl_idname, text="Bridge Gap")


class CLIP_PT_track_bridge_disable_range(Panel):
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Tool'
    bl_label = "Clear Track Range"

    @classmethod
    def poll(cls, context):
        return get_clip(context) is not None

    def draw(self, context):
        layout = self.layout
        settings = context.scene.track_gap_interp_settings
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator(CLIP_OT_track_bridge_set_disable_range_start.bl_idname, text="", icon='TRIA_LEFT_BAR')
        row.prop(settings, "disable_range_start", text="In")
        row.prop(settings, "disable_range_end", text="Out")
        row.operator(CLIP_OT_track_bridge_set_disable_range_end.bl_idname, text="", icon='TRIA_RIGHT_BAR')
        col.operator(CLIP_OT_track_bridge_disable_range.bl_idname, text="Clear Track Range")


_LEGACY_KEY_JUMPS = {
    "clip.plane_track_key_previous": "clip.jump_selected_track_key_previous",
    "clip.plane_track_key_next": "clip.jump_selected_track_key_next",
    "mask.clip_tools_key_previous": "clip.jump_selected_track_key_previous",
    "mask.clip_tools_key_next": "clip.jump_selected_track_key_next",
}
_KEY_EVENT_FIELDS = ('type', 'value', 'any', 'shift', 'ctrl', 'alt', 'oskey',
                     'key_modifier', 'direction', 'repeat')
if 'hyper' in bpy.types.KeyMapItem.bl_rna.properties:
    _KEY_EVENT_FIELDS += ('hyper',)


def migrate_legacy_key_jumps():
    # Run after keymaps initialize, not during restricted addon registration.
    wm = bpy.context.window_manager
    if not wm or not wm.keyconfigs.user:
        return None
    keymaps = wm.keyconfigs.user.keymaps
    legacy = [(keymap, item) for keymap in keymaps for item in keymap.keymap_items
              if item.idname in _LEGACY_KEY_JUMPS]
    if not legacy:
        return None
    target = keymaps.get("Clip")
    if target is None:
        target = keymaps.new(name="Clip", space_type='CLIP_EDITOR', region_type='WINDOW')
    for keymap, item in legacy:
        idname = _LEGACY_KEY_JUMPS[item.idname]
        event = {field: getattr(item, field) for field in _KEY_EVENT_FIELDS}
        duplicate = next((other for other in target.keymap_items
                          if other != item and other.idname == idname and other.active == item.active
                          and all(getattr(other, field) == value for field, value in event.items())), None)
        if duplicate is not None:
            keymap.keymap_items.remove(item)
        elif keymap == target:
            item.idname = idname
        else:
            replacement = target.keymap_items.new(idname, **event)
            replacement.active = item.active
            keymap.keymap_items.remove(item)
    bpy.context.preferences.is_dirty = True
    return None


classes = (
    TrackGapInterpSettings,
    CLIP_OT_marker_offset_get_source,
    CLIP_OT_jump_selected_track_key_previous,
    CLIP_OT_jump_selected_track_key_next,
    CLIP_OT_jump_selected_track_range_previous,
    CLIP_OT_jump_selected_track_range_next,
    CLIP_OT_auto_interpolate_track_gap_with_islands,
    CLIP_OT_track_bridge_disable_range,
    CLIP_OT_track_bridge_set_disable_range_start,
    CLIP_OT_track_bridge_set_disable_range_end,
    CLIP_PT_track_time_offset,
    CLIP_PT_auto_interpolate_track_gap_with_islands,
    CLIP_PT_track_bridge_disable_range,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if hasattr(bpy.types, "CLIP_HT_header"):
        bpy.types.CLIP_HT_header.append(draw_track_jump_header)
    if hasattr(bpy.types, "CLIP_PT_tools_tracking"):
        bpy.types.CLIP_PT_tools_tracking.append(draw_track_jump_tools_tracking)

    bpy.types.Scene.clip_tools_marker_offset = IntProperty(
        name="Frame Offset",
        default=0,
        description="Positive = later, Negative = earlier",
        update=on_marker_offset_changed,
    )
    bpy.types.Scene.clip_tools_marker_offset_selected_only = BoolProperty(name="Selected Only", default=False)
    bpy.types.Scene.clip_tools_marker_offset_status = StringProperty(name="Status", default="")
    bpy.types.Scene.track_gap_interp_settings = PointerProperty(type=TrackGapInterpSettings)
    from . import track_bridge_preview
    track_bridge_preview.register()
    bpy.app.timers.register(migrate_legacy_key_jumps, first_interval=0.0)


def unregister():
    if bpy.app.timers.is_registered(migrate_legacy_key_jumps):
        bpy.app.timers.unregister(migrate_legacy_key_jumps)
    from . import track_bridge_preview
    track_bridge_preview.unregister()
    global MARKER_OFFSET_CACHE
    global SUPPRESS_MARKER_OFFSET_UPDATE
    MARKER_OFFSET_CACHE = None
    SUPPRESS_MARKER_OFFSET_UPDATE = False

    if hasattr(bpy.types.Scene, "track_gap_interp_settings"):
        del bpy.types.Scene.track_gap_interp_settings
    if hasattr(bpy.types.Scene, "clip_tools_marker_offset_status"):
        del bpy.types.Scene.clip_tools_marker_offset_status
    if hasattr(bpy.types.Scene, "clip_tools_marker_offset_selected_only"):
        del bpy.types.Scene.clip_tools_marker_offset_selected_only
    if hasattr(bpy.types.Scene, "clip_tools_marker_offset"):
        del bpy.types.Scene.clip_tools_marker_offset

    if hasattr(bpy.types, "CLIP_HT_header"):
        try:
            bpy.types.CLIP_HT_header.remove(draw_track_jump_header)
        except (AttributeError, RuntimeError, ValueError):
            pass
    if hasattr(bpy.types, "CLIP_PT_tools_tracking"):
        try:
            bpy.types.CLIP_PT_tools_tracking.remove(draw_track_jump_tools_tracking)
        except (AttributeError, RuntimeError, ValueError):
            pass

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
