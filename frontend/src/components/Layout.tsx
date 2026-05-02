import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

// App shell: 240px dark sidebar on the left, content area on the right.
export function Layout() {
  return (
    <div
      className="grid h-screen w-screen bg-[#1A1816]"
      style={{ gridTemplateColumns: '240px 1fr' }}
    >
      <Sidebar />
      <div className="flex h-screen min-w-0 flex-col bg-[#F5F4F2] text-slate-900">
        <TopBar />
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default Layout;
