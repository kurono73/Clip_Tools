# Blender Addon: Clip Tools

## Overview
**Clip Tools** is a utility addon for the **Movie Clip Editor** in Blender.  

---

## Tools

### Set Start Seq No.
**Location:** `Toolbar > Track Tab > Clip > Set Start Seq No.`

- Automatically sets the start frame based on the sequence number from the loaded footage filename.
- Useful for quickly syncing the timeline to the imported sequence.

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
