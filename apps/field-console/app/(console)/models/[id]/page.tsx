"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ModelViewer, { BomItem } from "@/components/ModelViewer/ModelViewer";
import { sessionStore } from "@/lib/client";
import { uuid7 } from "@/lib/uuid7";

function authHeaders(): Record<string, string> {
  const s = sessionStore.get();
  return s ? { Authorization: `Bearer ${s.accessToken}` } : {};
}

/**
 * Asset Model 3D Exploded View & BOM Route Page (Task T4.057 / SCR4.09 / FR4.056 / TC4.148).
 *
 * Implements:
 * - SCR4.09: 3D scene-graph canvas with orbit rotation, explode slider t in [0, 1].
 * - Interactive balloon annotations, part isolation, serialised part flags.
 * - Model details header with version tag, publishing status, and step-up publish trigger.
 */

interface ModelDetails {
  id: string;
  equipment_class: string;
  version: string;
  status: "draft" | "published" | "superseded";
  file_size_bytes?: number;
  triangle_count?: number;
  sha256_hash?: string;
  published_at?: string | null;
}

export default function ModelDetailPage() {
  const params = useParams();
  const modelId = typeof params?.id === "string" ? params.id : "";

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState<ModelDetails | null>(null);
  const [bomItems, setBomItems] = useState<BomItem[]>([]);
  const [publishing, setPublishing] = useState<boolean>(false);
  const [publishSuccess, setPublishSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!modelId) return;

    async function fetchModelAndBom() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/v1/asset-models/${modelId}/bom`, {
          headers: authHeaders(),
        });

        if (!res.ok) {
          throw new Error(`Failed to load model BOM (${res.status})`);
        }

        const data = await res.json();
        setModel({
          id: data.model_id || modelId,
          equipment_class: data.equipment_class || "Unknown class",
          version: data.version || "?",
          status: data.status || "draft",
        });

        const items: BomItem[] = (data.items || []).map((it: any) => ({
          balloon_no: it.balloon_no ?? null,
          part_no: it.part_no,
          description: it.description || it.part_no,
          qty: it.qty ?? 1,
          is_serialised: Boolean(it.is_serialised || it.serialised),
          node_names: it.node_names || [],
          explode_vector: it.explode_vector || [0, 0, 0],
          parent_part_no: it.parent_part_no ?? null,
          node_path: it.node_path,
        }));

        setBomItems(items);
      } catch (err: any) {
        setError(err instanceof Error ? err.message : "Could not load the model from field-api.");
      } finally {
        setLoading(false);
      }
    }

    fetchModelAndBom();
  }, [modelId]);

  const handlePublish = async () => {
    if (!modelId) return;
    setPublishing(true);
    setPublishSuccess(null);
    setError(null);
    try {
      const res = await fetch(`/v1/asset-models/${modelId}/publish`, {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json", "Idempotency-Key": uuid7() },
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Publish failed (${res.status})`);
      }

      setPublishSuccess("Model version published successfully!");
      if (model) {
        setModel({ ...model, status: "published" });
      }
    } catch (err: any) {
      setError(err.message || "Failed to publish model version");
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[500px]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-500 font-mono text-sm">Loading 3D asset model & BOM schema...</p>
        </div>
      </div>
    );
  }

  if (!model) {
    return (
      <div role="alert" className="rounded-card border border-alert-line bg-alert-bg p-5 text-alert-ink">
        <b>Could not load this asset model.</b> {error ?? "field-api returned no model."}
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-200 pb-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">
              {model?.equipment_class || "Asset Model"}
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 font-mono">
              v{model?.version || "1.0.0"}
            </span>
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wide ${
                model?.status === "published"
                  ? "bg-green-100 text-green-800"
                  : "bg-amber-100 text-amber-800"
              }`}
            >
              {model?.status || "draft"}
            </span>
          </div>
          <p className="text-sm text-gray-500 font-mono mt-1">
            Model ID: {modelId}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {model?.status !== "published" && (
            <button
              onClick={handlePublish}
              disabled={publishing}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-md text-sm font-medium shadow-sm transition-colors flex items-center gap-2"
            >
              {publishing ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Publishing...
                </>
              ) : (
                "Publish Version"
              )}
            </button>
          )}
        </div>
      </div>

      {publishSuccess && (
        <div className="p-4 bg-green-50 border border-green-200 text-green-700 rounded-md text-sm">
          {publishSuccess}
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md text-sm">
          {error}
        </div>
      )}

      {/* Model Viewer Component */}
      <ModelViewer
        modelId={modelId}
        equipmentClass={model?.equipment_class || "Equipment"}
        version={model?.version || "1.0.0"}
        bomItems={bomItems}
      />
    </div>
  );
}
