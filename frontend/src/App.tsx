import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { GeointView } from './views/GeointView';
import { DocumentView } from './views/DocumentView';
import { CollaborationView } from './views/CollaborationView';
import { OsintView } from './views/OsintView';
import { SupplyChainView } from './views/SupplyChainView';
import { ComplianceView } from './views/ComplianceView';
import { LagebildView } from './views/LagebildView';

// Minimal fallback for unknown routes.
function NotFound() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
        <div className="text-sm uppercase tracking-wider text-slate-500">
          404
        </div>
        <div className="mt-1 text-lg font-semibold text-slate-900">
          Seite nicht gefunden
        </div>
      </div>
    </div>
  );
}

// Routed shell — all six use cases are nested under the dark Layout.
function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/geoint" replace />} />
        <Route path="/geoint" element={<GeointView />} />
        <Route path="/documents" element={<DocumentView />} />
        <Route path="/collaboration" element={<CollaborationView />} />
        <Route path="/osint" element={<OsintView />} />
        <Route path="/lagebild" element={<LagebildView />} />
        <Route path="/supply-chain" element={<SupplyChainView />} />
        <Route path="/compliance" element={<ComplianceView />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export default App;
