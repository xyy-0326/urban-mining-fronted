# -*- coding: utf-8 -*-
"""
导出当前 Rhino 文件中的 Block 实例为 glTF 2.0 二进制 (.glb)

- 兼容 Rhino 的 IronPython（无 Python3 特性）
- 只导出 Block 实例（InstanceObject）
- 每个 Block 实例合成一个大 Mesh
- 元数据写入：
    mesh.name  = block_name
    node.name  = block_name_0001
    node.extras.block_name = block_name
    node.extras.layer      = layer_full_path
"""

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os
import json
import struct


# ------------------ 工具函数 ------------------

def float32_array(lst):
    return struct.pack("<%sf" % len(lst), *[float(x) for x in lst])

def uint32_array(lst):
    return struct.pack("<%sI" % len(lst), *[int(x) for x in lst])

def pad4(data):
    """4 字节对齐，并确保返回 bytes 类型"""
    if isinstance(data, bytearray):
        data = bytes(data)
    pad = (4 - (len(data) % 4)) % 4
    if pad:
        data += b"\x00" * pad
    return data

def mesh_from_geometry(geo):
    """把各种 Rhino 几何转成 Mesh"""
    if isinstance(geo, Rhino.Geometry.Mesh):
        m = geo.DuplicateMesh()
        m.Faces.ConvertQuadsToTriangles()
        m.Normals.ComputeNormals()
        m.Compact()
        return m

    if isinstance(geo, Rhino.Geometry.Brep):
        meshes = Rhino.Geometry.Mesh.CreateFromBrep(
            geo, Rhino.Geometry.MeshingParameters.Default
        )
        if not meshes:
            return None
        m = Rhino.Geometry.Mesh()
        for mm in meshes:
            mm.Faces.ConvertQuadsToTriangles()
            mm.Normals.ComputeNormals()
            mm.Compact()
            m.Append(mm)
        m.Compact()
        return m

    if isinstance(geo, Rhino.Geometry.Extrusion):
        m = Rhino.Geometry.Mesh.CreateFromExtrusion(
            geo, Rhino.Geometry.MeshingParameters.Default
        )
        if m:
            m.Faces.ConvertQuadsToTriangles()
            m.Normals.ComputeNormals()
            m.Compact()
        return m

    return None


# ------------------ 收集 Block 实例 ------------------

def collect_block_instance_meshes():
    """
    返回列表 [(block_name, layer_name, combined_mesh), ...]
    每个元素对应一个顶层 Block 实例。
    """
    doc = sc.doc
    instance_objects = [o for o in doc.Objects
                        if isinstance(o, Rhino.DocObjects.InstanceObject)]

    results = []

    for inst_obj in instance_objects:
        idef = inst_obj.InstanceDefinition
        if idef is None:
            continue

        block_name = idef.Name or "Block"

        # 图层名称（完整路径，包含子图层）
        layer_name = ""
        layer_index = inst_obj.Attributes.LayerIndex
        if 0 <= layer_index < doc.Layers.Count:
            layer = doc.Layers[layer_index]
            try:
                layer_name = layer.FullPath
            except:
                layer_name = layer.Name

        combined = Rhino.Geometry.Mesh()
        xform = inst_obj.InstanceXform

        for oid in idef.GetObjectIds():
            src_obj = doc.Objects.Find(oid)
            if not src_obj:
                continue
            geo = src_obj.Geometry
            m = mesh_from_geometry(geo)
            if not m:
                continue
            m.Transform(xform)
            combined.Append(m)

        if combined.Vertices.Count > 0 and combined.Faces.Count > 0:
            combined.Faces.ConvertQuadsToTriangles()
            combined.Normals.ComputeNormals()
            combined.Compact()
            results.append((block_name, layer_name, combined))

    return results


# ------------------ 构建 glTF JSON & 二进制 Buffer ------------------

def build_gltf_dict_and_bin(block_meshes):
    gltf = {
        "asset": {"version": "2.0", "generator": "RhinoPython BlockToGLB"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "buffers": [],
        "bufferViews": [],
        "accessors": []
    }

    buffer_data = bytearray()

    def add_buffer_view(data_bytes, target):
        offset = len(buffer_data)
        data_bytes_padded = pad4(data_bytes)
        buffer_data.extend(data_bytes_padded)
        view_index = len(gltf["bufferViews"])
        gltf["bufferViews"].append({
            "buffer": 0,
            "byteOffset": int(offset),
            "byteLength": int(len(data_bytes_padded)),
            "target": int(target)
        })
        return view_index

    def add_accessor(view_idx, component_type, count, type_str,
                     min_val=None, max_val=None):
        acc = {
            "bufferView": int(view_idx),
            "componentType": int(component_type),
            "count": int(count),
            "type": type_str
        }
        if min_val is not None:
            acc["min"] = [float(v) for v in min_val]
        if max_val is not None:
            acc["max"] = [float(v) for v in max_val]
        idx = len(gltf["accessors"])
        gltf["accessors"].append(acc)
        return idx

    ARRAY = 34962            # GL_ARRAY_BUFFER
    ELEMENT = 34963          # GL_ELEMENT_ARRAY_BUFFER
    FLOAT = 5126             # FLOAT
    UINT = 5125              # UNSIGNED_INT

    for i, (block_name, layer_name, mesh) in enumerate(block_meshes):

        # positions
        pos = []
        for v in mesh.Vertices:
            pos.extend([float(v.X), float(v.Y), float(v.Z)])
        if not pos:
            continue

        xs = pos[0::3]
        ys = pos[1::3]
        zs = pos[2::3]

        pos_min = [float(min(xs)), float(min(ys)), float(min(zs))]
        pos_max = [float(max(xs)), float(max(ys)), float(max(zs))]

        pos_bytes = float32_array(pos)
        pos_view = add_buffer_view(pos_bytes, ARRAY)
        pos_count = int(len(pos) / 3)
        pos_acc = add_accessor(pos_view, FLOAT, pos_count,
                               "VEC3", pos_min, pos_max)

        # normals
        mesh.Normals.ComputeNormals()
        norm = []
        for n in mesh.Normals:
            norm.extend([float(n.X), float(n.Y), float(n.Z)])
        norm_bytes = float32_array(norm)
        norm_view = add_buffer_view(norm_bytes, ARRAY)
        norm_count = int(len(norm) / 3)
        norm_acc = add_accessor(norm_view, FLOAT, norm_count, "VEC3")

        # indices
        idx_list = []
        for f in mesh.Faces:
            if f.IsTriangle:
                idx_list.extend([int(f.A), int(f.B), int(f.C)])
        idx_bytes = uint32_array(idx_list)
        idx_view = add_buffer_view(idx_bytes, ELEMENT)
        idx_acc = add_accessor(idx_view, UINT, int(len(idx_list)), "SCALAR")

        # mesh primitive
        mesh_dict = {
            "primitives": [{
                "attributes": {"POSITION": pos_acc, "NORMAL": norm_acc},
                "indices": idx_acc
            }],
            "name": block_name
        }

        mesh_index = len(gltf["meshes"])
        gltf["meshes"].append(mesh_dict)

        node_index = len(gltf["nodes"])
        node_name = "%s_%03d" % (block_name, i + 1)
        gltf["nodes"].append({
            "mesh": int(mesh_index),
            "name": node_name,
            "extras": {
                "block_name": block_name,
                "layer": layer_name
            }
        })

        gltf["scenes"][0]["nodes"].append(int(node_index))

    # buffer（GLB 中不需要 uri）
    gltf["buffers"].append({
        "byteLength": int(len(buffer_data))
    })

    return gltf, buffer_data


# ------------------ 写出 GLB ------------------

def write_glb(filepath, gltf_dict, bin_data):
    # JSON chunk
    json_str = json.dumps(gltf_dict, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")
    json_bytes = pad4(json_bytes)       # bytes, 4 字节对齐

    # BIN chunk
    bin_bytes = pad4(bin_data)          # bytearray -> bytes, 4 字节对齐

    # Header
    magic = b"glTF"
    version = 2
    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)

    header = struct.pack("<4sII", magic, version, total_length)

    # chunk headers
    json_header = struct.pack("<I4s", len(json_bytes), b"JSON")
    bin_header  = struct.pack("<I4s", len(bin_bytes),  b"BIN\x00")

    data = header + json_header + json_bytes + bin_header + bin_bytes

    with open(filepath, "wb") as f:
        f.write(data)


# ------------------ 主导出函数 ------------------

def export_blocks_to_glb():
    block_meshes = collect_block_instance_meshes()
    if not block_meshes:
        rs.MessageBox("没有找到 Block 实例。", 0, "错误")
        return

    path = rs.SaveFileName(
        "保存 GLB 文件",
        "glTF Binary (*.glb)|*.glb||"
    )
    if not path:
        return

    path = os.path.normpath(path)

    gltf_dict, bin_data = build_gltf_dict_and_bin(block_meshes)
    write_glb(path, gltf_dict, bin_data)

    rs.MessageBox("导出完成：\n%s" % path, 0, "完成")


if __name__ == "__main__":
    export_blocks_to_glb()
