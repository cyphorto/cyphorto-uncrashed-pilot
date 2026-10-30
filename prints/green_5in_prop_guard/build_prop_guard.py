"""5-inch FPV propeller guard for Bambu Lab A1 / A1 mini (green filament).

Run with Blender 4.2+:
    blender -b --factory-startup --python-exit-code 1 -P build_prop_guard.py

Units: 1 Blender unit = 1 mm (so the exported STL is already in mm for
Bambu Studio). Z is up, the part sits flat on the build plate (Z=0).

Design (all mm):
  Propeller:            5 inch = 127.0 diameter
  Guard inner diameter: 134.0  (3.5 mm tip clearance per side)
  Guard wall:           3.6 thick  -> outer diameter 141.2
  Guard height:         18.0
  Mounting tabs:        4x at 0/90/180/270 deg, on the bottom face,
                        reaching inwards, each with a slotted M3 hole
                        so it can be screwed or zip-tied to an arm.
  Stiffening ribs:      8x small ribs on the outer wall.
Outputs next to this script: .blend, .stl, preview .png
"""

import bpy
import math
import os

OUT_DIR = os.environ.get("GUARD_OUT") or os.path.dirname(os.path.abspath(__file__))
NAME = "green_5in_prop_guard"

# --- tunables (mm) -------------------------------------------------------
PROP_DIA = 127.0
INNER_R = 67.0            # 134.0 inner diameter
WALL = 3.6
OUTER_R = INNER_R + WALL  # 70.6 -> 141.2 outer diameter
HEIGHT = 18.0
TAB_COUNT = 4
TAB_LEN = 18.0            # radial reach inwards from inner wall
TAB_WID = 14.0
TAB_THICK = 3.0
SLOT_LEN = 8.0            # M3 slot, adjustable along the radius
SLOT_R = 1.7              # 3.4 mm wide slot for M3 screw / zip-tie
RIB_COUNT = 8


def clean_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        pass  # orphan purge below handles leftovers
    bpy.ops.outliner.orphans_purge(do_recursive=True)


def green_material():
    mat = bpy.data.materials.new("GreenFilament")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.05, 0.65, 0.12, 1.0)  # green
    bsdf.inputs["Roughness"].default_value = 0.45
    return mat


def add_cylinder(name, radius, depth, location, vertices=128):
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius, depth=depth, location=location, vertices=vertices
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_box(name, size, location, rotation_z=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.dimensions = size
    obj.rotation_euler[2] = rotation_z
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def boolean(target, cutter, op):
    mod = target.modifiers.new(name="bool", type="BOOLEAN")
    mod.operation = op
    mod.solver = "EXACT"
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def build_guard(mat):
    # Main ring: outer cylinder minus inner cylinder.
    ring = add_cylinder("GuardRing", OUTER_R, HEIGHT, (0, 0, HEIGHT / 2))
    cutter = add_cylinder("InnerCut", INNER_R, HEIGHT + 4, (0, 0, HEIGHT / 2))
    boolean(ring, cutter, "DIFFERENCE")

    # Mounting tabs on the bottom face + slotted M3 holes.
    for i in range(TAB_COUNT):
        ang = math.radians(90 * i)
        # Tab reaches from inside the wall inwards.
        mid_r = INNER_R - TAB_LEN / 2 + 2.0  # 2 mm overlap into the wall
        loc = (mid_r * math.cos(ang), mid_r * math.sin(ang), TAB_THICK / 2)
        tab = add_box("Tab", (TAB_LEN + 2.0, TAB_WID, TAB_THICK), loc, rotation_z=ang)
        boolean(ring, tab, "UNION")

        # Slot: two cylinders + connecting box, cut through the tab.
        slot_mid_r = INNER_R - TAB_LEN / 2
        for off in (-SLOT_LEN / 2, SLOT_LEN / 2):
            r = slot_mid_r + off
            hole = add_cylinder(
                "SlotEnd", SLOT_R, TAB_THICK + 2,
                (r * math.cos(ang), r * math.sin(ang), TAB_THICK / 2), vertices=32,
            )
            boolean(ring, hole, "DIFFERENCE")
        r = slot_mid_r
        slot_box = add_box(
            "SlotMid", (SLOT_LEN, SLOT_R * 2, TAB_THICK + 2),
            (r * math.cos(ang), r * math.sin(ang), TAB_THICK / 2), rotation_z=ang,
        )
        boolean(ring, slot_box, "DIFFERENCE")

    # Stiffening ribs on the outer wall, offset 22.5 deg from the tabs.
    for i in range(RIB_COUNT):
        ang = math.radians(45 * i + 22.5)
        r = OUTER_R - 0.5  # half sunk into the wall
        loc = (r * math.cos(ang), r * math.sin(ang), HEIGHT / 2)
        rib = add_box("Rib", (3.0, 2.4, HEIGHT - 4.0), loc, rotation_z=ang)
        boolean(ring, rib, "UNION")

    ring.data.materials.append(mat)
    # Smooth the round walls, keep the flat faces flat.
    for poly in ring.data.polygons:
        poly.use_smooth = abs(poly.normal.z) < 0.5
    return ring


def add_text_label(mat):
    bpy.ops.object.text_add(location=(0, -OUTER_R - 14, 0))
    txt = bpy.context.active_object
    txt.name = "Label_NotPrinted"
    txt.data.body = "5in PROP GUARD - 134mm ID"
    txt.data.size = 9
    txt.data.align_x = "CENTER"
    # Kept as a scene note only; excluded from the STL export.
    return txt


def setup_render(guard):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(OUT_DIR, NAME + "_preview.png")
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.85, 0.85, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.7

    # Ground plane (render only, not exported).
    bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, -0.01))
    ground = bpy.context.active_object
    ground.name = "Ground_RenderOnly"
    gmat = bpy.data.materials.new("Ground")
    gmat.use_nodes = True
    gmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        0.75, 0.75, 0.75, 1)
    ground.data.materials.append(gmat)

    bpy.ops.object.camera_add(location=(150, -170, 130))
    cam = bpy.context.active_object
    cam.name = "Camera"
    cam.rotation_euler = (math.radians(58), 0, math.radians(41))
    cam.data.lens = 50
    scene.camera = cam

    bpy.ops.object.light_add(type="AREA", location=(80, -60, 160))
    key = bpy.context.active_object
    key.data.energy = 90000  # mm scale scene, so a large value is needed
    key.data.shape = "DISK"
    key.data.size = 120
    key.rotation_euler = (math.radians(35), 0, math.radians(30))

    bpy.ops.object.light_add(type="AREA", location=(-120, 80, 90))
    fill = bpy.context.active_object
    fill.data.energy = 40000
    fill.data.size = 120
    fill.rotation_euler = (math.radians(60), 0, math.radians(-120))


def main():
    clean_scene()
    mat = green_material()
    guard = build_guard(mat)
    add_text_label(mat)
    setup_render(guard)

    # Export only the guard itself.
    bpy.ops.object.select_all(action="DESELECT")
    guard.select_set(True)
    bpy.context.view_layer.objects.active = guard
    stl_path = os.path.join(OUT_DIR, NAME + ".stl")
    bpy.ops.wm.stl_export(filepath=stl_path, export_selected_objects=True)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, NAME + ".blend"))
    bpy.ops.render.render(write_still=True)

    dims = guard.dimensions
    print(f"EXPORTED {stl_path}")
    print(f"SIZE_MM X={dims.x:.1f} Y={dims.y:.1f} Z={dims.z:.1f}")
    print(f"VERTS {len(guard.data.vertices)} FACES {len(guard.data.polygons)}")


if __name__ == "__main__":
    main()
