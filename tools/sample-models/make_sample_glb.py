"""glTF 2.0 Binary (.glb) Generator and Sample Model Builder (Task T4.055 / FR4.051 / TC4.145).

Constructs compliant glTF 2.0 binary files containing mesh primitives, accessors,
buffer views, node hierarchies, and material definitions without external URIs.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path


def create_glb_binary(
    nodes: list[dict[str, any]],
    triangle_count: int = 12,
    has_external_uri: bool = False,
) -> bytes:
    """Create compliant .glb binary bytes."""
    # 1. Generate minimal vertex buffers: 3 vertices per triangle or a cube
    # For simplicity, generate float32 position vertices: (x, y, z)
    # 3 floats * 4 bytes = 12 bytes per vertex.
    num_vertices = triangle_count * 3
    positions = []
    for i in range(num_vertices):
        positions.extend([float(i % 10), float((i * 2) % 10), float((i * 3) % 10)])

    pos_bytes = struct.pack(f"<{len(positions)}f", *positions)
    # Pad to 4-byte boundary
    pad_len = (4 - (len(pos_bytes) % 4)) % 4
    bin_data = pos_bytes + (b"\x00" * pad_len)

    # 2. Build glTF JSON metadata
    gltf_nodes = []
    scene_nodes = []
    for idx, n in enumerate(nodes):
        gltf_nodes.append({
            "name": n.get("name", f"node_{idx}"),
            "mesh": 0,
            "translation": n.get("translation", [0.0, 0.0, 0.0]),
        })
        scene_nodes.append(idx)

    buffer_dict = {
        "byteLength": len(bin_data),
    }
    if has_external_uri:
        buffer_dict["uri"] = "http://external.assets.com/malicious.bin"

    gltf_dict = {
        "asset": {"version": "2.0", "generator": "SCMTips-Field-Builder"},
        "scenes": [{"nodes": scene_nodes}],
        "nodes": gltf_nodes,
        "meshes": [
            {
                "name": "SampleMesh",
                "primitives": [
                    {
                        "mode": 4,  # TRIANGLES
                        "attributes": {"POSITION": 0},
                    }
                ],
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5126,  # FLOAT
                "count": num_vertices,
                "type": "VEC3",
                "max": [10.0, 10.0, 10.0],
                "min": [0.0, 0.0, 0.0],
            }
        ],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(pos_bytes),
                "target": 34962,  # ARRAY_BUFFER
            }
        ],
        "buffers": [buffer_dict],
    }

    json_str = json.dumps(gltf_dict)
    json_bytes = json_str.encode("utf-8")
    # Pad JSON chunk with spaces (0x20) to 4-byte boundary per glTF 2.0 spec
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    json_bytes += b" " * json_pad

    # 3. Structure glTF chunks
    # Chunk 0: JSON
    chunk0_header = struct.pack("<II", len(json_bytes), 0x4E4F534A)  # 0x4E4F534A == 'JSON'
    chunk0 = chunk0_header + json_bytes

    # Chunk 1: BIN
    chunk1_header = struct.pack("<II", len(bin_data), 0x004E4942)  # 0x004E4942 == 'BIN\x00'
    chunk1 = chunk1_header + bin_data

    # Main Header: magic (4) + version (4) + length (4)
    total_len = 12 + len(chunk0) + len(chunk1)
    main_header = struct.pack("<III", 0x46546C67, 2, total_len)  # 0x46546C67 == 'glTF'

    return main_header + chunk0 + chunk1


def build_sample_files() -> None:
    sample_dir = Path(r"<repo>\tools\sample-models")
    sample_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build RRU sample model (nodes: psu, fan, rru_housing, connector_a, connector_b)
    nodes = [
        {"name": "rru_housing", "translation": [0.0, 0.0, 0.0]},
        {"name": "psu", "translation": [0.0, 0.12, 0.0]},
        {"name": "fan", "translation": [0.0, -0.15, 0.0]},
        {"name": "connector_a", "translation": [0.1, 0.0, 0.0]},
        {"name": "connector_b", "translation": [-0.1, 0.0, 0.0]},
    ]
    rru_glb = create_glb_binary(nodes, triangle_count=120)
    (sample_dir / "rru_model.glb").write_bytes(rru_glb)

    # 2. Build matching RRU BOM CSV
    bom_csv = (
        "part_no,description,qty,is_serialised,parent_part_no,node_path,node_names,explode_vector_x,explode_vector_y,explode_vector_z\n"
        "RRU-HSG-01,RRU Aluminium Housing,1,false,,housing,rru_housing,0.0,0.0,0.0\n"
        "PSU-48V-2K,Power Supply Unit 48V,1,true,,housing/psu,psu,0.0,0.12,0.0\n"
        "FAN-BLWR-01,Blower Fan Module,1,true,,housing/fan,fan,0.0,-0.15,0.0\n"
        "RF-CONN-716,7/16 DIN RF Connector,2,false,,housing/rf,connector_a|connector_b,0.1,0.0,0.0\n"
    )
    (sample_dir / "rru_bom.csv").write_text(bom_csv, encoding="utf-8")
    print(f"Sample models written to {sample_dir}")


if __name__ == "__main__":
    build_sample_files()
