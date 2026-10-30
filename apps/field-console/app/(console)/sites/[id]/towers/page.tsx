"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { sessionStore } from "@/lib/client";

interface LocationNode {
  id: string;
  code: string;
  fl_code: string;
  kind: string;
  sector_code?: string;
  height_m?: number;
  path: string;
  children?: LocationNode[];
  installed_equipment?: {
    serial_no: string;
    erp_equipment_no: string;
    material: string;
    equipment_class: string;
    pinned_model_version?: string;
    since: string;
  }[];
}

interface SiteDetail {
  id: string;
  code: string;
  name: string;
  kind: string;
  status: string;
  lat: number;
  lon: number;
  last_audit_date: string | null;
}

export default function SiteTowerExplorerPage() {
  const params = useParams();
  const siteId = params?.id as string;

  const [site, setSite] = useState<SiteDetail | null>(null);
  const [tree, setTree] = useState<LocationNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<LocationNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadSiteAndTree() {
      if (!siteId) return;
      try {
        setLoading(true);
        const headers = {
          Authorization: `Bearer ${sessionStore.get()?.accessToken ?? ""}`,
        };

        // 1. Fetch site metadata
        const siteRes = await fetch(`/v1/sites/${siteId}`, { headers });
        if (siteRes.status === 403 || siteRes.status === 401) {
          setError("Access denied. You do not have permission to view this site.");
          return;
        }
        if (siteRes.status === 404) {
          setError("Site not found or out of authorized scope.");
          return;
        }
        if (!siteRes.ok) {
          throw new Error(`Failed to load site details: ${siteRes.statusText}`);
        }
        const siteData = await siteRes.json();
        setSite(siteData);

        // 2. Fetch site location tree with installed equipment
        const treeRes = await fetch(`/v1/sites/${siteId}/tree?include_equipment=true`, { headers });
        if (treeRes.ok) {
          const treeData = await treeRes.json();
          setTree(treeData.nodes || []);
          if (treeData.nodes && treeData.nodes.length > 0) {
            setSelectedNode(treeData.nodes[0]);
          }
        }
      } catch (err: any) {
        setError(err.message || "Failed to load tower explorer.");
      } finally {
        setLoading(false);
      }
    }
    loadSiteAndTree();
  }, [siteId]);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Breadcrumb & Metadata */}
      <div className="flex justify-between items-start border-b pb-4">
        <div>
          <div className="text-xs text-gray-400 mb-1">
            <Link href="/sites" className="hover:underline">
              Sites
            </Link>{" "}
            &gt; {site ? site.code : siteId} &gt; Tower Explorer
          </div>
          <h1 className="text-2xl font-bold tracking-tight">
            {site ? `${site.name} (${site.code})` : "Tower Explorer"}
          </h1>
          <p className="text-sm text-gray-500">
            {site?.last_audit_date
              ? `Last audit: ${new Date(site.last_audit_date).toLocaleDateString()}`
              : "Last audit: Never audited"}
          </p>
        </div>
        <div className="flex gap-3">
          <Link
            href={`/sites/${siteId}/graph`}
            className="px-3 py-1.5 border rounded text-sm hover:bg-gray-50"
          >
            3D Lattice Graph
          </Link>
          <Link
            href={`/v1/sites/${siteId}/pack`}
            className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            Download Site Pack
          </Link>
        </div>
      </div>

      {loading && (
        <div className="p-12 text-center text-gray-500 text-sm animate-pulse">
          Loading tower structure and installed base...
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded text-sm">
          {error}
        </div>
      )}

      {!loading && !error && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Location Tree Panel */}
          <div className="border rounded-lg p-4 bg-white shadow-sm md:col-span-1 space-y-3">
            <h2 className="font-semibold text-sm uppercase tracking-wide text-gray-500 border-b pb-2">
              Structure Hierarchy Tree
            </h2>

            {tree.length === 0 ? (
              <p className="text-xs text-gray-400 p-4 text-center">
                No location hierarchy imported for this site.
              </p>
            ) : (
              <div className="space-y-1 text-sm max-h-[600px] overflow-y-auto">
                {tree.map((node) => (
                  <button
                    key={node.id}
                    onClick={() => setSelectedNode(node)}
                    className={`w-full text-left px-3 py-2 rounded text-xs transition flex justify-between items-center ${
                      selectedNode?.id === node.id
                        ? "bg-blue-50 text-blue-800 font-semibold border border-blue-200"
                        : "hover:bg-gray-50 text-gray-700"
                    }`}
                  >
                    <span>
                      <span className="font-mono text-gray-400 mr-2">{node.kind}</span>
                      {node.code}
                    </span>
                    {node.height_m !== undefined && (
                      <span className="text-[10px] text-gray-400 font-mono">
                        {node.height_m}m
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Position Detail & Installed Equipment Panel */}
          <div className="border rounded-lg p-5 bg-white shadow-sm md:col-span-2 space-y-5">
            {selectedNode ? (
              <>
                <div className="border-b pb-3 flex justify-between items-start">
                  <div>
                    <span className="text-xs uppercase tracking-wider font-semibold text-blue-600">
                      Position Detail Panel
                    </span>
                    <h2 className="text-xl font-bold">{selectedNode.code}</h2>
                    <p className="font-mono text-xs text-gray-500">{selectedNode.fl_code}</p>
                  </div>
                  <div className="text-right text-xs text-gray-500 space-y-0.5">
                    <p>
                      <strong>Kind:</strong> {selectedNode.kind}
                    </p>
                    {selectedNode.sector_code && (
                      <p>
                        <strong>Sector:</strong> {selectedNode.sector_code}
                      </p>
                    )}
                    {selectedNode.height_m !== undefined && (
                      <p>
                        <strong>Elevation:</strong> {selectedNode.height_m} m
                      </p>
                    )}
                  </div>
                </div>

                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-gray-700">
                    Installed Equipment at this Position
                  </h3>

                  {!selectedNode.installed_equipment ||
                  selectedNode.installed_equipment.length === 0 ? (
                    <div className="p-8 text-center border-2 border-dashed rounded text-xs text-gray-400">
                      Position is currently empty (no active installed equipment segment).
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {selectedNode.installed_equipment.map((eq) => (
                        <div
                          key={eq.serial_no}
                          className="border rounded p-4 bg-gray-50 space-y-2 text-xs"
                        >
                          <div className="flex justify-between items-center">
                            <span className="font-bold text-sm text-gray-900 font-mono">
                              SN: {eq.serial_no}
                            </span>
                            <span className="bg-green-100 text-green-800 px-2 py-0.5 rounded font-mono text-[11px]">
                              INSTALLED
                            </span>
                          </div>
                          <div className="grid grid-cols-2 gap-2 text-gray-600">
                            <p>
                              <strong>Material:</strong> {eq.material}
                            </p>
                            <p>
                              <strong>ERP Eq No:</strong> {eq.erp_equipment_no || "N/A"}
                            </p>
                            <p>
                              <strong>Class:</strong> {eq.equipment_class}
                            </p>
                            <p>
                              <strong>Pinned Model:</strong>{" "}
                              {eq.pinned_model_version || "Unpinned"}
                            </p>
                            <p className="col-span-2 text-gray-400">
                              <strong>Installed Since:</strong>{" "}
                              {new Date(eq.since).toLocaleString()}
                            </p>
                          </div>
                          <div className="pt-2 border-t flex gap-3 text-blue-600">
                            <Link
                              href={`/v1/equipment/${eq.serial_no}/trail`}
                              className="hover:underline font-medium"
                            >
                              View Custody Trail &rarr;
                            </Link>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="p-12 text-center text-gray-400 text-xs">
                Select a structure position from the tree to view installed assets.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
