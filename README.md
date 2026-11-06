# Blender Addon: Clip Tools

## Overview
**Clip Tools** is a utility addon for the **Movie Clip Editor** in Blender.  

---

## Tools

### Set Start Seq No.
**Location:** `Toolbar > Track Tab > Clip > Set Start Seq No.`

- Sets the clip start frame from the sequence number in the original source filename, unaffected by Blender's duplicate clip naming.
- Supports names such as `clip_1001.jpg`, `Test1001.jpg`, and `00000001.jpg`, and updates the scene frame range.
- For movie files, runs Blender's **Set Scene Frames** and jumps to the start frame, without reading a frame number from the filename or changing the clip start frame.
- If no sequence number is detected, runs Blender's **Set Scene Frames** without changing the clip start frame.
- Use the reset icon beside the button to set the clip start frame to 1 and update the scene frame range.

---

### Setup Camera Solver
**Location:** `Toolbar > Solve Tab > Scene Setup > Setup Camera Solver` or `Header > Clip Menus`

- Adds and configures a **Camera Solver Constraint** to the active scene camera.
- Useful when you want to set up a Camera Solver without adding extra objects typically created by Blender's **Setup Tracking Scene**.

---

### Setup Object Solver
**Location:** `Toolbar > Solve Tab > Scene Setup > Setup Object Solver` or `Header > Clip Menus`

- Creates an Empty object named **ObjectTrack** and sets up an **Object Solver Constraint**.
- Available only when a **Tracking Object** has been added to the Movie Clip.
- The constraint is automatically configured to use the active Tracking Object name.

---

### Duplicate Active Clip
**Location:** `Header > Clip Menus > Duplicate Active Clip`

- Create a duplicate of the data block of the active movie clip containing all tracking data.
- Ideal when you want to:
  - Split tracking tasks on the same footage.
  - Test different parameter settings independently.
- Optionally, enable **Fake User** to prevent accidental deletion of the duplicated data block.

---

### Delete Active Clip
**Location:** `Header > Clip Menus > Delete Active Clip`

- Deletes the active Movie Clip from the data block.
- Useful for quickly cleaning up unused clips.

---

### Track Jump
**Location:** `Toolbar > Track Tab > Track > Jump` or `Graph/Dopesheet Header`

- Use the inner buttons to jump to the previous or next keyed marker on the selected point or plane track.
- Use the outer buttons to move through the start and end of each enabled tracking range, including separated tracking islands.
- Custom shortcuts can be assigned through Blender's standard button context menu. No default shortcuts are assigned.
- Previous/next key shortcuts are shared across the Track panel, Graph/Dopesheet headers, Plane Track, and Mask Animation buttons.

---

### 3D Markers to Empty
**Location:** `Toolbar > Solve Tab > Geometry` or `Header > Reconstruction Menus`

- Converts 3D tracking markers into actual **Empty objects**, similar to other matchmoving software.
- Especially useful when exporting to other 3D applications.
- Workflow:
  - A parent Empty named `"Trackpoint"` will be automatically created.
  - The selected tracking point is parented to  `"Trackpoint"` .
  - The display size of the Empties can be adjusted via the parent’s property and is linked via drivers.

---

### Create Image Plane
**Location:** `Toolbar > Solve Tab > Geometry` or `Header > Reconstruction Menus`

- Creates an actual “image plane” in the 3D view that links the Active Movie Clip to the Active camera.
- Supports:
  - Start frame offset.
  - Camera sensor shift.
  - Image Sequences and Movie Files.  

- Useful for workflows similar to Maya's image plane system.

> **Note for Blender 4.4 and Later:** 
Due to changes in driver and dependency graph evaluation in Blender 4.4, driver-based setups may become unstable or display visual glitches during playback.

---

### Set Camera Projection
**Location:** `Toolbar > Solve Tab > Geometry` or `Header > Reconstruction Menus`

- Automatically sets up a **Camera Projection Shader** on the selected mesh using the active Movie Clip and active camera.
- Supports:
  - Start frame offset.
  - Camera sensor shift.
  - Image Sequences and Movie Files.

- Useful for:
  - Checking tracking accuracy.
  - Relighting workflows.

> **Note:** Texture projection is not displayed in Solid View. Please use Material Preview or Rendered modes.


---

### Orientation Plus
**Location:** `Toolbar > Solve Tab > Orientation Plus`
- Orientation Plus provides an extended orientation workflow for solved Movie Clips. Unlike Blender’s standard Floor and Wall tools, it can use one or more selected reconstructed trackers and align their contact plane while preserving the current camera orientation as much as possible.

- Choose the target plane from **Target Surface**. Use `+Z/-Z Floor` for floor alignment, or `+X/-X/+Y/-Y Wall` for wall alignment.

- Use **Position Mode** to decide how the plane is placed:
  - **Move Plane To** moves the selected tracker center to the chosen coordinate.
  - **Keep Camera XY** (default) keeps the camera's world X/Y position and moves the tracker plane vertically to the chosen coordinate's Z value, rather than setting the camera's own height.

- The coordinate can come from the world origin, the 3D cursor, or a manual XYZ value. For multiple trackers, **Track Center** can use either Average or Median.

- Tracker selection:
  - 1 tracker: position alignment with target direction/side correction
  - 2 trackers: constrained angle correction
  - 3 or more trackers: fitted plane alignment

- Use this after re-tracking or re-solving when you want to re-align the scene contact plane without rebuilding the orientation from scratch.

---

### Plane Track
**Location:** `Sidebar > Track Tab > Plane Track`

- **Create Plane Track:** When no plane track is active, select exactly four enabled point markers at the current frame and create a plane using their actual corner positions rather than a bounding box. The points must form a convex quadrilateral.
- **Previous / Next Key:** Jump between the active plane track's keys, including those created with **Auto Keyframe**.
- **Insert Key:** Record the current frame's four-corner shape, or update an existing key.
- **Delete Key:** Remove the current frame's key and recalculate the surrounding motion.
- **Update:** Use the refresh icon after editing the source point tracks to recalculate the plane motion while preserving its keyed shapes.
- **Clear All:** Remove all plane track keys.

> **Note:** When **Auto Keyframe** is OFF, editing the plane resets existing keys as part of Blender's standard behavior. Creating a plane or inserting a key with these tools automatically turns Auto Keyframe ON.

---

### Mask Animation
**Location:** `Toolbar > Mask Tab > Mask Tools > Animation`

- Use the added keyframe icons to jump to the previous or next mask shape key, or clear all keys. Use the existing **Insert Key / Clear Key** buttons to add or remove a key at the current frame.
- Previous/next key navigation shares the Track Jump operators, so the same custom shortcuts work in both Tracking and Mask modes.
- Operations affect editable mask layers containing selected points. Shape keys store the entire layer, not individual points.

---

### Track Time Offset  
**Location:** `Sidebar > Tool Tab > Track Time Offset`
- Offsets tracking marker keys forward or backward in time. Click **Get Trackers** first to cache the current marker keys, then adjust **Frame Offset**. Positive values move keys later, and negative values move keys earlier.  

> **Note:**  
> If the cache is lost, markers shifted before frame 1 cannot be restored and may be removed. The camera solve is cleared after applying an offset.  
> Due to the way this tool applies the offset, the resulting trackers will have marker keys on every captured frame.

---

### Track Bridge  
**Location:** `Sidebar > Tool Tab > Track Bridge`
- Fills an OFF or missing tracking gap by interpolating new marker positions. Select the track, place the timeline cursor near the gap you want to fill, choose an interpolation method, then click **Bridge Gap**. The gap closest to the current frame is processed. Enable **Join** to automatically bridge across short enabled marker islands as part of the same gap.

- Enable **Preview** to compare the proposed interpolation with the existing track path before applying it. The preview updates as settings change without modifying marker data, and turns OFF automatically after a successful **Bridge Gap** operation.
- Preview is available in **Clip View**. Disable Stabilized View, and disable Undistorted View when lens distortion is present.
- Only marker positions are interpolated. Other marker parameters, including the pattern and search area, are copied from the preceding marker.

**Interpolation Methods**

- **Linear:** Creates a straight interpolation between the surrounding enabled keys.
- **Ease Linear:** Keeps a straight path, but eases the timing near the surrounding keys.
- **Trend Hermite:** Creates a curved interpolation that follows the motion trend from nearby reference keys. The Tangent value controls how strongly the curve bends.
- **Natural Cubic:** Creates a smooth spline through the reference keys. Good for soft, continuous motion.
- **Akima:** Creates a smooth curve with reduced overshoot, useful for uneven or noisy marker motion. The Tangent value controls the curve strength.

**Tangent** is available only for **Trend Hermite** and **Akima**.

> **Note:**  
> This is a simple interpolation tool. Bridged marker positions may affect the camera solve negatively depending on the shot and tracking quality.

---

### Clear Track Range  
**Location:** `Sidebar > Tool Tab > Clear Track Range`
- Turns selected tracking markers OFF within the specified frame range. Set the **In** and **Out** frames manually or with the arrow buttons, then click **Clear Track Range**.
- Only selected point tracks in the active tracking object are affected, including object tracks.
