'use client';

import { useRole } from '@/context/RoleContext';
import { matrixHeaders } from '@/data/roles';

export default function DataAccessMatrix() {
  const { roleConfig } = useRole();

  const getCellClass = (cell: string) => {
    if (cell === '✓' || cell === '✓*') return 'check';
    if (cell === '✗') return 'cross';
    if (cell === '—') return 'partial';
    return '';
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Data Access Matrix</span>
        <span className="panel-meta">Your permissions</span>
      </div>
      <table className="matrix-table">
        <thead>
          <tr>
            {matrixHeaders.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {roleConfig.matrix.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className={getCellClass(cell)}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
