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
**Location:** `Toolbar > Solve > Geometry` or `Header > Reconstruction Menus`

- Converts 3D tracking markers into actual **Empty objects**, similar to other matchmoving software.
- Especially useful when exporting to other 3D applications.
- Workflow:
  - A parent Empty named `"Trackpoint"` will be automatically created.
  - The selected tracking point is parented to  `"Trackpoint"` .
  - The display size of the Empties can be adjusted via the parent’s property and is linked via drivers.

---

### Create Image Plane
**Location:** `Toolbar > Solve > Geometry` or `Header > Reconstruction Menus`

- Creates an actual “image plane” in the 3D view that links the Active Movie Clip to the Active camera.
- Supports:
  - Start frame offset.
  - Camera sensor shift.
  - Image Sequences and Movie Files.  

- Useful for workflows similar to Maya's image plane system.

---

### Set Camera Projection
**Location:** `Toolbar > Solve > Geometry` or `Header > Reconstruction Menus`

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
