'use client';

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';

import { ApiException, apiUpload, type SuccessEnvelope } from '@/lib/api';


/** Shared shape of the per-row error returned by both bulk endpoints. */
export interface BulkRowError {
  line_number: number;
  raw_row: Record<string, string>;
  error: string;
}


/* ─── Aid coverage bulk upload (Module 02, Slice 02.live) ─────────────── */


export interface BulkCoverageUploadResult {
  tenant_id: string;
  source: string;
  rows_received: number;
  rows_inserted: number;
  rows_skipped: number;
  errors: BulkRowError[];
}


export interface BulkCoverageUploadVariables {
  tenantId: string;
  file: File;
  source: string;
}


export function useBulkAidCoverageUpload(): UseMutationResult<
  BulkCoverageUploadResult,
  ApiException,
  BulkCoverageUploadVariables
> {
  const qc = useQueryClient();
  return useMutation<BulkCoverageUploadResult, ApiException, BulkCoverageUploadVariables>({
    mutationFn: async (vars) => {
      const fd = new FormData();
      fd.append('file', vars.file, vars.file.name);
      fd.append('source', vars.source);
      const envelope: SuccessEnvelope<BulkCoverageUploadResult> =
        await apiUpload<BulkCoverageUploadResult>(
          '/aid_coordination/coverage/bulk',
          fd,
          { tenantId: vars.tenantId },
        );
      return envelope.data;
    },
    onSuccess: (_data, vars) => {
      // Invalidate any aid-coordination queries for this tenant so the
      // matrix + stats refetch the just-uploaded rows.
      qc.invalidateQueries({ queryKey: ['aid-coordination', vars.tenantId] });
      qc.invalidateQueries({ queryKey: ['intelligence-feed'] });
    },
  });
}


/* ─── Crop prices bulk upload (Module 04, Slice 04.b.live) ────────────── */


export interface BulkPriceUploadResult {
  source: string;
  rows_received: number;
  rows_inserted: number;
  rows_skipped: number;
  crops_seen: string[];
  regions_seen: string[];
  errors: BulkRowError[];
}


export interface BulkPriceUploadVariables {
  file: File;
  source: string;
}


export function useBulkCropPriceUpload(): UseMutationResult<
  BulkPriceUploadResult,
  ApiException,
  BulkPriceUploadVariables
> {
  const qc = useQueryClient();
  return useMutation<BulkPriceUploadResult, ApiException, BulkPriceUploadVariables>({
    mutationFn: async (vars) => {
      const fd = new FormData();
      fd.append('file', vars.file, vars.file.name);
      fd.append('source', vars.source);
      const envelope: SuccessEnvelope<BulkPriceUploadResult> =
        await apiUpload<BulkPriceUploadResult>(
          '/cropguard/prices/bulk',
          fd,
          {},  // crop_prices is cross-tenant, no X-Tenant-Id
        );
      return envelope.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['crop-prices'] });
      qc.invalidateQueries({ queryKey: ['intelligence-feed'] });
    },
  });
}
