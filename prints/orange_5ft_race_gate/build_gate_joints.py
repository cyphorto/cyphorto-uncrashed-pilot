"""5 ft FPV race gate - 3D-printed joints for 3/4 inch PVC pipe.

Run with Blender 4.2+:
    blender -b --factory-startup --python-exit-code 1 -P build_gate_joints.py

Units: 1 Blender unit = 1 mm. Z is up, parts sit on the plate (Z=0).

You print 4 parts and buy PVC pipe. The printer never prints the gate
itself - it prints the joints, the pipe is the gate:

  gate_corner_elbow.stl        x2  top corners (same part, flipped)
  gate_foot_corner_left.stl    x1  bottom left (post + bottom bar + foot)
  gate_foot_corner_right.stl   x1  bottom right (mirror of left)

Design (all mm):
  Pipe:        3/4" PVC, outside diameter 26.7
  Socket:      27.6 bore (0.45 radial clearance), 45 deep, 3.8 wall
  Pin hole:    4.2 through each socket (M4 bolt / screw, optional)
  Horizontal pipe bores have a pointed (teardrop) roof so they print
  on a Bambu plate with no support inside the socket.
  Gate:        pipe centrelines 1560 x 1560, clear opening 1533 x 1533
               (5 ft = 1524), bottom bar centre 50 above the ground.

Pipe cut list (see BLUEPRINT.md): posts 2x 1555, bars 2x 1510,
foot pipes 2x 600. Total 7.33 m of 3/4" PVC.

Outputs next to this script: 3x .stl, assembly .blend, preview .png
"""

import bpy
import math
import os
from mathutils import Matrix, Vector

OUT_DIR = os.environ.get("GATE_OUT") or os.path.dirname(os.path.abspath(__file__))

# --- tunables (mm) -------------------------------------------------------
PIPE_OD = 26.7
SOCKET_R = 13.8           # 27.6 bore
OUTER_R = 17.6            # 3.8 wall around the socket
SOCKET_DEPTH = 45.0
PIN_R = 2.1               # 4.2 pin / M4 hole
GATE_CL = 1560.0          # pipe centreline spacing, width and height
BOTTOM_CL_Z = 50.0        # bottom bar centreline above ground
TOP_CL_Z = BOTTOM_CL_Z + GATE_CL
POST_LEN = 1555.0
BAR_LEN = 1510.0
FOOT_PIPE_LEN = 600.0


def clean_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.outliner.orphans_purge(do_recursive=True)


def orange_material(name="OrangeFilament", shade=(1.0, 0.32, 0.04)):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*shade, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.45
    return mat


def add_cylinder(name, radius, depth, location, axis="Z", vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius, depth=depth, location=location, vertices=vertices)
    obj = bpy.context.active_object
    obj.name = name
    if axis == "X":
        obj.rotation_euler = (0, math.radians(90), 0)
    elif axis == "Y":
        obj.rotation_euler = (math.radians(90), 0, 0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return obj


def add_box(name, size, location, rot_axis=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.dimensions = size
    if rot_axis == "X":
        obj.rotation_euler = (math.radians(45), 0, 0)
    elif rot_axis == "Y":
        obj.rotation_euler = (0, math.radians(45), 0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return obj


def boolean(target, cutter, op):
    mod = target.modifiers.new(name="bool", type="BOOLEAN")
    mod.operation = op
    mod.solver = "EXACT"
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def cut_socket(target, centre, axis, wedge=True):
    """Cut one 45 mm pipe socket. centre = (x, y, z) of the bore centre."""
    bore = add_cylinder("Bore", SOCKET_R, SOCKET_DEPTH + 4, centre, axis=axis)
    boolean(target, bore, "DIFFERENCE")
    if wedge and axis in ("X", "Y"):
        # Pointed roof above a horizontal bore: prints without support.
        size = ((SOCKET_DEPTH + 4, 12, 12) if axis == "X"
                else (12, SOCKET_DEPTH + 4, 12))
        roof = add_box("BoreRoof", size,
                       (centre[0], centre[1], centre[2] + 8.5), rot_axis=axis)
        boolean(target, roof, "DIFFERENCE")


def cut_pin(target, location, axis="Y"):
    hole = add_cylinder("Pin", PIN_R, OUTER_R * 2 + 10, location, axis=axis,
                        vertices=24)
    boolean(target, hole, "DIFFERENCE")


def finish(obj, mat):
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.use_smooth = abs(poly.normal.z) < 0.5
    return obj


def export_stl(obj, filename):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    path = os.path.join(OUT_DIR, filename)
    bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True)
    d = obj.dimensions
    print(f"EXPORTED {path}")
    print(f"SIZE_MM X={d.x:.1f} Y={d.y:.1f} Z={d.z:.1f}")


def build_elbow(mat):
    """Top corner: vertical socket + horizontal socket, printed L-up."""
    part = add_cylinder("ElbowVert", OUTER_R, 70, (0, 0, 35), axis="Z")
    arm = add_cylinder("ElbowArm", OUTER_R, 88, (26, 0, OUTER_R), axis="X")
    boolean(part, arm, "UNION")
    pad = add_box("ElbowPad", (64, 30, 5), (28, 0, 2.5))
    boolean(part, pad, "UNION")
    # Vertical bore: mouth at z=70, floor at z=25.
    cut_socket(part, (0, 0, 70 - SOCKET_DEPTH / 2 + 2), "Z", wedge=False)
    # Horizontal bore: mouth at x=70, floor at x=25, teardrop roof.
    cut_socket(part, (70 - SOCKET_DEPTH / 2 + 2, 0, OUTER_R), "X")
    cut_pin(part, (0, 0, 48))
    cut_pin(part, (48, 0, OUTER_R))
    return finish(part, mat)


def build_foot(mat, sign, label):
    """Bottom corner: post socket up, bottom-bar socket sideways (+-X),
    and a through foot bore (Y) over a flat base plate. sign=+1: bar
    points +X (left foot). sign=-1: bar points -X (right foot)."""
    part = add_box(f"Foot{label}Plate", (46, 130, 6), (0, 0, 3))
    foot = add_cylinder("FootBarrel", OUTER_R, 120, (0, 0, 23.6), axis="Y")
    boolean(part, foot, "UNION")
    post = add_cylinder("FootPost", OUTER_R, 69, (0, 0, 40.5), axis="Z")
    boolean(part, post, "UNION")
    bar = add_cylinder("FootBar", OUTER_R, 88, (sign * 26, 0, BOTTOM_CL_Z),
                       axis="X")
    boolean(part, bar, "UNION")
    # Foot bore straight through (pipe slides in, centred by eye).
    bore = add_cylinder("FootBore", SOCKET_R, 124, (0, 0, 23.6), axis="Y")
    boolean(part, bore, "DIFFERENCE")
    roof = add_box("FootBoreRoof", (12, 124, 12), (0, 0, 23.6 + 8.5),
                   rot_axis="Y")
    boolean(part, roof, "DIFFERENCE")
    # Post bore: mouth at z=75, floor at z=30.
    cut_socket(part, (0, 0, 75 - SOCKET_DEPTH / 2 + 2), "Z", wedge=False)
    # Bottom-bar bore: mouth at x=sign*70, floor at x=sign*25.
    cut_socket(part, (sign * (70 - SOCKET_DEPTH / 2 + 2), 0, BOTTOM_CL_Z), "X")
    cut_pin(part, (0, 0, 53))
    return finish(part, mat)


def add_pipe(name, radius, length, location, axis, mat):
    pipe = add_cylinder(name, radius, length, location, axis=axis, vertices=32)
    pipe.data.materials.append(mat)
    return pipe


def look_at_camera(cam, location, target):
    direction = Vector(target) - Vector(location)
    cam.matrix_world = Matrix.Translation(location) @ (
        direction.to_track_quat("-Z", "Y").to_matrix().to_4x4())


def build_assembly(elbow, foot_l, foot_r, joint_mat, pipe_mat):
    """Assembled gate for the preview render and the saved .blend.
    Render/setup evidence only - the STLs above are what you print."""
    half = GATE_CL / 2
    parts = []
    for src, loc, rot in (
        (foot_l, (-half, 0, 0), (0, 0, 0)),
        (foot_r, (half, 0, 0), (0, 0, 0)),
        (elbow, (-half, 0, TOP_CL_Z + OUTER_R), (180, 0, 0)),
        (elbow, (half, 0, TOP_CL_Z + OUTER_R), (180, 0, 180)),
    ):
        dup = src.copy()
        bpy.context.scene.collection.objects.link(dup)
        dup.location = loc
        dup.rotation_euler = tuple(math.radians(a) for a in rot)
        parts.append(dup)

    r = PIPE_OD / 2
    post_cz = (30 + (TOP_CL_Z - 25)) / 2
    parts.append(add_pipe("PostL", r, POST_LEN, (-half, 0, post_cz), "Z", pipe_mat))
    parts.append(add_pipe("PostR", r, POST_LEN, (half, 0, post_cz), "Z", pipe_mat))
    parts.append(add_pipe("BarTop", r, BAR_LEN, (0, 0, TOP_CL_Z), "X", pipe_mat))
    parts.append(add_pipe("BarBot", r, BAR_LEN, (0, 0, BOTTOM_CL_Z), "X", pipe_mat))
    parts.append(add_pipe("FootL", r, FOOT_PIPE_LEN, (-half, 0, 23.6), "Y", pipe_mat))
    parts.append(add_pipe("FootR", r, FOOT_PIPE_LEN, (half, 0, 23.6), "Y", pipe_mat))

    bpy.ops.mesh.primitive_plane_add(size=6000, location=(0, 0, -0.01))
    ground = bpy.context.active_object
    ground.name = "Ground_RenderOnly"
    gmat = bpy.data.materials.new("Ground")
    gmat.use_nodes = True
    gmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        0.55, 0.55, 0.55, 1)
    ground.data.materials.append(gmat)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1100
    scene.render.resolution_y = 850
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(
        OUT_DIR, "orange_5ft_race_gate_preview.png")
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.85, 0.85, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.7

    bpy.ops.object.empty_add(location=(0, 0, 780))
    target = bpy.context.active_object
    target.name = "CameraTarget"
    bpy.ops.object.camera_add(location=(2700, -3900, 1550))
    cam = bpy.context.active_object
    track = cam.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    cam.data.lens = 50
    cam.data.clip_end = 20000  # mm-scale scene: gate is ~3000 from camera
    scene.camera = cam

    bpy.ops.object.light_add(type="AREA", location=(900, -700, 2200))
    key = bpy.context.active_object
    key.data.energy = 25000000
    key.data.size = 1500
    bpy.ops.object.light_add(type="AREA", location=(-1400, 900, 1100))
    fill = bpy.context.active_object
    fill.data.energy = 10000000
    fill.data.size = 1500
    return parts


def main():
    clean_scene()
    joint_mat = orange_material()
    pipe_mat = orange_material("OrangePipe", shade=(1.0, 0.45, 0.08))

    elbow = build_elbow(joint_mat)
    export_stl(elbow, "gate_corner_elbow.stl")
    foot_l = build_foot(joint_mat, +1, "Left")
    export_stl(foot_l, "gate_foot_corner_left.stl")
    foot_r = build_foot(joint_mat, -1, "Right")
    export_stl(foot_r, "gate_foot_corner_right.stl")

    build_assembly(elbow, foot_l, foot_r, joint_mat, pipe_mat)
    # Hide the loose parts at the origin; the assembly copies are the scene.
    for obj in (elbow, foot_l, foot_r):
        obj.hide_render = True
        obj.hide_set(True)
    bpy.ops.wm.save_as_mainfile(
        filepath=os.path.join(OUT_DIR, "orange_5ft_race_gate_assembly.blend"))
    bpy.ops.render.render(write_still=True)
    print("WROTE assembly .blend and preview .png")
    print(f"PIPE_CUT post 2x {POST_LEN:.0f}  bar 2x {BAR_LEN:.0f}  "
          f"foot 2x {FOOT_PIPE_LEN:.0f}  total "
          f"{2 * (POST_LEN + BAR_LEN + FOOT_PIPE_LEN):.0f} mm")


if __name__ == "__main__":
    main()
